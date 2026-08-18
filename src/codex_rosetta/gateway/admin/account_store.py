"""Local persistence for Admin-managed provider accounts.

The account database is deliberately separate from gateway configuration and
request observability data.  Public account projections never include token
material; token columns are only read while completing a provider flow.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any


class AccountStore:
    """Persist account metadata and provider credentials in SQLite."""

    def __init__(self, config_path: str | None) -> None:
        if config_path:
            self.path = Path(config_path).parent / "data" / "accounts.db"
            self.path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.path = None
        self._lock = threading.RLock()
        self._memory_connection: sqlite3.Connection | None = None
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self.path is None:
            if self._memory_connection is None:
                # OAuth callbacks persist from an asyncio worker thread while
                # the Admin list is commonly served by the event-loop thread.
                # The store lock serializes access to this shared connection.
                self._memory_connection = sqlite3.connect(
                    ":memory:", check_same_thread=False
                )
            connection = self._memory_connection
        else:
            connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _close(self, connection: sqlite3.Connection) -> None:
        if self.path is not None:
            connection.close()

    def _initialize(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS accounts (
                        id TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        identity TEXT NOT NULL,
                        metadata_json TEXT NOT NULL,
                        credentials_json TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(provider, identity)
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_accounts_provider ON accounts(provider)"
                )
                connection.commit()
            finally:
                self._close(connection)
            if self.path:
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass

    def list_public(self, provider: str | None = None) -> list[dict[str, Any]]:
        """Return account metadata without credential fields."""
        query = "SELECT id, provider, metadata_json FROM accounts"
        params: tuple[str, ...] = ()
        if provider:
            query += " WHERE provider = ?"
            params = (provider,)
        query += " ORDER BY updated_at DESC, id"
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(query, params).fetchall()
            finally:
                self._close(connection)
        result: list[dict[str, Any]] = []
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            if row["provider"] == "sub2api":
                metadata = {"email": metadata.get("email", "")}
            result.append({"id": row["id"], "provider": row["provider"], **metadata})
        return result

    def upsert(
        self,
        *,
        provider: str,
        identity: str,
        metadata: dict[str, Any],
        credentials: dict[str, str],
    ) -> dict[str, Any]:
        """Insert or replace one provider account identified by stable identity."""
        if not identity.strip():
            raise ValueError("account identity is required")
        if not credentials:
            raise ValueError("account credentials are required")
        account_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"codex-rosetta:{provider}:{identity}"
        ).hex
        metadata_json = json.dumps(metadata, ensure_ascii=True, separators=(",", ":"))
        credentials_json = json.dumps(
            credentials, ensure_ascii=True, separators=(",", ":")
        )
        with self._lock:
            connection = self._connect()
            try:
                connection.execute(
                    """
                    INSERT INTO accounts(id, provider, identity, metadata_json, credentials_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(provider, identity) DO UPDATE SET
                      id = excluded.id,
                      metadata_json = excluded.metadata_json,
                      credentials_json = excluded.credentials_json,
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    (account_id, provider, identity, metadata_json, credentials_json),
                )
                connection.commit()
            finally:
                self._close(connection)
        return {"id": account_id, "provider": provider, **metadata}

    def delete(self, account_id: str) -> bool:
        """Delete one locally stored account and its credentials."""
        with self._lock:
            connection = self._connect()
            try:
                cursor = connection.execute(
                    "DELETE FROM accounts WHERE id = ?", (account_id,)
                )
                connection.commit()
                return cursor.rowcount > 0
            finally:
                self._close(connection)


def get_account_store(app: Any) -> AccountStore:
    """Return the app-owned account store, creating it exactly once.

    The app owns this instance so flows that complete outside the authenticated
    Admin API (such as the OAuth callback) observe the same in-memory store as
    the account-list route when no config path is available.
    """
    store = getattr(app, "account_store", None)
    if store is None:
        store = AccountStore(getattr(app, "config_path", None))
        setattr(app, "account_store", store)
    return store
