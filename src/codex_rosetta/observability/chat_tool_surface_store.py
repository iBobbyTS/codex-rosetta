"""Encrypted persistent snapshots for window-scoped Chat tool surfaces."""

from __future__ import annotations

import hmac
import json
import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from .tool_mapping_crypto import (
    CHAT_TOOL_SURFACE_PAYLOAD_VERSION,
    ToolMappingCipher,
    ToolMappingIntegrityError,
    chat_tool_surface_aad,
)

TABLE_NAME = "codex_chat_tool_surface_snapshots"
TTL = timedelta(hours=24)

DEFAULT_MAX_ROW_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_PRINCIPAL_ROWS = 1_024
DEFAULT_MAX_PRINCIPAL_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_GLOBAL_ROWS = 8_192
DEFAULT_MAX_GLOBAL_BYTES = 512 * 1024 * 1024

EXPECTED_COLUMNS = (
    ("scope_token", "BLOB", 1, 1),
    ("principal_id", "TEXT", 1, 0),
    ("payload_version", "INTEGER", 1, 0),
    ("key_id", "TEXT", 1, 0),
    ("nonce", "BLOB", 1, 0),
    ("encrypted_payload", "BLOB", 1, 0),
    ("snapshot_bytes", "INTEGER", 1, 0),
    ("expire_at", "TEXT", 1, 0),
    ("created_at", "TEXT", 1, 0),
    ("updated_at", "TEXT", 1, 0),
)


class ChatToolSurfaceCapacityError(RuntimeError):
    """A tool-surface snapshot exceeded a hard persistence quota."""


class ChatToolSurfaceConflictError(RuntimeError):
    """A concurrent writer replaced the expected surface epoch."""


