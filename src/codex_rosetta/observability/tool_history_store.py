"""Encrypted principal-scoped persistence for single-object tool translations."""

from __future__ import annotations

import hmac
import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from ..gateway.tool_history_translation import (
    ToolHistoryObjectKind,
    canonical_tool_history_template,
    tool_history_object_template,
)
from .tool_mapping_crypto import (
    PAYLOAD_VERSION as LEGACY_PAYLOAD_VERSION,
    TOOL_HISTORY_PAYLOAD_VERSION,
    ToolMappingCipher,
    ToolMappingIntegrityError,
    mapping_aad,
    tool_history_translation_aad,
)

logger = logging.getLogger("codex-rosetta.observability")

TABLE_NAME = "tool_history_object_translations"
LEGACY_TABLE_NAME = "tool_call_mappings"

EXPECTED_COLUMNS = (
    ("principal_id", "TEXT", 1, 1),
    ("object_kind", "TEXT", 1, 2),
    ("lookup_token", "BLOB", 1, 3),
    ("payload_version", "INTEGER", 1, 0),
    ("key_id", "TEXT", 1, 0),
    ("nonce", "BLOB", 1, 0),
    ("encrypted_payload", "BLOB", 1, 0),
    ("translation_bytes", "INTEGER", 1, 0),
    ("expire_at", "TEXT", 1, 0),
    ("created_at", "TEXT", 1, 0),
    ("updated_at", "TEXT", 1, 0),
)

EXPECTED_INDEXES = {
    "idx_thot_expire_at": ("expire_at",),
    "idx_thot_principal": ("principal_id",),
}

_SQL_BYTES = """
    16
    + length(CAST(principal_id AS BLOB))
    + length(CAST(object_kind AS BLOB))
    + length(lookup_token)
    + length(CAST(key_id AS BLOB))
    + length(nonce)
    + length(encrypted_payload)
    + length(CAST(expire_at AS BLOB))
    + length(CAST(created_at AS BLOB))
    + length(CAST(updated_at AS BLOB))
""".strip()


class ToolHistoryCapacityError(RuntimeError):
    """Encrypted tool-history translations exceeded a configured hard budget."""


class ToolHistoryConflictError(RuntimeError):
    """One exact source object was observed with incompatible target objects."""


