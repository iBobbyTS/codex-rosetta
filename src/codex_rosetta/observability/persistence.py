"""SQLite-based persistence for observability data.

Stores request log entries and metrics counters in a single SQLite
database (``gateway.db``) using WAL journal mode. The pre-release system
does not provide a compatibility migration layer; incompatible legacy data
must be removed or rebuilt by the operator before startup.

This module is framework-agnostic and can be used by any consumer
(the codex-rosetta gateway, argo-proxy, or standalone scripts).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .redaction import SecretRedactor
from .retention import (
    DEFAULT_ERROR_MAX,
    DEFAULT_SUCCESS_MAX,
    validate_retention_cap,
)

logger = logging.getLogger("codex-rosetta.observability")

_DB_FILENAME = "gateway.db"

DEFAULT_TOOL_MAPPING_MAX_ROW_BYTES = 16 * 1024 * 1024
DEFAULT_TOOL_MAPPING_MAX_PRINCIPAL_ROWS = 8_192
DEFAULT_TOOL_MAPPING_MAX_PRINCIPAL_BYTES = 256 * 1024 * 1024
DEFAULT_TOOL_MAPPING_MAX_GLOBAL_ROWS = 32_768
DEFAULT_TOOL_MAPPING_MAX_GLOBAL_BYTES = 512 * 1024 * 1024

# Remote-compaction summaries are plaintext prompt-derived state. Keep their
# rolling TTL, but also enforce explicit row/byte ceilings so a valid client
# cannot grow the shared SQLite store without bound.
DEFAULT_CODEX_COMPACTION_MAX_ROW_BYTES = 1 * 1024 * 1024
DEFAULT_CODEX_COMPACTION_MAX_PRINCIPAL_ROWS = 1_024
DEFAULT_CODEX_COMPACTION_MAX_PRINCIPAL_BYTES = 64 * 1024 * 1024
DEFAULT_CODEX_COMPACTION_MAX_GLOBAL_ROWS = 8_192
DEFAULT_CODEX_COMPACTION_MAX_GLOBAL_BYTES = 512 * 1024 * 1024

# Legacy filenames for migration
_LEGACY_LOG = "request_log.jsonl"
_LEGACY_METRICS = "metrics.json"

# SQLite does not repair an existing table when CREATE TABLE IF NOT EXISTS is
# used. Validate the complete supported shape so incompatible pre-release state
# fails during startup instead of on the first write.
_EXPECTED_SCHEMA_COLUMNS: dict[str, tuple[tuple[str, str, int, int], ...]] = {
    "request_log": (
        ("id", "TEXT", 0, 1),
        ("timestamp", "TEXT", 1, 0),
        ("model", "TEXT", 1, 0),
        ("source_provider", "TEXT", 1, 0),
        ("target_provider", "TEXT", 1, 0),
        ("is_stream", "INTEGER", 1, 0),
        ("status_code", "INTEGER", 1, 0),
        ("duration_ms", "REAL", 1, 0),
        ("error_detail", "TEXT", 0, 0),
        ("api_key_label", "TEXT", 0, 0),
        ("target_provider_name", "TEXT", 0, 0),
        ("client_ip", "TEXT", 0, 0),
        ("profile", "TEXT", 0, 0),
    ),
    "metrics": (("key", "TEXT", 0, 1), ("value", "TEXT", 1, 0)),
    "dump_bodies": (
        ("hash", "TEXT", 0, 1),
        ("data", "BLOB", 1, 0),
        ("orig_bytes", "INTEGER", 1, 0),
        ("created", "TEXT", 1, 0),
    ),
    "error_dumps": (
        ("id", "TEXT", 0, 1),
        ("request_log_id", "TEXT", 0, 0),
        ("timestamp", "TEXT", 1, 0),
        ("model", "TEXT", 0, 0),
        ("source_provider", "TEXT", 0, 0),
        ("target_provider", "TEXT", 0, 0),
        ("provider_name", "TEXT", 0, 0),
        ("status_code", "INTEGER", 0, 0),
        ("error_phase", "TEXT", 0, 0),
        ("body_hash", "TEXT", 0, 0),
        ("response_text", "TEXT", 0, 0),
        ("upstream_url", "TEXT", 0, 0),
        ("converted_body_hash", "TEXT", 0, 0),
    ),
    "codex_compaction_mappings": (
        ("principal_id", "TEXT", 1, 1),
        ("token_hash", "TEXT", 1, 2),
        ("replacement_text", "TEXT", 1, 0),
        ("replacement_bytes", "INTEGER", 1, 0),
        ("source_model", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("prompt_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
        ("expires_at", "TEXT", 1, 0),
    ),
    "search_provider_state": (
        ("row_id", "TEXT", 0, 1),
        ("identity", "TEXT", 1, 0),
        ("is_current", "INTEGER", 1, 0),
        ("quota_exhausted", "INTEGER", 1, 0),
        ("quota_check_at", "REAL", 0, 0),
    ),
}

_EXPECTED_SCHEMA_INDEXES: dict[
    str, dict[str, tuple[tuple[str, ...], int, str, int]]
] = {
    "request_log": {
        "idx_rl_timestamp": (("timestamp",), 0, "c", 0),
        "idx_rl_status": (("status_code",), 0, "c", 0),
    },
    "error_dumps": {
        "idx_ed_timestamp": (("timestamp",), 0, "c", 0),
        "idx_ed_request_log": (("request_log_id",), 0, "c", 0),
    },
    "codex_compaction_mappings": {
        "idx_ccm_expire_at": (("expires_at",), 0, "c", 0),
        "idx_ccm_principal": (("principal_id",), 0, "c", 0),
    },
}


class CompactionMappingCapacityError(RuntimeError):
    """Plaintext remote-compaction state exceeded a configured hard budget."""


def _positive_tool_mapping_limit(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


@dataclass(frozen=True)
class PreparedPersistenceUpdate:
    """Validated persistence policy ready for one transactional commit."""

    redactor: SecretRedactor
    success_max: int
    error_max: int


@dataclass(frozen=True)
class PersistenceUpdateRollback:
    """Compensation data for a committed persistence-policy update."""

    redactor: SecretRedactor
    success_max: int
    error_max: int
    pruned_rows: tuple[tuple[Any, ...], ...]


class PersistenceManager:
    """SQLite-backed persistence for request logs and metrics.

    The request log uses a dual-threshold retention policy: successful
    requests (status_code < 400) and error requests (status_code >= 400)
    are pruned independently.  Errors typically make up a tiny fraction
    of traffic but are the most valuable rows to keep around for
    debugging, so they get their own cap that the success rotation
    cannot evict.

    Args:
        data_dir: Directory for the database file (created if missing).
        success_max: Maximum number of successful request log entries to
            retain.  Defaults to :data:`DEFAULT_SUCCESS_MAX`.
        error_max: Maximum number of error request log entries to retain
            (status_code >= 400).  Defaults to :data:`DEFAULT_ERROR_MAX`.
        token_values: Exact API-token values to redact from newly persisted
            diagnostics. Non-token diagnostic data is retained.
        tool_mapping_max_row_bytes: Maximum ciphertext plus metadata bytes per row.
        tool_mapping_max_principal_rows: Maximum rows owned by one principal.
        tool_mapping_max_principal_bytes: Maximum bytes owned by one principal.
        tool_mapping_max_global_rows: Maximum encrypted mapping rows in the database.
        tool_mapping_max_global_bytes: Maximum encrypted mapping bytes in the database.
        codex_compaction_max_row_bytes: Maximum replacement bytes per compaction row.
        codex_compaction_max_principal_rows: Maximum compaction rows per principal.
        codex_compaction_max_principal_bytes: Maximum compaction bytes per principal.
        codex_compaction_max_global_rows: Maximum compaction rows in the database.
        codex_compaction_max_global_bytes: Maximum compaction bytes in the database.
    """

    def __init__(
        self,
        data_dir: str,
        success_max: int | None = None,
        error_max: int | None = None,
        *,
        token_values: Iterable[str] = (),
        tool_mapping_max_row_bytes: int = DEFAULT_TOOL_MAPPING_MAX_ROW_BYTES,
        tool_mapping_max_principal_rows: int = DEFAULT_TOOL_MAPPING_MAX_PRINCIPAL_ROWS,
        tool_mapping_max_principal_bytes: int = DEFAULT_TOOL_MAPPING_MAX_PRINCIPAL_BYTES,
        tool_mapping_max_global_rows: int = DEFAULT_TOOL_MAPPING_MAX_GLOBAL_ROWS,
        tool_mapping_max_global_bytes: int = DEFAULT_TOOL_MAPPING_MAX_GLOBAL_BYTES,
        codex_compaction_max_row_bytes: int = DEFAULT_CODEX_COMPACTION_MAX_ROW_BYTES,
        codex_compaction_max_principal_rows: int = DEFAULT_CODEX_COMPACTION_MAX_PRINCIPAL_ROWS,
        codex_compaction_max_principal_bytes: int = DEFAULT_CODEX_COMPACTION_MAX_PRINCIPAL_BYTES,
        codex_compaction_max_global_rows: int = DEFAULT_CODEX_COMPACTION_MAX_GLOBAL_ROWS,
        codex_compaction_max_global_bytes: int = DEFAULT_CODEX_COMPACTION_MAX_GLOBAL_BYTES,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._success_max = validate_retention_cap(
            success_max if success_max is not None else DEFAULT_SUCCESS_MAX,
            field="success_max",
        )
        self._error_max = validate_retention_cap(
            error_max if error_max is not None else DEFAULT_ERROR_MAX,
            field="error_max",
        )
        self._insert_count = 0
        self._redactor = SecretRedactor(token_values)
        self._mapping_cipher: Any | None = None
        self._tool_history_store: Any | None = None
        self._chat_tool_surface_store: Any | None = None
        self._tool_mapping_lock = threading.RLock()
        self._compaction_mapping_lock = threading.RLock()
        self._search_provider_state_lock = threading.RLock()
        self._tool_mapping_max_row_bytes = _positive_tool_mapping_limit(
            tool_mapping_max_row_bytes,
            field="tool_mapping_max_row_bytes",
        )
        self._tool_mapping_max_principal_rows = _positive_tool_mapping_limit(
            tool_mapping_max_principal_rows,
            field="tool_mapping_max_principal_rows",
        )
        self._tool_mapping_max_principal_bytes = _positive_tool_mapping_limit(
            tool_mapping_max_principal_bytes,
            field="tool_mapping_max_principal_bytes",
        )
        self._tool_mapping_max_global_rows = _positive_tool_mapping_limit(
            tool_mapping_max_global_rows,
            field="tool_mapping_max_global_rows",
        )
        self._tool_mapping_max_global_bytes = _positive_tool_mapping_limit(
            tool_mapping_max_global_bytes,
            field="tool_mapping_max_global_bytes",
        )
        self._codex_compaction_max_row_bytes = _positive_tool_mapping_limit(
            codex_compaction_max_row_bytes,
            field="codex_compaction_max_row_bytes",
        )
        self._codex_compaction_max_principal_rows = _positive_tool_mapping_limit(
            codex_compaction_max_principal_rows,
            field="codex_compaction_max_principal_rows",
        )
        self._codex_compaction_max_principal_bytes = _positive_tool_mapping_limit(
            codex_compaction_max_principal_bytes,
            field="codex_compaction_max_principal_bytes",
        )
        self._codex_compaction_max_global_rows = _positive_tool_mapping_limit(
            codex_compaction_max_global_rows,
            field="codex_compaction_max_global_rows",
        )
        self._codex_compaction_max_global_bytes = _positive_tool_mapping_limit(
            codex_compaction_max_global_bytes,
            field="codex_compaction_max_global_bytes",
        )
        self._data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._data_dir, 0o700)

        db_fd = os.open(self.db_path, os.O_RDWR | os.O_CREAT, 0o600)
        os.close(db_fd)
        os.chmod(self.db_path, 0o600)

        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._init_tables()
            self.cleanup_expired_codex_compaction_mappings(
                datetime.now(timezone.utc).isoformat()
            )
            self._secure_storage_paths()
            self._reject_legacy_files()
            self._prune()
        except BaseException:
            self._conn.close()
            raise

    def _secure_storage_paths(self) -> None:
        """Enforce owner-only permissions on SQLite database sidecars."""
        for path in (
            self.db_path,
            Path(f"{self.db_path}-wal"),
            Path(f"{self.db_path}-shm"),
        ):
            if path.exists():
                os.chmod(path, 0o600)

    def update_token_values(self, token_values: Iterable[str]) -> None:
        """Update exact token values removed from newly persisted diagnostics."""
        self.commit_token_values(self.prepare_token_values(token_values))

    def prepare_token_values(self, token_values: Iterable[str]) -> SecretRedactor:
        """Construct a replacement redactor without mutating live state."""
        return SecretRedactor(token_values)

    def commit_token_values(self, redactor: SecretRedactor) -> None:
        """Commit a prepared redactor using assignment only."""
        self._redactor = redactor

    def prepare_update(
        self,
        token_values: Iterable[str],
        *,
        success_max: int,
        error_max: int,
    ) -> PreparedPersistenceUpdate:
        """Build a complete redaction and retention update without mutation."""
        return PreparedPersistenceUpdate(
            redactor=SecretRedactor(token_values),
            success_max=validate_retention_cap(success_max, field="success_max"),
            error_max=validate_retention_cap(error_max, field="error_max"),
        )

    def commit_update(
        self,
        prepared: PreparedPersistenceUpdate,
    ) -> PersistenceUpdateRollback:
        """Atomically apply retention policy and immediately prune excess rows."""
        old_redactor = self._redactor
        old_success_max = self._success_max
        old_error_max = self._error_max
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            rollback = PersistenceUpdateRollback(
                redactor=old_redactor,
                success_max=old_success_max,
                error_max=old_error_max,
                pruned_rows=self._rows_beyond_retention(
                    prepared.success_max,
                    prepared.error_max,
                ),
            )
            self._redactor = prepared.redactor
            self._success_max = prepared.success_max
            self._error_max = prepared.error_max
            self._prune(commit=False)
            self._commit_retention_transaction()
        except BaseException:
            self._conn.rollback()
            self._redactor = old_redactor
            self._success_max = old_success_max
            self._error_max = old_error_max
            raise
        return rollback

    def rollback_update(self, rollback: PersistenceUpdateRollback) -> None:
        """Compensate one committed policy update, including pruned log rows."""
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            if rollback.pruned_rows:
                placeholders = ", ".join("?" for _ in self._LOG_COLUMNS)
                columns = ", ".join(self._LOG_COLUMNS)
                self._conn.executemany(
                    f"INSERT OR REPLACE INTO request_log ({columns}) "
                    f"VALUES ({placeholders})",
                    rollback.pruned_rows,
                )
            self._commit_retention_transaction()
        except BaseException:
            self._conn.rollback()
            raise
        self._redactor = rollback.redactor
        self._success_max = rollback.success_max
        self._error_max = rollback.error_max

    def redact_sensitive(self, value: Any) -> Any:
        """Return a redacted copy suitable for persistence."""
        return self._redactor.redact(value)

    def redact_protocol_fields(self, value: Any) -> Any:
        """Redact only explicitly named auth/token fields for model responses."""
        return self._redactor.redact_protocol_fields(value)

    def redact_protocol_text(self, value: str | None) -> str | None:
        """Redact explicit auth/token assignments in model response error text."""
        return self._redactor.redact_protocol_text(value)

    def redact_protocol_diagnostic(self, value: Any) -> Any:
        """Redact protocol fields and explicit assignments in error-text slots."""
        return self._redactor.redact_protocol_diagnostic(value)

    @property
    def success_max(self) -> int:
        """Cap on retained successful request log entries."""
        return self._success_max

    @property
    def error_max(self) -> int:
        """Cap on retained error request log entries (status_code >= 400)."""
        return self._error_max

    @property
    def db_path(self) -> Path:
        return self._data_dir / _DB_FILENAME

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_tables(self) -> None:
        retired_table = self._conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'soft_interrupt_handoffs'"
        ).fetchone()
        if retired_table is not None:
            retired_rows = self._conn.execute(
                "SELECT COUNT(*) FROM soft_interrupt_handoffs"
            ).fetchone()[0]
            self._conn.execute("DROP TABLE soft_interrupt_handoffs")
            self._conn.commit()
            logger.warning(
                "Deleted %d retired soft-interrupt handoff row(s); "
                "hard-interrupt compatibility no longer retains model output",
                retired_rows,
            )
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS request_log (
                id              TEXT PRIMARY KEY,
                timestamp       TEXT NOT NULL,
                model           TEXT NOT NULL,
                source_provider TEXT NOT NULL,
                target_provider TEXT NOT NULL,
                is_stream       INTEGER NOT NULL,
                status_code     INTEGER NOT NULL,
                duration_ms     REAL NOT NULL,
                error_detail    TEXT,
                api_key_label   TEXT,
                target_provider_name TEXT,
                client_ip       TEXT,
                profile         TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_rl_timestamp
                ON request_log(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_rl_status
                ON request_log(status_code);
            CREATE TABLE IF NOT EXISTS metrics (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dump_bodies (
                hash        TEXT PRIMARY KEY,
                data        BLOB NOT NULL,
                orig_bytes  INTEGER NOT NULL,
                created     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS error_dumps (
                id                  TEXT PRIMARY KEY,
                request_log_id      TEXT,
                timestamp           TEXT NOT NULL,
                model               TEXT,
                source_provider     TEXT,
                target_provider     TEXT,
                provider_name       TEXT,
                status_code         INTEGER,
                error_phase         TEXT,
                body_hash           TEXT,
                response_text       TEXT,
                upstream_url        TEXT,
                converted_body_hash TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ed_timestamp
                ON error_dumps(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_ed_request_log
                ON error_dumps(request_log_id);
            CREATE TABLE IF NOT EXISTS codex_compaction_mappings (
                principal_id      TEXT NOT NULL,
                token_hash        TEXT NOT NULL,
                replacement_text  TEXT NOT NULL,
                replacement_bytes INTEGER NOT NULL,
                source_model      TEXT NOT NULL,
                reason            TEXT NOT NULL,
                prompt_sha256     TEXT NOT NULL,
                created_at        TEXT NOT NULL,
                expires_at        TEXT NOT NULL,
                PRIMARY KEY (principal_id, token_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_ccm_expire_at
                ON codex_compaction_mappings(expires_at);
            CREATE INDEX IF NOT EXISTS idx_ccm_principal
                ON codex_compaction_mappings(principal_id);
            CREATE TABLE IF NOT EXISTS search_provider_state (
                row_id           TEXT PRIMARY KEY,
                identity         TEXT NOT NULL,
                is_current       INTEGER NOT NULL,
                quota_exhausted  INTEGER NOT NULL,
                quota_check_at   REAL
            );
        """)
        from .tool_history_store import ToolHistoryStore

        self._tool_history_store = ToolHistoryStore(
            connection=self._conn,
            lock=self._tool_mapping_lock,
            cipher_loader=lambda create: self._mapping_crypto(create=create),
            max_row_bytes=self._tool_mapping_max_row_bytes,
            max_principal_rows=self._tool_mapping_max_principal_rows,
            max_principal_bytes=self._tool_mapping_max_principal_bytes,
            max_global_rows=self._tool_mapping_max_global_rows,
            max_global_bytes=self._tool_mapping_max_global_bytes,
        )
        from .chat_tool_surface_store import ChatToolSurfaceStore

        self._chat_tool_surface_store = ChatToolSurfaceStore(
            connection=self._conn,
            lock=self._tool_mapping_lock,
            cipher_loader=lambda create: self._mapping_crypto(create=create),
        )
        self._validate_schema()

    def _validate_schema(self) -> None:
        """Reject incompatible databases instead of migrating them in place."""
        for table, expected in _EXPECTED_SCHEMA_COLUMNS.items():
            rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            observed = tuple(
                (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]))
                for row in rows
            )
            if observed != expected:
                raise RuntimeError(
                    f"incompatible gateway.db schema for {table}: column/type/"
                    "constraint shape differs from the supported schema; rebuild "
                    "the data directory because Rosetta-version migration is unsupported"
                )

        for table, expected_indexes in _EXPECTED_SCHEMA_INDEXES.items():
            observed_indexes = {
                str(row[1]): (int(row[2]), str(row[3]), int(row[4]))
                for row in self._conn.execute(f"PRAGMA index_list({table})").fetchall()
            }
            for index_name, expected in expected_indexes.items():
                expected_columns, expected_unique, expected_origin, expected_partial = (
                    expected
                )
                if index_name not in observed_indexes:
                    raise RuntimeError(
                        f"incompatible gateway.db schema for {table}: missing index "
                        f"{index_name!r}; rebuild the data directory because "
                        "Rosetta-version migration is unsupported"
                    )
                observed_attributes = observed_indexes[index_name]
                if observed_attributes != (
                    expected_unique,
                    expected_origin,
                    expected_partial,
                ):
                    raise RuntimeError(
                        f"incompatible gateway.db schema for {table}: index "
                        f"{index_name!r} has unexpected attributes; rebuild the data "
                        "directory because Rosetta-version migration is unsupported"
                    )
                observed_columns = tuple(
                    str(row[2])
                    for row in self._conn.execute(
                        f"PRAGMA index_info({index_name})"
                    ).fetchall()
                )
                if observed_columns != expected_columns:
                    raise RuntimeError(
                        f"incompatible gateway.db schema for {table}: index "
                        f"{index_name!r} has unexpected columns; rebuild the data "
                        "directory because Rosetta-version migration is unsupported"
                    )

    def _reject_legacy_files(self) -> None:
        """Fail closed when pre-SQLite persistence files are still present."""
        legacy_names = [
            _LEGACY_LOG,
            _LEGACY_METRICS,
            *(f"request_log.{i}.jsonl.gz" for i in range(1, 4)),
        ]
        present = [name for name in legacy_names if (self._data_dir / name).exists()]
        if present:
            raise RuntimeError(
                "legacy persistence files are unsupported; rebuild the data "
                f"directory before startup: {present}"
            )

    def _mapping_crypto(self, *, create: bool) -> Any:
        """Return the lazy gateway-only AEAD boundary."""
        if self._mapping_cipher is None:
            from .tool_mapping_crypto import ToolMappingCipher

            self._mapping_cipher = ToolMappingCipher.load(
                self._data_dir,
                create=create,
            )
        return self._mapping_cipher

    # ------------------------------------------------------------------
    # Request log
    # ------------------------------------------------------------------

    _LOG_COLUMNS = [
        "id",
        "timestamp",
        "model",
        "source_provider",
        "target_provider",
        "is_stream",
        "status_code",
        "duration_ms",
        "error_detail",
        "api_key_label",
        "target_provider_name",
        "client_ip",
        "profile",
    ]

    def insert_log_entries(
        self,
        entries: list[dict[str, Any]],
        *,
        response_redaction: Literal["exact", "protocol_fields"] = "exact",
    ) -> None:
        """Insert request log entries, pruning oldest if over capacity."""
        if not entries:
            return
        redacted_entries: list[dict[str, Any]] = []
        for entry in entries:
            redacted = dict(entry)
            for field in (
                "model",
                "source_provider",
                "target_provider",
                "error_detail",
                "api_key_label",
                "target_provider_name",
                "client_ip",
                "profile",
            ):
                if field in redacted:
                    redacted[field] = (
                        self.redact_protocol_diagnostic(redacted[field])
                        if response_redaction == "protocol_fields"
                        and field in {"error_detail", "profile"}
                        else self.redact_sensitive(redacted[field])
                    )
            redacted_entries.append(redacted)
        self._conn.executemany(
            "INSERT OR IGNORE INTO request_log "
            "(id, timestamp, model, source_provider, target_provider, "
            "is_stream, status_code, duration_ms, error_detail, api_key_label, "
            "target_provider_name, client_ip, profile) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    e["id"],
                    e["timestamp"],
                    e["model"],
                    e["source_provider"],
                    e["target_provider"],
                    int(e["is_stream"]),
                    e["status_code"],
                    e["duration_ms"],
                    e.get("error_detail"),
                    e.get("api_key_label"),
                    e.get("target_provider_name"),
                    e.get("client_ip"),
                    json.dumps(e["profile"]) if e.get("profile") else None,
                )
                for e in redacted_entries
            ],
        )
        self._conn.commit()
        self._insert_count += len(entries)
        # Periodic prune amortizes the DELETE cost; opportunistic prune
        # bounds memory when the success cap is small.
        if self._insert_count >= 100:
            self._prune()
            self._insert_count = 0
        elif self.count_success_entries() > self._success_max or (
            self.count_error_entries() > self._error_max
        ):
            self._prune()

    def query_log_entries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        model: str | None = None,
        provider: str | None = None,
        provider_type: str | None = None,
        status: str | None = None,
        api_key_label: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Query request log with optional filters, newest first.

        Args:
            provider: Provider display name (e.g. ``"Gemini"``).
            provider_type: Resolved API type for *provider* (e.g.
                ``"google"``).  Enables matching legacy rows that only
                have ``target_provider`` (the API type) without a
                ``target_provider_name`` backfill.

        Returns:
            A ``(entries, total)`` tuple.
        """
        where_clauses: list[str] = []
        params: list[Any] = []

        if model:
            where_clauses.append("model = ?")
            params.append(model)
        if provider:
            if provider_type and provider_type != provider:
                # Match by name, OR fall back to API type only for legacy
                # rows that have no target_provider_name (avoids cross-
                # contamination when multiple providers share a base type).
                where_clauses.append(
                    "(target_provider_name = ? OR target_provider = ? "
                    "OR (target_provider_name IS NULL AND target_provider = ?))"
                )
                params.extend([provider, provider, provider_type])
            else:
                where_clauses.append(
                    "(target_provider_name = ? OR target_provider = ?)"
                )
                params.extend([provider, provider])
        if status == "ok":
            where_clauses.append("status_code < 400")
        elif status == "error":
            where_clauses.append("status_code >= 400")
        if api_key_label:
            where_clauses.append("api_key_label = ?")
            params.append(api_key_label)

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        count_row = self._conn.execute(
            f"SELECT COUNT(*) FROM request_log {where_sql}", params
        ).fetchone()
        total = count_row[0] if count_row else 0

        rows = self._conn.execute(
            f"SELECT * FROM request_log {where_sql} "
            f"ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

        entries = [self._row_to_dict(row) for row in rows]
        return entries, total

    def get_log_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Return a single log entry by id, or ``None``."""
        row = self._conn.execute(
            "SELECT * FROM request_log WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def get_api_key_labels(self) -> list[str]:
        """Return distinct API key labels seen in request logs."""
        rows = self._conn.execute(
            "SELECT DISTINCT api_key_label FROM request_log "
            "WHERE api_key_label IS NOT NULL AND api_key_label != '' "
            "ORDER BY api_key_label"
        ).fetchall()
        return [row[0] for row in rows]

    def iter_log_rows_for_rebuild(
        self, batch_size: int = 5000
    ) -> Iterator[dict[str, Any]]:
        """Yield lightweight dicts for every log entry (for counter rebuild).

        Only fetches the columns needed by
        :meth:`~MetricsCollector.rebuild_counters`.  Rows are fetched
        in batches of *batch_size* to bound memory usage regardless of
        table size.
        """
        cursor = self._conn.execute(
            "SELECT model, source_provider, target_provider, "
            "target_provider_name, is_stream, status_code "
            "FROM request_log"
        )
        while True:
            batch = cursor.fetchmany(batch_size)
            if not batch:
                break
            for r in batch:
                yield {
                    "model": r[0],
                    "source_provider": r[1],
                    "target_provider": r[2],
                    "target_provider_name": r[3],
                    "is_stream": bool(r[4]),
                    "status_code": r[5],
                }

    def count_log_entries(self) -> int:
        """Return the total number of log entries."""
        row = self._conn.execute("SELECT COUNT(*) FROM request_log").fetchone()
        return row[0] if row else 0

    def count_success_entries(self) -> int:
        """Return the number of successful log entries (status_code < 400)."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM request_log WHERE status_code < 400"
        ).fetchone()
        return row[0] if row else 0

    def count_error_entries(self) -> int:
        """Return the number of error log entries (status_code >= 400)."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM request_log WHERE status_code >= 400"
        ).fetchone()
        return row[0] if row else 0

    def db_file_sizes(self) -> dict[str, int]:
        """Return on-disk byte sizes of the SQLite database files.

        Returns:
            Dict with keys ``db_bytes`` (main file), ``wal_bytes`` (WAL),
            and ``shm_bytes`` (shared memory).  Missing files report 0.
        """
        db = self.db_path
        sizes = {"db_bytes": 0, "wal_bytes": 0, "shm_bytes": 0}
        for key, suffix in (
            ("db_bytes", ""),
            ("wal_bytes", "-wal"),
            ("shm_bytes", "-shm"),
        ):
            p = db.with_name(db.name + suffix)
            try:
                sizes[key] = p.stat().st_size
            except OSError:
                sizes[key] = 0
        return sizes

    def clear_log(self) -> None:
        """Delete all request log entries."""
        self._conn.execute("DELETE FROM request_log")
        self._conn.commit()

    # ------------------------------------------------------------------
    # Tool-history object translations
    # ------------------------------------------------------------------

    def lookup_tool_history_translation_templates(
        self,
        *,
        principal_id: str,
        objects: list[tuple[Any, dict[str, Any]]],
        now: str,
    ) -> list[dict[str, Any] | None]:
        """Return ordered ID-independent target templates for exact hits."""
        assert self._tool_history_store is not None
        return self._tool_history_store.lookup_templates(
            principal_id=principal_id,
            objects=objects,
            now=now,
        )

    def lookup_tool_history_translations(
        self,
        *,
        principal_id: str,
        objects: list[tuple[Any, dict[str, Any]]],
        now: str,
    ) -> list[dict[str, Any] | None]:
        """Return ordered hits rebuilt with each current request protocol ID."""
        from ..gateway.tool_history_translation import (
            ToolHistoryObjectKind,
            inject_tool_history_object_id,
            tool_history_object_template,
        )

        templates: list[tuple[ToolHistoryObjectKind, dict[str, Any]]] = []
        protocol_ids: list[str] = []
        for kind_value, source_object in objects:
            kind = ToolHistoryObjectKind(kind_value)
            id_field = "id" if kind is ToolHistoryObjectKind.CALL else "tool_call_id"
            protocol_id = source_object.get(id_field)
            if not isinstance(protocol_id, str) or not protocol_id:
                raise ValueError(f"tool-history {kind.value} object needs {id_field}")
            templates.append((kind, tool_history_object_template(kind, source_object)))
            protocol_ids.append(protocol_id)
        hits = self.lookup_tool_history_translation_templates(
            principal_id=principal_id,
            objects=templates,
            now=now,
        )
        return [
            None
            if target is None
            else inject_tool_history_object_id(kind, target, protocol_id)
            for (kind, _source), protocol_id, target in zip(
                templates,
                protocol_ids,
                hits,
                strict=True,
            )
        ]

    def upsert_tool_history_translation_templates(
        self,
        *,
        principal_id: str,
        object_kind: Any,
        source_template: dict[str, Any],
        target_template: dict[str, Any],
        expire_at: str,
        timestamp: str,
    ) -> bool:
        """Persist one exact ID-independent source/target translation."""
        assert self._tool_history_store is not None
        return self._tool_history_store.upsert_template(
            principal_id=principal_id,
            object_kind=object_kind,
            source_template=source_template,
            target_template=target_template,
            expire_at=expire_at,
            timestamp=timestamp,
        )

    def upsert_tool_history_translation(
        self,
        *,
        principal_id: str,
        object_kind: Any,
        source_object: dict[str, Any],
        target_object: dict[str, Any],
        expire_at: str,
        timestamp: str,
    ) -> bool:
        """Normalize protocol IDs and persist one object translation."""
        from ..gateway.tool_history_translation import (
            ToolHistoryObjectKind,
            tool_history_object_template,
        )

        kind = ToolHistoryObjectKind(object_kind)
        return self.upsert_tool_history_translation_templates(
            principal_id=principal_id,
            object_kind=kind,
            source_template=tool_history_object_template(kind, source_object),
            target_template=tool_history_object_template(kind, target_object),
            expire_at=expire_at,
            timestamp=timestamp,
        )

    def cleanup_expired_tool_history_translations(self, now: str) -> int:
        """Delete expired object translations and return the deleted count."""
        assert self._tool_history_store is not None
        return self._tool_history_store.cleanup_expired(now)

    def count_tool_history_translations(self) -> int:
        """Return the total number of persistent object translations."""
        assert self._tool_history_store is not None
        return self._tool_history_store.count()

    def load_or_create_chat_tool_surface(
        self,
        *,
        principal_id: str,
        scope: dict[str, Any],
        initial_payload: dict[str, Any],
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Return the winning encrypted window tool-surface snapshot."""
        assert self._chat_tool_surface_store is not None
        return self._chat_tool_surface_store.load_or_create(
            principal_id=principal_id,
            scope=scope,
            initial_payload=initial_payload,
            now=now,
        )

    def replace_chat_tool_surface(
        self,
        *,
        principal_id: str,
        scope: dict[str, Any],
        expected_epoch: int,
        payload: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically replace an encrypted window tool-surface snapshot."""
        assert self._chat_tool_surface_store is not None
        return self._chat_tool_surface_store.replace(
            principal_id=principal_id,
            scope=scope,
            expected_epoch=expected_epoch,
            payload=payload,
            now=now,
        )

    def cleanup_expired_chat_tool_surfaces(self, now: datetime | None = None) -> int:
        """Delete expired window tool-surface snapshots."""
        assert self._chat_tool_surface_store is not None
        return self._chat_tool_surface_store.cleanup_expired(now)

    def count_chat_tool_surfaces(self) -> int:
        """Return the number of persistent window tool-surface snapshots."""
        assert self._chat_tool_surface_store is not None
        return self._chat_tool_surface_store.count()

    # ------------------------------------------------------------------
    # Codex remote-compaction mappings
    # ------------------------------------------------------------------

    def store_codex_compaction_mapping(
        self,
        *,
        principal_id: str,
        token_hash: str,
        replacement_text: str,
        source_model: str,
        reason: str,
        prompt_sha256: str,
        created_at: str,
        expires_at: str,
    ) -> None:
        """Persist one plaintext Rosetta remote-compaction replacement."""
        replacement_bytes = len(replacement_text.encode("utf-8"))
        with self._compaction_mapping_lock:
            if replacement_bytes > self._codex_compaction_max_row_bytes:
                raise CompactionMappingCapacityError(
                    "compaction replacement exceeds row byte limit "
                    f"({self._codex_compaction_max_row_bytes})"
                )
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "DELETE FROM codex_compaction_mappings WHERE expires_at <= ?",
                    (datetime.now(timezone.utc).isoformat(),),
                )
                existing = self._conn.execute(
                    "SELECT replacement_bytes FROM codex_compaction_mappings "
                    "WHERE principal_id = ? AND token_hash = ?",
                    (principal_id, token_hash),
                ).fetchone()
                row_delta = 0 if existing is not None else 1
                byte_delta = replacement_bytes - (int(existing[0]) if existing else 0)
                principal_rows, principal_bytes = self._compaction_mapping_usage_locked(
                    principal_id
                )
                global_rows, global_bytes = self._compaction_mapping_usage_locked()
                limits = (
                    (
                        "principal row count",
                        principal_rows + row_delta,
                        self._codex_compaction_max_principal_rows,
                    ),
                    (
                        "principal bytes",
                        principal_bytes + byte_delta,
                        self._codex_compaction_max_principal_bytes,
                    ),
                    (
                        "global row count",
                        global_rows + row_delta,
                        self._codex_compaction_max_global_rows,
                    ),
                    (
                        "global bytes",
                        global_bytes + byte_delta,
                        self._codex_compaction_max_global_bytes,
                    ),
                )
                for label, observed, limit in limits:
                    if observed > limit:
                        raise CompactionMappingCapacityError(
                            f"compaction mapping {label} exceeds limit ({limit})"
                        )
                self._conn.execute(
                    "INSERT INTO codex_compaction_mappings "
                    "(principal_id, token_hash, replacement_text, replacement_bytes, "
                    "source_model, reason, prompt_sha256, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(principal_id, token_hash) DO UPDATE SET "
                    "replacement_text = excluded.replacement_text, "
                    "replacement_bytes = excluded.replacement_bytes, "
                    "source_model = excluded.source_model, reason = excluded.reason, "
                    "prompt_sha256 = excluded.prompt_sha256, created_at = excluded.created_at, "
                    "expires_at = excluded.expires_at",
                    (
                        principal_id,
                        token_hash,
                        replacement_text,
                        replacement_bytes,
                        source_model,
                        reason,
                        prompt_sha256,
                        created_at,
                        expires_at,
                    ),
                )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def _compaction_mapping_usage_locked(
        self, principal_id: str | None = None
    ) -> tuple[int, int]:
        """Return row count and replacement bytes under the compaction lock."""
        if principal_id is None:
            row = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(replacement_bytes), 0) "
                "FROM codex_compaction_mappings"
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(replacement_bytes), 0) "
                "FROM codex_compaction_mappings WHERE principal_id = ?",
                (principal_id,),
            ).fetchone()
        return (int(row[0]), int(row[1])) if row else (0, 0)

    def get_codex_compaction_mapping(
        self,
        *,
        principal_id: str,
        token_hash: str,
        now: str,
        renewed_expires_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Return one live replacement owned by *principal_id*, if any.

        ``renewed_expires_at`` supports the gateway's rolling seven-day
        retention policy without making callers that only inspect rows mutate
        them implicitly.
        """
        with self._compaction_mapping_lock:
            self._conn.execute(
                "DELETE FROM codex_compaction_mappings WHERE expires_at <= ?", (now,)
            )
            row = self._conn.execute(
                "SELECT replacement_text, replacement_bytes, source_model, reason, "
                "prompt_sha256, created_at, expires_at "
                "FROM codex_compaction_mappings "
                "WHERE principal_id = ? AND token_hash = ?",
                (principal_id, token_hash),
            ).fetchone()
            if row is not None and renewed_expires_at is not None:
                self._conn.execute(
                    "UPDATE codex_compaction_mappings SET expires_at = ? "
                    "WHERE principal_id = ? AND token_hash = ?",
                    (renewed_expires_at, principal_id, token_hash),
                )
            self._conn.commit()
        if row is None:
            return None
        return {
            "replacement_text": row[0],
            "replacement_bytes": row[1],
            "source_model": row[2],
            "reason": row[3],
            "prompt_sha256": row[4],
            "created_at": row[5],
            "expires_at": renewed_expires_at or row[6],
        }

    def cleanup_expired_codex_compaction_mappings(self, now: str) -> int:
        """Delete expired Rosetta remote-compaction mappings."""
        with self._compaction_mapping_lock:
            cursor = self._conn.execute(
                "DELETE FROM codex_compaction_mappings WHERE expires_at <= ?", (now,)
            )
            self._conn.commit()
            return cursor.rowcount

    def count_codex_compaction_mappings(self) -> int:
        """Return the number of retained Rosetta remote-compaction mappings."""
        with self._compaction_mapping_lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM codex_compaction_mappings"
            ).fetchone()
            return row[0] if row else 0

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def save_metrics(self, data: dict[str, Any]) -> None:
        """Persist metrics counters."""
        redacted = self.redact_sensitive(data)
        self._conn.execute(
            "INSERT OR REPLACE INTO metrics (key, value) VALUES (?, ?)",
            ("counters", json.dumps(redacted, ensure_ascii=False)),
        )
        self._conn.commit()

    def load_metrics(self) -> dict[str, Any] | None:
        """Load metrics counters, or ``None`` if not yet saved."""
        row = self._conn.execute(
            "SELECT value FROM metrics WHERE key = ?", ("counters",)
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Failed to load metrics: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Search provider routing state
    # ------------------------------------------------------------------

    def load_current_search_provider(self) -> tuple[str, str] | None:
        """Return the persisted current row and its effective identity."""
        with self._search_provider_state_lock:
            row = self._conn.execute(
                "SELECT row_id, identity FROM search_provider_state "
                "WHERE is_current = 1 LIMIT 1"
            ).fetchone()
        return (str(row[0]), str(row[1])) if row is not None else None

    def set_current_search_provider(self, row_id: str, identity: str) -> None:
        """Persist one current row while invalidating stale row identities."""
        with self._search_provider_state_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "UPDATE search_provider_state SET is_current = 0 "
                    "WHERE is_current = 1"
                )
                self._conn.execute(
                    "INSERT INTO search_provider_state "
                    "(row_id, identity, is_current, quota_exhausted, quota_check_at) "
                    "VALUES (?, ?, 1, 0, NULL) "
                    "ON CONFLICT(row_id) DO UPDATE SET "
                    "identity = excluded.identity, is_current = 1, "
                    "quota_exhausted = CASE WHEN identity = excluded.identity "
                    "THEN quota_exhausted ELSE 0 END, "
                    "quota_check_at = CASE WHEN identity = excluded.identity "
                    "THEN quota_check_at ELSE NULL END",
                    (row_id, identity),
                )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def load_search_provider_quota_check(
        self, row_id: str, identity: str
    ) -> float | None:
        """Return the next check time for an exhausted matching row identity."""
        with self._search_provider_state_lock:
            row = self._conn.execute(
                "SELECT quota_check_at FROM search_provider_state "
                "WHERE row_id = ? AND identity = ? AND quota_exhausted = 1",
                (row_id, identity),
            ).fetchone()
        return float(row[0]) if row is not None and row[0] is not None else None

    def set_search_provider_quota_exhausted(
        self, row_id: str, identity: str, next_check_at: float
    ) -> None:
        """Persist a zero-credit exclusion and its next on-demand check time."""
        with self._search_provider_state_lock:
            self._conn.execute(
                "INSERT INTO search_provider_state "
                "(row_id, identity, is_current, quota_exhausted, quota_check_at) "
                "VALUES (?, ?, 0, 1, ?) "
                "ON CONFLICT(row_id) DO UPDATE SET identity = excluded.identity, "
                "quota_exhausted = 1, quota_check_at = excluded.quota_check_at, "
                "is_current = CASE WHEN identity = excluded.identity "
                "THEN is_current ELSE 0 END",
                (row_id, identity, next_check_at),
            )
            self._conn.commit()

    def clear_search_provider_quota(self, row_id: str, identity: str) -> None:
        """Clear quota exclusion for one matching row identity."""
        with self._search_provider_state_lock:
            self._conn.execute(
                "UPDATE search_provider_state SET quota_exhausted = 0, "
                "quota_check_at = NULL WHERE row_id = ? AND identity = ?",
                (row_id, identity),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Error dumps
    # ------------------------------------------------------------------

    # Error diagnostic retention is independent of request_log error_max.
    DEFAULT_DUMP_MAX = 10000

    def insert_dump_body(self, body_hash: str, data: bytes, orig_bytes: int) -> None:
        """Insert a compressed body blob, deduplicating by hash.

        If the hash already exists the row is silently skipped.
        """
        from datetime import datetime, timezone

        self._conn.execute(
            "INSERT OR IGNORE INTO dump_bodies (hash, data, orig_bytes, created) "
            "VALUES (?, ?, ?, ?)",
            (body_hash, data, orig_bytes, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def insert_error_dump(
        self,
        *,
        dump_id: str,
        request_log_id: str | None,
        timestamp: str,
        model: str | None,
        source_provider: str | None,
        target_provider: str | None,
        provider_name: str | None,
        status_code: int | None,
        error_phase: str | None,
        body_hash: str | None,
        response_text: str | None,
        upstream_url: str | None,
        converted_body_hash: str | None = None,
        response_redaction: str = "exact",
    ) -> None:
        """Insert an error dump record and prune if over capacity."""
        metadata = self.redact_sensitive(
            {
                "model": model,
                "source_provider": source_provider,
                "target_provider": target_provider,
                "provider_name": provider_name,
                "error_phase": error_phase,
                "upstream_url": upstream_url,
            }
        )
        stored_response_text = (
            response_text
            if response_redaction == "protocol_fields"
            else self.redact_sensitive(response_text)
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO error_dumps "
            "(id, request_log_id, timestamp, model, source_provider, "
            "target_provider, provider_name, status_code, error_phase, "
            "body_hash, response_text, upstream_url, converted_body_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                dump_id,
                request_log_id,
                timestamp,
                metadata["model"],
                metadata["source_provider"],
                metadata["target_provider"],
                metadata["provider_name"],
                status_code,
                metadata["error_phase"],
                body_hash,
                stored_response_text,
                metadata["upstream_url"],
                converted_body_hash,
            ),
        )
        self._conn.commit()
        self._prune_error_dumps()

    def query_error_dumps(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        model: str | None = None,
        error_phase: str | None = None,
        provider: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Query error dumps with optional filters, newest first.

        Returns:
            A ``(entries, total)`` tuple.
        """
        where_clauses: list[str] = []
        params: list[Any] = []

        if model:
            where_clauses.append("model = ?")
            params.append(model)
        if error_phase:
            where_clauses.append("error_phase = ?")
            params.append(error_phase)
        if provider:
            where_clauses.append("(provider_name = ? OR target_provider = ?)")
            params.extend([provider, provider])

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        count_row = self._conn.execute(
            f"SELECT COUNT(*) FROM error_dumps {where_sql}", params
        ).fetchone()
        total = count_row[0] if count_row else 0

        cols = (
            "id, request_log_id, timestamp, model, source_provider, "
            "target_provider, provider_name, status_code, error_phase, "
            "body_hash, response_text, upstream_url, converted_body_hash"
        )
        rows = self._conn.execute(
            f"SELECT {cols} FROM error_dumps {where_sql} "
            f"ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

        col_names = [
            "id",
            "request_log_id",
            "timestamp",
            "model",
            "source_provider",
            "target_provider",
            "provider_name",
            "status_code",
            "error_phase",
            "body_hash",
            "response_text",
            "upstream_url",
            "converted_body_hash",
        ]
        entries = [
            {k: v for k, v in zip(col_names, row) if v is not None} for row in rows
        ]
        return entries, total

    def get_error_dump(self, dump_id: str) -> dict[str, Any] | None:
        """Return a single error dump by ID, or ``None``."""
        cols = (
            "id, request_log_id, timestamp, model, source_provider, "
            "target_provider, provider_name, status_code, error_phase, "
            "body_hash, response_text, upstream_url, converted_body_hash"
        )
        row = self._conn.execute(
            f"SELECT {cols} FROM error_dumps WHERE id = ?", (dump_id,)
        ).fetchone()
        if row is None:
            return None
        col_names = [
            "id",
            "request_log_id",
            "timestamp",
            "model",
            "source_provider",
            "target_provider",
            "provider_name",
            "status_code",
            "error_phase",
            "body_hash",
            "response_text",
            "upstream_url",
            "converted_body_hash",
        ]
        return {k: v for k, v in zip(col_names, row) if v is not None}

    def get_dump_body(self, body_hash: str) -> bytes | None:
        """Return the compressed body blob for a hash, or ``None``."""
        row = self._conn.execute(
            "SELECT data FROM dump_bodies WHERE hash = ?", (body_hash,)
        ).fetchone()
        return row[0] if row else None

    def count_error_dumps(self) -> int:
        """Return the total number of error dump entries."""
        row = self._conn.execute("SELECT COUNT(*) FROM error_dumps").fetchone()
        return row[0] if row else 0

    def clear_error_dumps(self) -> None:
        """Delete all error dumps and orphaned bodies."""
        self._conn.execute("DELETE FROM error_dumps")
        self._conn.execute(
            "DELETE FROM dump_bodies WHERE hash NOT IN "
            "(SELECT body_hash FROM error_dumps WHERE body_hash IS NOT NULL "
            " UNION SELECT converted_body_hash FROM error_dumps "
            " WHERE converted_body_hash IS NOT NULL)"
        )
        self._conn.commit()

    def _prune_error_dumps(self) -> None:
        """Keep the newest error dumps up to the established count limit."""
        self._conn.execute(
            "DELETE FROM error_dumps WHERE id NOT IN ("
            "    SELECT id FROM error_dumps "
            "    ORDER BY timestamp DESC LIMIT ?"
            ")",
            (self.DEFAULT_DUMP_MAX,),
        )
        self._delete_orphaned_dump_bodies()
        self._conn.commit()

    def _delete_orphaned_dump_bodies(self) -> None:
        """Delete body blobs no longer referenced by an error dump."""
        self._conn.execute(
            "DELETE FROM dump_bodies WHERE hash NOT IN ("
            "    SELECT body_hash FROM error_dumps "
            "    WHERE body_hash IS NOT NULL"
            "    UNION "
            "    SELECT converted_body_hash FROM error_dumps "
            "    WHERE converted_body_hash IS NOT NULL"
            ")"
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Commit and close the database connection."""
        try:
            self._conn.commit()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rows_beyond_retention(
        self,
        success_max: int,
        error_max: int,
    ) -> tuple[tuple[Any, ...], ...]:
        columns = ", ".join(self._LOG_COLUMNS)
        rows: list[tuple[Any, ...]] = []
        for condition, limit in (
            ("status_code < 400", success_max),
            ("status_code >= 400", error_max),
        ):
            rows.extend(
                self._conn.execute(
                    f"SELECT {columns} FROM request_log "
                    f"WHERE {condition} AND id NOT IN ("
                    f"SELECT id FROM request_log WHERE {condition} "
                    "ORDER BY timestamp DESC LIMIT ?)",
                    (limit,),
                ).fetchall()
            )
        return tuple(rows)

    def _commit_retention_transaction(self) -> None:
        """Commit a retention transaction (split out for failure injection)."""
        self._conn.commit()

    def _prune(self, *, commit: bool = True) -> None:
        """Remove oldest entries beyond the per-class retention limits.

        Success and error rows are pruned independently so that rare
        error rows are not evicted by a flood of successful traffic.
        """
        try:
            self._conn.execute(
                "DELETE FROM request_log "
                "WHERE status_code < 400 AND id NOT IN ("
                "    SELECT id FROM request_log WHERE status_code < 400 "
                "    ORDER BY timestamp DESC LIMIT ?"
                ")",
                (self._success_max,),
            )
            self._conn.execute(
                "DELETE FROM request_log "
                "WHERE status_code >= 400 AND id NOT IN ("
                "    SELECT id FROM request_log WHERE status_code >= 400 "
                "    ORDER BY timestamp DESC LIMIT ?"
                ")",
                (self._error_max,),
            )
            if commit:
                self._conn.commit()
        except BaseException:
            if commit:
                self._conn.rollback()
            raise

    def update_entry_profile(
        self,
        entry_id: str,
        profile_update: dict[str, Any],
        *,
        response_redaction: Literal["exact", "protocol_fields"] = "exact",
    ) -> None:
        """Merge additional profile data into an existing log entry.

        Reads the current profile JSON, merges *profile_update* on top,
        and writes it back.  Used by the streaming path to write back
        stream metrics after the stream completes.

        Args:
            entry_id: The log entry ID to update.
            profile_update: Profile keys to merge.
        """
        row = self._conn.execute(
            "SELECT profile FROM request_log WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            return
        existing: dict[str, Any] = {}
        if row[0]:
            try:
                existing = json.loads(row[0])
            except json.JSONDecodeError, TypeError:
                pass
        redact = (
            self.redact_protocol_diagnostic
            if response_redaction == "protocol_fields"
            else self.redact_sensitive
        )
        existing = redact(existing)
        redacted_update = redact(profile_update)
        existing.update(redacted_update)
        self._conn.execute(
            "UPDATE request_log SET profile = ? WHERE id = ?",
            (json.dumps(existing, ensure_ascii=False), entry_id),
        )
        self._conn.commit()

    def update_entry_result(
        self,
        entry_id: str,
        *,
        status_code: int,
        duration_ms: float,
        error_detail: str | None,
        profile_update: dict[str, Any] | None = None,
        response_redaction: Literal["exact", "protocol_fields"] = "exact",
    ) -> None:
        """Finalize status, duration, error, and profile for a streaming entry."""
        row = self._conn.execute(
            "SELECT profile FROM request_log WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            return

        profile: dict[str, Any] = {}
        if row[0]:
            try:
                profile = json.loads(row[0])
            except json.JSONDecodeError, TypeError:
                pass
        redact = (
            self.redact_protocol_diagnostic
            if response_redaction == "protocol_fields"
            else self.redact_sensitive
        )
        if profile_update:
            profile.update(redact(profile_update))
        profile = redact(profile)
        redacted_error = redact(error_detail)
        self._conn.execute(
            "UPDATE request_log SET status_code = ?, duration_ms = ?, "
            "error_detail = ?, profile = ? WHERE id = ?",
            (
                status_code,
                round(duration_ms, 2),
                redacted_error,
                json.dumps(profile, ensure_ascii=False) if profile else None,
                entry_id,
            ),
        )
        self._conn.commit()

    @classmethod
    def _row_to_dict(cls, row: tuple[Any, ...]) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for col, val in zip(cls._LOG_COLUMNS, row):
            if col == "is_stream":
                d[col] = bool(val)
            elif col == "profile":
                if val is not None:
                    try:
                        d[col] = json.loads(val)
                    except json.JSONDecodeError, TypeError:
                        d[col] = None
                # omit if None (match old behavior for optional fields)
            elif col in ("error_detail", "api_key_label", "client_ip") and val is None:
                continue  # omit None optional fields (match old behavior)
            else:
                d[col] = val
        return d