def canonical_surface_scope(scope: dict[str, Any]) -> bytes:
    """Serialize the complete encrypted lookup scope deterministically."""
    return json.dumps(
        scope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


class ChatToolSurfaceStore:
    """Own schema, AEAD, sliding TTL, concurrency, and snapshot quotas."""

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        lock: threading.RLock,
        cipher_loader: Callable[[bool], ToolMappingCipher],
        max_row_bytes: int = DEFAULT_MAX_ROW_BYTES,
        max_principal_rows: int = DEFAULT_MAX_PRINCIPAL_ROWS,
        max_principal_bytes: int = DEFAULT_MAX_PRINCIPAL_BYTES,
        max_global_rows: int = DEFAULT_MAX_GLOBAL_ROWS,
        max_global_bytes: int = DEFAULT_MAX_GLOBAL_BYTES,
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

    def load_or_create(
        self,
        *,
        principal_id: str,
        scope: dict[str, Any],
        initial_payload: dict[str, Any],
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically return the winning snapshot, creating it if absent."""
        timestamp = _utc_now(now)
        canonical_scope = canonical_surface_scope(scope)
        with self._lock:
            cipher = self._cipher_loader(True)
            token = cipher.chat_tool_surface_scope_token(
                principal_id=principal_id,
                canonical_scope=canonical_scope,
            )
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._delete_expired_locked(timestamp)
                row = self._select_locked(token)
                if row is not None:
                    payload = self._decrypt_row(
                        row,
                        expected_principal=principal_id,
                        expected_scope=scope,
                        cipher=cipher,
                    )
                    self._conn.execute(
                        f"UPDATE {TABLE_NAME} SET expire_at = ?, updated_at = ? "
                        "WHERE scope_token = ?",
                        (_expires_at(timestamp), timestamp, token),
                    )
                    self._conn.commit()
                    return payload, False

                payload = {**initial_payload, "scope": scope}
                self._insert_locked(
                    token=token,
                    principal_id=principal_id,
                    payload=payload,
                    cipher=cipher,
                    timestamp=timestamp,
                )
                self._conn.commit()
                return payload, True
            except BaseException:
                self._conn.rollback()
                raise

    def replace(
        self,
        *,
        principal_id: str,
        scope: dict[str, Any],
        expected_epoch: int,
        payload: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Replace one snapshot only when its authenticated epoch still matches."""
        timestamp = _utc_now(now)
        canonical_scope = canonical_surface_scope(scope)
        with self._lock:
            cipher = self._cipher_loader(False)
            token = cipher.chat_tool_surface_scope_token(
                principal_id=principal_id,
                canonical_scope=canonical_scope,
            )
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._delete_expired_locked(timestamp)
                row = self._select_locked(token)
                if row is None:
                    raise ChatToolSurfaceConflictError("surface snapshot expired")
                current = self._decrypt_row(
                    row,
                    expected_principal=principal_id,
                    expected_scope=scope,
                    cipher=cipher,
                )
                if current.get("epoch") != expected_epoch:
                    raise ChatToolSurfaceConflictError(
                        "surface snapshot epoch changed concurrently"
                    )
                replacement = {**payload, "scope": scope}
                nonce, ciphertext = cipher.encrypt_chat_tool_surface(
                    payload=replacement,
                    aad=chat_tool_surface_aad(
                        principal_id=principal_id,
                        scope_token=token,
                    ),
                )
                byte_size = self._row_bytes(
                    principal_id=principal_id,
                    key_id=cipher.key_id,
                    nonce=nonce,
                    ciphertext=ciphertext,
                    timestamp=timestamp,
                )
                self._validate_replacement_capacity_locked(
                    token=token,
                    principal_id=principal_id,
                    byte_size=byte_size,
                )
                self._conn.execute(
                    f"UPDATE {TABLE_NAME} SET payload_version = ?, key_id = ?, "
                    "nonce = ?, encrypted_payload = ?, snapshot_bytes = ?, "
                    "expire_at = ?, updated_at = ? WHERE scope_token = ?",
                    (
                        CHAT_TOOL_SURFACE_PAYLOAD_VERSION,
                        cipher.key_id,
                        nonce,
                        ciphertext,
                        byte_size,
                        _expires_at(timestamp),
                        timestamp,
                        token,
                    ),
                )
                self._conn.commit()
                return replacement
            except BaseException:
                self._conn.rollback()
                raise

    def cleanup_expired(self, now: datetime | None = None) -> int:
        """Delete expired snapshots without evicting any live row."""
        timestamp = _utc_now(now)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                count = self._delete_expired_locked(timestamp)
                self._conn.commit()
                return count
            except BaseException:
                self._conn.rollback()
                raise

    def count(self) -> int:
        """Return the number of stored snapshots."""
        with self._lock:
            row = self._conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()
        return int(row[0]) if row else 0

    def _initialize(self) -> None:
        with self._lock:
            self._create_schema()
            self._validate_schema()
            self.cleanup_expired()
            rows = self._conn.execute(
                f"SELECT scope_token, principal_id, payload_version, key_id, "
                "nonce, encrypted_payload, snapshot_bytes, expire_at, created_at, "
                f"updated_at FROM {TABLE_NAME}"
            ).fetchall()
            if rows:
                cipher = self._cipher_loader(False)
                for row in rows:
                    self._decrypt_row(row, cipher=cipher)
            self._validate_capacity_locked()

    def _create_schema(self) -> None:
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                scope_token       BLOB NOT NULL PRIMARY KEY,
                principal_id      TEXT NOT NULL,
                payload_version   INTEGER NOT NULL,
                key_id            TEXT NOT NULL,
                nonce             BLOB NOT NULL,
                encrypted_payload BLOB NOT NULL,
                snapshot_bytes    INTEGER NOT NULL,
                expire_at         TEXT NOT NULL,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL
            )
        """)
        self._conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_cctss_expire_at ON {TABLE_NAME}(expire_at)"
        )
        self._conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_cctss_principal "
            f"ON {TABLE_NAME}(principal_id)"
        )
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
        expected_indexes = {
            "idx_cctss_expire_at": ("expire_at",),
            "idx_cctss_principal": ("principal_id",),
        }
        indexes = {
            str(row[1]): (int(row[2]), str(row[3]), int(row[4]))
            for row in self._conn.execute(f"PRAGMA index_list({TABLE_NAME})")
        }
        for name, columns in expected_indexes.items():
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

    def _insert_locked(
        self,
        *,
        token: bytes,
        principal_id: str,
        payload: dict[str, Any],
        cipher: ToolMappingCipher,
        timestamp: str,
    ) -> None:
        nonce, ciphertext = cipher.encrypt_chat_tool_surface(
            payload=payload,
            aad=chat_tool_surface_aad(
                principal_id=principal_id,
                scope_token=token,
            ),
        )
        byte_size = self._row_bytes(
            principal_id=principal_id,
            key_id=cipher.key_id,
            nonce=nonce,
            ciphertext=ciphertext,
            timestamp=timestamp,
        )
        self._validate_insert_capacity_locked(
            principal_id=principal_id,
            byte_size=byte_size,
        )
        self._conn.execute(
            f"INSERT INTO {TABLE_NAME} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                principal_id,
                CHAT_TOOL_SURFACE_PAYLOAD_VERSION,
                cipher.key_id,
                nonce,
                ciphertext,
                byte_size,
                _expires_at(timestamp),
                timestamp,
                timestamp,
            ),
        )

    def _select_locked(self, token: bytes) -> tuple[Any, ...] | None:
        return self._conn.execute(
            f"SELECT scope_token, principal_id, payload_version, key_id, nonce, "
            "encrypted_payload, snapshot_bytes, expire_at, created_at, updated_at "
            f"FROM {TABLE_NAME} WHERE scope_token = ?",
            (token,),
        ).fetchone()

    def _decrypt_row(
        self,
        row: tuple[Any, ...],
        *,
        expected_principal: str | None = None,
        expected_scope: dict[str, Any] | None = None,
        cipher: ToolMappingCipher,
    ) -> dict[str, Any]:
        if int(row[2]) != CHAT_TOOL_SURFACE_PAYLOAD_VERSION:
            raise ToolMappingIntegrityError(
                f"Unsupported Chat tool-surface payload version {row[2]!r}"
            )
        principal_id = str(row[1])
        actual_bytes = (
            64
            + len(principal_id.encode())
            + len(str(row[3]).encode())
            + len(bytes(row[4]))
            + len(bytes(row[5]))
            + len(str(row[7]).encode())
            + len(str(row[8]).encode())
            + len(str(row[9]).encode())
        )
        if int(row[6]) != actual_bytes:
            raise ToolMappingIntegrityError(
                "Chat tool-surface accounting does not match encrypted row"
            )
        if expected_principal is not None and principal_id != expected_principal:
            raise ToolMappingIntegrityError(
                "Chat tool-surface principal does not match lookup owner"
            )
        token = bytes(row[0])
        payload = cipher.decrypt_chat_tool_surface(
            key_id=str(row[3]),
            nonce=bytes(row[4]),
            encrypted_payload=bytes(row[5]),
            aad=chat_tool_surface_aad(
                principal_id=principal_id,
                scope_token=token,
            ),
        )
        scope = payload.get("scope")
        if not isinstance(scope, dict):
            raise ToolMappingIntegrityError(
                "Chat tool-surface payload is missing its authenticated scope"
            )
        expected_token = cipher.chat_tool_surface_scope_token(
            principal_id=principal_id,
            canonical_scope=canonical_surface_scope(scope),
        )
        if not hmac.compare_digest(expected_token, token):
            raise ToolMappingIntegrityError(
                "Authenticated Chat tool-surface scope does not match lookup token"
            )
        if expected_scope is not None and scope != expected_scope:
            raise ToolMappingIntegrityError(
                "Chat tool-surface payload scope does not match request scope"
            )
        if not isinstance(payload.get("epoch"), int) or not isinstance(
            payload.get("tools"), list
        ):
            raise ToolMappingIntegrityError(
                "Chat tool-surface payload is missing its epoch or tools"
            )
        return payload

    def _delete_expired_locked(self, timestamp: str) -> int:
        cursor = self._conn.execute(
            f"DELETE FROM {TABLE_NAME} WHERE expire_at <= ?",
            (timestamp,),
        )
        return max(0, int(cursor.rowcount))

    def _usage_locked(
        self,
        where: str = "",
        values: tuple[Any, ...] = (),
        *,
        exclude_token: bytes | None = None,
    ) -> tuple[int, int]:
        conditions = [where] if where else []
        params = list(values)
        if exclude_token is not None:
            conditions.append("scope_token != ?")
            params.append(exclude_token)
        clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        row = self._conn.execute(
            f"SELECT COUNT(*), COALESCE(SUM(snapshot_bytes), 0) "
            f"FROM {TABLE_NAME}{clause}",
            tuple(params),
        ).fetchone()
        return (int(row[0]), int(row[1])) if row else (0, 0)

    def _validate_insert_capacity_locked(
        self, *, principal_id: str, byte_size: int
    ) -> None:
        self._validate_projected_capacity_locked(
            principal_id=principal_id,
            byte_size=byte_size,
            exclude_token=None,
        )

    def _validate_replacement_capacity_locked(
        self,
        *,
        token: bytes,
        principal_id: str,
        byte_size: int,
    ) -> None:
        self._validate_projected_capacity_locked(
            principal_id=principal_id,
            byte_size=byte_size,
            exclude_token=token,
        )

    def _validate_projected_capacity_locked(
        self,
        *,
        principal_id: str,
        byte_size: int,
        exclude_token: bytes | None,
    ) -> None:
        if byte_size > self._max_row_bytes:
            self._raise_capacity("row bytes", self._max_row_bytes)
        principal_rows, principal_bytes = self._usage_locked(
            "principal_id = ?",
            (principal_id,),
            exclude_token=exclude_token,
        )
        global_rows, global_bytes = self._usage_locked(exclude_token=exclude_token)
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
        rows, byte_size = self._usage_locked()
        if rows > self._max_global_rows:
            self._raise_capacity("global row count", self._max_global_rows)
        if byte_size > self._max_global_bytes:
            self._raise_capacity("global bytes", self._max_global_bytes)
        principals = self._conn.execute(
            f"SELECT principal_id, COUNT(*), COALESCE(SUM(snapshot_bytes), 0) "
            f"FROM {TABLE_NAME} GROUP BY principal_id"
        ).fetchall()
        for _principal_id, principal_rows, principal_bytes in principals:
            if int(principal_rows) > self._max_principal_rows:
                self._raise_capacity("principal row count", self._max_principal_rows)
            if int(principal_bytes) > self._max_principal_bytes:
                self._raise_capacity("principal bytes", self._max_principal_bytes)

    @staticmethod
    def _row_bytes(
        *,
        principal_id: str,
        key_id: str,
        nonce: bytes,
        ciphertext: bytes,
        timestamp: str,
    ) -> int:
        return (
            64
            + len(principal_id.encode())
            + len(key_id.encode())
            + len(nonce)
            + len(ciphertext)
            + 3 * len(timestamp.encode())
        )

    @staticmethod
    def _raise_capacity(label: str, limit: int) -> None:
        raise ChatToolSurfaceCapacityError(
            f"Chat tool-surface persistence exceeds {label} limit {limit}"
        )


def _utc_now(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _expires_at(timestamp: str) -> str:
    return (datetime.fromisoformat(timestamp) + TTL).isoformat()