class ToolHistoryStore:
    """Own schema, migration, AEAD, lookup, TTL, and quotas for tool history."""

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        lock: threading.RLock,
        cipher_loader: Callable[[bool], ToolMappingCipher],
        max_row_bytes: int,
        max_principal_rows: int,
        max_principal_bytes: int,
        max_global_rows: int,
        max_global_bytes: int,
    ) -> None:
        self._conn = connection
        self._lock = lock
        self._cipher_loader = cipher_loader
        self._max_row_bytes = max_row_bytes
        self._max_principal_rows = max_principal_rows
        self._max_principal_bytes = max_principal_bytes
        self._max_global_rows = max_global_rows
        self._max_global_bytes = max_global_bytes
        self._initialize()

    def _initialize(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            legacy_exists = self._table_exists(LEGACY_TABLE_NAME)
            current_exists = self._table_exists(TABLE_NAME)
            if legacy_exists:
                legacy_columns = {
                    str(row[1])
                    for row in self._conn.execute(
                        f"PRAGMA table_info({LEGACY_TABLE_NAME})"
                    )
                }
                encrypted = {
                    "principal_id",
                    "provider_name",
                    "model",
                    "session_id",
                    "tool_call_id",
                    "payload_version",
                    "key_id",
                    "nonce",
                    "encrypted_payload",
                    "expire_at",
                    "created_at",
                    "updated_at",
                }.issubset(legacy_columns)
                if encrypted:
                    self._migrate_encrypted_v1(now=now, current_exists=current_exists)
                else:
                    self._discard_plaintext_legacy(current_exists=current_exists)
            elif not current_exists:
                self._create_schema()
                self._conn.commit()
            self._validate_schema()
            self.cleanup_expired(now)
            self._validate_capacity_locked()
            self._validate_encrypted_rows_locked()

    def lookup_templates(
        self,
        *,
        principal_id: str,
        objects: list[tuple[ToolHistoryObjectKind | str, dict[str, Any]]],
        now: str,
    ) -> list[dict[str, Any] | None]:
        """Return ordered target templates for exact source-template hits."""
        if not objects:
            return []
        normalized = [
            (ToolHistoryObjectKind(kind), source_template)
            for kind, source_template in objects
        ]
        with self._lock:
            if (
                self._cleanup_and_count_principal(principal_id=principal_id, now=now)
                == 0
            ):
                return [None] * len(objects)

            cipher = self._cipher_loader(False)
            keys = self._lookup_coordinates(
                principal_id=principal_id,
                normalized=normalized,
                cipher=cipher,
            )
            rows_by_key = self._load_candidate_rows(
                principal_id=principal_id,
                keys=keys,
            )
            return self._authenticate_lookup_results(
                principal_id=principal_id,
                normalized=normalized,
                keys=keys,
                rows_by_key=rows_by_key,
                cipher=cipher,
            )

    def _cleanup_and_count_principal(self, *, principal_id: str, now: str) -> int:
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                f"DELETE FROM {TABLE_NAME} WHERE expire_at <= ?",
                (now,),
            )
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE principal_id = ?",
                (principal_id,),
            ).fetchone()
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        return int(row[0]) if row else 0

    @staticmethod
    def _lookup_coordinates(
        *,
        principal_id: str,
        normalized: list[tuple[ToolHistoryObjectKind, dict[str, Any]]],
        cipher: ToolMappingCipher,
    ) -> list[tuple[str, bytes, bytes]]:
        keys: list[tuple[str, bytes, bytes]] = []
        for kind, source_template in normalized:
            canonical_source = canonical_tool_history_template(source_template)
            token = cipher.tool_history_lookup_token(
                principal_id=principal_id,
                object_kind=kind.value,
                canonical_source=canonical_source,
            )
            keys.append((kind.value, token, canonical_source))
        return keys

    def _load_candidate_rows(
        self,
        *,
        principal_id: str,
        keys: list[tuple[str, bytes, bytes]],
    ) -> dict[tuple[str, bytes], tuple[Any, ...]]:
        rows_by_key: dict[tuple[str, bytes], tuple[Any, ...]] = {}
        for kind in ToolHistoryObjectKind:
            tokens = list(
                dict.fromkeys(
                    token for item_kind, token, _source in keys if item_kind == kind
                )
            )
            for start in range(0, len(tokens), 400):
                chunk = tokens[start : start + 400]
                if not chunk:
                    continue
                placeholders = ",".join("?" for _ in chunk)
                rows = self._conn.execute(
                    f"SELECT principal_id, object_kind, lookup_token, "
                    "payload_version, key_id, nonce, encrypted_payload, "
                    "expire_at, created_at, updated_at, translation_bytes "
                    f"FROM {TABLE_NAME} WHERE principal_id = ? "
                    f"AND object_kind = ? AND lookup_token IN ({placeholders})",
                    (principal_id, kind.value, *chunk),
                ).fetchall()
                for row in rows:
                    rows_by_key[(str(row[1]), bytes(row[2]))] = row
        return rows_by_key

    def _authenticate_lookup_results(
        self,
        *,
        principal_id: str,
        normalized: list[tuple[ToolHistoryObjectKind, dict[str, Any]]],
        keys: list[tuple[str, bytes, bytes]],
        rows_by_key: dict[tuple[str, bytes], tuple[Any, ...]],
        cipher: ToolMappingCipher,
    ) -> list[dict[str, Any] | None]:
        results: list[dict[str, Any] | None] = []
        for (kind, _source_template), (kind_value, token, canonical_source) in zip(
            normalized,
            keys,
            strict=True,
        ):
            row = rows_by_key.get((kind_value, token))
            if row is None:
                results.append(None)
                continue
            stored_source, target = self._decrypt_row(row, cipher=cipher)
            if canonical_tool_history_template(stored_source) != canonical_source:
                raise ToolMappingIntegrityError(
                    "Tool-history keyed lookup did not match authenticated source"
                )
            expected_token = cipher.tool_history_lookup_token(
                principal_id=principal_id,
                object_kind=kind.value,
                canonical_source=canonical_source,
            )
            if not hmac.compare_digest(expected_token, token):
                raise ToolMappingIntegrityError(
                    "Tool-history keyed lookup token is inconsistent"
                )
            results.append(target)
        return results

    def upsert_template(
        self,
        *,
        principal_id: str,
        object_kind: ToolHistoryObjectKind | str,
        source_template: dict[str, Any],
        target_template: dict[str, Any],
        expire_at: str,
        timestamp: str,
    ) -> bool:
        """Insert one translation, preserving absolute TTL for an existing hit."""
        kind = ToolHistoryObjectKind(object_kind)
        canonical_source = canonical_tool_history_template(source_template)
        cipher = self._cipher_loader(True)
        token = cipher.tool_history_lookup_token(
            principal_id=principal_id,
            object_kind=kind.value,
            canonical_source=canonical_source,
        )
        aad = tool_history_translation_aad(
            principal_id=principal_id,
            object_kind=kind.value,
            lookup_token=token,
        )
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    f"DELETE FROM {TABLE_NAME} WHERE expire_at <= ?",
                    (timestamp,),
                )
                existing = self._conn.execute(
                    f"SELECT principal_id, object_kind, lookup_token, "
                    "payload_version, key_id, nonce, encrypted_payload, "
                    "expire_at, created_at, updated_at, translation_bytes "
                    f"FROM {TABLE_NAME} WHERE principal_id = ? "
                    "AND object_kind = ? AND lookup_token = ?",
                    (principal_id, kind.value, token),
                ).fetchone()
                if existing is not None:
                    stored_source, stored_target = self._decrypt_row(
                        existing,
                        cipher=cipher,
                    )
                    if (
                        canonical_tool_history_template(stored_source)
                        != canonical_source
                    ):
                        raise ToolMappingIntegrityError(
                            "Tool-history keyed lookup collision failed source validation"
                        )
                    if stored_target != target_template:
                        raise ToolHistoryConflictError(
                            "Exact tool-history source has conflicting translations"
                        )
                    self._conn.commit()
                    return False

                nonce, encrypted_payload = cipher.encrypt_tool_history_translation(
                    source_template=source_template,
                    target_template=target_template,
                    aad=aad,
                )
                byte_size = self._row_bytes(
                    principal_id=principal_id,
                    object_kind=kind.value,
                    lookup_token=token,
                    key_id=cipher.key_id,
                    nonce=nonce,
                    encrypted_payload=encrypted_payload,
                    expire_at=expire_at,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                self._validate_projected_insert_locked(
                    principal_id=principal_id,
                    byte_size=byte_size,
                )
                self._conn.execute(
                    f"INSERT INTO {TABLE_NAME} "
                    "(principal_id, object_kind, lookup_token, payload_version, "
                    "key_id, nonce, encrypted_payload, translation_bytes, expire_at, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        principal_id,
                        kind.value,
                        token,
                        TOOL_HISTORY_PAYLOAD_VERSION,
                        cipher.key_id,
                        nonce,
                        encrypted_payload,
                        byte_size,
                        expire_at,
                        timestamp,
                        timestamp,
                    ),
                )
                self._conn.commit()
                return True
            except BaseException:
                self._conn.rollback()
                raise

    def cleanup_expired(self, now: str) -> int:
        """Delete expired translations and return the deleted row count."""
        with self._lock:
            cursor = self._conn.execute(
                f"DELETE FROM {TABLE_NAME} WHERE expire_at <= ?",
                (now,),
            )
            self._conn.commit()
            return cursor.rowcount

    def count(self) -> int:
        """Return the total durable object-translation count."""
        with self._lock:
            row = self._conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()
            return int(row[0]) if row else 0

    def _migrate_encrypted_v1(self, *, now: str, current_exists: bool) -> None:
        if (
            current_exists
            and self._conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
        ):
            raise RuntimeError(
                "Both legacy and current tool-history tables contain rows; "
                "refusing ambiguous migration"
            )
        cipher = self._cipher_loader(False)
        migrated = 0
        merged = 0
        conflicts = 0
        expired = 0
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            if not current_exists:
                self._create_schema(commit=False)
            self._conn.execute(
                "CREATE TEMP TABLE IF NOT EXISTS tool_history_migration_conflicts "
                "(principal_id TEXT NOT NULL, object_kind TEXT NOT NULL, "
                "lookup_token BLOB NOT NULL, "
                "PRIMARY KEY (principal_id, object_kind, lookup_token))"
            )
            rows = self._conn.execute(
                f"SELECT principal_id, provider_name, model, session_id, tool_call_id, "
                "payload_version, key_id, nonce, encrypted_payload, expire_at, "
                f"created_at, updated_at FROM {LEGACY_TABLE_NAME} ORDER BY updated_at"
            )
            for row in rows:
                if str(row[9]) <= now:
                    expired += 1
                    continue
                if int(row[5]) != LEGACY_PAYLOAD_VERSION:
                    raise ToolMappingIntegrityError(
                        f"Unsupported legacy tool-mapping format version {row[5]!r}"
                    )
                localized_call, native_call = cipher.decrypt(
                    key_id=str(row[6]),
                    nonce=bytes(row[7]),
                    encrypted_payload=bytes(row[8]),
                    aad=mapping_aad(
                        principal_id=str(row[0]),
                        provider_name=str(row[1]),
                        model=str(row[2]),
                        session_id=str(row[3]),
                        tool_call_id=str(row[4]),
                    ),
                )
                principal_id = str(row[0])
                kind = ToolHistoryObjectKind.CALL
                source = tool_history_object_template(kind, native_call)
                source.pop("_codex_rosetta_native_type", None)
                target = tool_history_object_template(kind, localized_call)
                canonical_source = canonical_tool_history_template(source)
                token = cipher.tool_history_lookup_token(
                    principal_id=principal_id,
                    object_kind=kind.value,
                    canonical_source=canonical_source,
                )
                if self._conn.execute(
                    "SELECT 1 FROM tool_history_migration_conflicts "
                    "WHERE principal_id = ? AND object_kind = ? AND lookup_token = ?",
                    (principal_id, kind.value, token),
                ).fetchone():
                    continue
                existing = self._conn.execute(
                    f"SELECT principal_id, object_kind, lookup_token, payload_version, "
                    "key_id, nonce, encrypted_payload, expire_at, created_at, "
                    f"updated_at, translation_bytes FROM {TABLE_NAME} "
                    "WHERE principal_id = ? AND object_kind = ? AND lookup_token = ?",
                    (principal_id, kind.value, token),
                ).fetchone()
                if existing is not None:
                    existing_source, existing_target = self._decrypt_row(
                        existing,
                        cipher=cipher,
                    )
                    if existing_source == source and existing_target == target:
                        merged += 1
                        continue
                    self._conn.execute(
                        f"DELETE FROM {TABLE_NAME} WHERE principal_id = ? "
                        "AND object_kind = ? AND lookup_token = ?",
                        (principal_id, kind.value, token),
                    )
                    self._conn.execute(
                        "INSERT INTO tool_history_migration_conflicts VALUES (?, ?, ?)",
                        (principal_id, kind.value, token),
                    )
                    conflicts += 1
                    continue
                aad = tool_history_translation_aad(
                    principal_id=principal_id,
                    object_kind=kind.value,
                    lookup_token=token,
                )
                nonce, encrypted_payload = cipher.encrypt_tool_history_translation(
                    source_template=source,
                    target_template=target,
                    aad=aad,
                )
                byte_size = self._row_bytes(
                    principal_id=principal_id,
                    object_kind=kind.value,
                    lookup_token=token,
                    key_id=cipher.key_id,
                    nonce=nonce,
                    encrypted_payload=encrypted_payload,
                    expire_at=str(row[9]),
                    created_at=str(row[10]),
                    updated_at=str(row[11]),
                )
                self._conn.execute(
                    f"INSERT INTO {TABLE_NAME} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        principal_id,
                        kind.value,
                        token,
                        TOOL_HISTORY_PAYLOAD_VERSION,
                        cipher.key_id,
                        nonce,
                        encrypted_payload,
                        byte_size,
                        str(row[9]),
                        str(row[10]),
                        str(row[11]),
                    ),
                )
                migrated += 1
            self._validate_capacity_locked()
            self._conn.execute(f"DROP TABLE {LEGACY_TABLE_NAME}")
            self._conn.execute("DROP TABLE tool_history_migration_conflicts")
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        logger.warning(
            "Migrated encrypted tool history to content-addressed objects "
            "(migrated=%d merged=%d conflicts=%d expired=%d)",
            migrated,
            merged,
            conflicts,
            expired,
        )

    def _discard_plaintext_legacy(self, *, current_exists: bool) -> None:
        legacy_count = int(
            self._conn.execute(f"SELECT COUNT(*) FROM {LEGACY_TABLE_NAME}").fetchone()[
                0
            ]
        )
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(f"DROP TABLE {LEGACY_TABLE_NAME}")
            if not current_exists:
                self._create_schema(commit=False)
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        logger.warning(
            "Discarded %d plaintext/redacted legacy tool-history row(s)",
            legacy_count,
        )

    def _create_schema(self, *, commit: bool = False) -> None:
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                principal_id       TEXT NOT NULL,
                object_kind        TEXT NOT NULL,
                lookup_token       BLOB NOT NULL,
                payload_version    INTEGER NOT NULL,
                key_id             TEXT NOT NULL,
                nonce              BLOB NOT NULL,
                encrypted_payload  BLOB NOT NULL,
                translation_bytes  INTEGER NOT NULL,
                expire_at          TEXT NOT NULL,
                created_at         TEXT NOT NULL,
                updated_at         TEXT NOT NULL,
                PRIMARY KEY (principal_id, object_kind, lookup_token)
            )
        """)
        self._conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_thot_expire_at ON {TABLE_NAME}(expire_at)"
        )
        self._conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_thot_principal "
            f"ON {TABLE_NAME}(principal_id)"
        )
        if commit:
            self._conn.commit()

    def _validate_schema(self) -> None:
        observed = tuple(
            (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]))
            for row in self._conn.execute(f"PRAGMA table_info({TABLE_NAME})")
        )
        if observed != EXPECTED_COLUMNS:
            raise RuntimeError(
                f"incompatible gateway.db schema for {TABLE_NAME}: "
                "column/type/constraint shape differs from the supported schema"
            )
        indexes = {
            str(row[1]): (int(row[2]), str(row[3]), int(row[4]))
            for row in self._conn.execute(f"PRAGMA index_list({TABLE_NAME})")
        }
        for name, columns in EXPECTED_INDEXES.items():
            if indexes.get(name) != (0, "c", 0):
                raise RuntimeError(
                    f"incompatible gateway.db schema for {TABLE_NAME}: "
                    f"missing or invalid index {name!r}"
                )
            observed_columns = tuple(
                str(row[2]) for row in self._conn.execute(f"PRAGMA index_info({name})")
            )
            if observed_columns != columns:
                raise RuntimeError(
                    f"incompatible gateway.db schema for {TABLE_NAME}: "
                    f"index {name!r} has unexpected columns"
                )

    def _validate_encrypted_rows_locked(self) -> None:
        rows = self._conn.execute(
            f"SELECT principal_id, object_kind, lookup_token, payload_version, "
            "key_id, nonce, encrypted_payload, expire_at, created_at, updated_at, "
            f"translation_bytes FROM {TABLE_NAME}"
        ).fetchall()
        if not rows:
            return
        cipher = self._cipher_loader(False)
        for row in rows:
            self._decrypt_row(row, cipher=cipher)

    def _decrypt_row(
        self,
        row: tuple[Any, ...],
        *,
        cipher: ToolMappingCipher,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if int(row[3]) != TOOL_HISTORY_PAYLOAD_VERSION:
            raise ToolMappingIntegrityError(
                f"Unsupported tool-history format version {row[3]!r}"
            )
        kind = ToolHistoryObjectKind(str(row[1]))
        token = bytes(row[2])
        source, target = cipher.decrypt_tool_history_translation(
            key_id=str(row[4]),
            nonce=bytes(row[5]),
            encrypted_payload=bytes(row[6]),
            aad=tool_history_translation_aad(
                principal_id=str(row[0]),
                object_kind=kind.value,
                lookup_token=token,
            ),
        )
        expected_token = cipher.tool_history_lookup_token(
            principal_id=str(row[0]),
            object_kind=kind.value,
            canonical_source=canonical_tool_history_template(source),
        )
        if not hmac.compare_digest(expected_token, token):
            raise ToolMappingIntegrityError(
                "Authenticated tool-history source does not match lookup token"
            )
        return source, target

    def _validate_projected_insert_locked(
        self,
        *,
        principal_id: str,
        byte_size: int,
    ) -> None:
        if byte_size > self._max_row_bytes:
            self._raise_capacity("row bytes", self._max_row_bytes)
        principal_rows, principal_bytes = self._usage_locked(
            "principal_id = ?",
            (principal_id,),
        )
        global_rows, global_bytes = self._usage_locked()
        projected = (
            ("principal row count", principal_rows + 1, self._max_principal_rows),
            ("principal bytes", principal_bytes + byte_size, self._max_principal_bytes),
            ("global row count", global_rows + 1, self._max_global_rows),
            ("global bytes", global_bytes + byte_size, self._max_global_bytes),
        )
        for label, actual, limit in projected:
            if actual > limit:
                self._raise_capacity(label, limit)

    def _validate_capacity_locked(self) -> None:
        global_rows, global_bytes = self._usage_locked()
        if global_rows > self._max_global_rows:
            self._raise_capacity("global row count", self._max_global_rows)
        if global_bytes > self._max_global_bytes:
            self._raise_capacity("global bytes", self._max_global_bytes)
        for (principal_id,) in self._conn.execute(
            f"SELECT DISTINCT principal_id FROM {TABLE_NAME}"
        ):
            rows, byte_size = self._usage_locked(
                "principal_id = ?",
                (principal_id,),
            )
            if rows > self._max_principal_rows:
                self._raise_capacity("principal row count", self._max_principal_rows)
            if byte_size > self._max_principal_bytes:
                self._raise_capacity("principal bytes", self._max_principal_bytes)

    def _usage_locked(
        self,
        where: str = "",
        params: tuple[Any, ...] = (),
    ) -> tuple[int, int]:
        predicate = f" WHERE {where}" if where else ""
        row = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(translation_bytes), 0), "
            f"COALESCE(SUM({_SQL_BYTES}), 0), "
            f"COALESCE(SUM(translation_bytes != ({_SQL_BYTES})), 0) "
            f"FROM {TABLE_NAME}{predicate}",
            params,
        ).fetchone()
        count = int(row[0]) if row else 0
        stored_bytes = int(row[1]) if row else 0
        actual_bytes = int(row[2]) if row else 0
        mismatches = int(row[3]) if row else 0
        if mismatches or stored_bytes != actual_bytes:
            raise ToolHistoryCapacityError(
                "Encrypted tool-history accounting is invalid; refusing replay"
            )
        return count, actual_bytes

    @staticmethod
    def _row_bytes(
        *,
        principal_id: str,
        object_kind: str,
        lookup_token: bytes,
        key_id: str,
        nonce: bytes,
        encrypted_payload: bytes,
        expire_at: str,
        created_at: str,
        updated_at: str,
    ) -> int:
        return (
            16
            + len(principal_id.encode("utf-8"))
            + len(object_kind.encode("utf-8"))
            + len(lookup_token)
            + len(key_id.encode("utf-8"))
            + len(nonce)
            + len(encrypted_payload)
            + len(expire_at.encode("utf-8"))
            + len(created_at.encode("utf-8"))
            + len(updated_at.encode("utf-8"))
        )

    @staticmethod
    def _raise_capacity(label: str, limit: int) -> None:
        raise ToolHistoryCapacityError(
            f"Encrypted tool-history {label} exceeds hard limit {limit}"
        )

    def _table_exists(self, table: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            is not None
        )
