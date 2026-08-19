"""Local persistence for Admin-managed provider accounts.

The account database is deliberately separate from gateway configuration and
request observability data.  Public account projections never include token
material; token columns are only read while completing a provider flow.
"""

from __future__ import annotations

import json
import base64
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
        query = "SELECT id, provider, metadata_json, credentials_json FROM accounts"
        params: tuple[str, ...] = ()
        if provider:
            query += " WHERE provider = ?"
            params = (provider,)
        query += " ORDER BY created_at DESC, id"
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
                # Keep the account label public, but never expose the auth
                # export.  The label is the normalized Base URL entered by
                # the user when the account was added.
                base_url = metadata.get("base_url") or metadata.get("name") or ""
                metadata = {
                    "name": base_url,
                    "email": metadata.get("email", ""),
                    "base_url": base_url,
                }
            elif row["provider"] == "chatgpt":
                metadata = _correct_chatgpt_workspace(metadata, row["credentials_json"])
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

    def get_private(self, account_id: str) -> dict[str, Any] | None:
        """Return one account's private metadata and credentials internally."""
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT id, provider, identity, metadata_json, credentials_json FROM accounts WHERE id = ?",
                    (account_id,),
                ).fetchone()
            finally:
                self._close(connection)
        if row is None:
            return None
        return {
            "id": row["id"],
            "provider": row["provider"],
            "identity": row["identity"],
            "metadata": json.loads(row["metadata_json"]),
            "credentials": json.loads(row["credentials_json"]),
        }

    def update_metadata(self, account_id: str, metadata: dict[str, Any]) -> bool:
        """Update one account's public metadata without changing credentials."""
        with self._lock:
            connection = self._connect()
            try:
                cursor = connection.execute(
                    "UPDATE accounts SET metadata_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (
                        json.dumps(metadata, ensure_ascii=True, separators=(",", ":")),
                        account_id,
                    ),
                )
                connection.commit()
                return cursor.rowcount > 0
            finally:
                self._close(connection)

    def update_credentials(self, account_id: str, credentials: dict[str, str]) -> bool:
        """Replace private credentials for an existing account atomically."""
        if not credentials:
            raise ValueError("account credentials are required")
        with self._lock:
            connection = self._connect()
            try:
                cursor = connection.execute(
                    "UPDATE accounts SET credentials_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (
                        json.dumps(
                            credentials, ensure_ascii=True, separators=(",", ":")
                        ),
                        account_id,
                    ),
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


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        segment = token.split(".")[1]
        segment += "=" * (-len(segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(segment.encode()))
    except IndexError, ValueError, TypeError, json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _correct_chatgpt_workspace(
    metadata: dict[str, Any], credentials_json: str
) -> dict[str, Any]:
    """Correct legacy workspace projections from locally saved token claims."""
    corrected = dict(metadata)
    try:
        credentials = json.loads(credentials_json)
    except TypeError, ValueError, json.JSONDecodeError:
        credentials = {}
    access = _decode_jwt_payload(credentials.get("access_token", ""))
    identity = _decode_jwt_payload(credentials.get("id_token", ""))
    auth = access.get("https://api.openai.com/auth")
    identity_auth = identity.get("https://api.openai.com/auth")
    if not isinstance(auth, dict):
        auth = identity_auth if isinstance(identity_auth, dict) else {}
    if not isinstance(identity_auth, dict):
        identity_auth = {}
    organizations = auth.get("organizations") or identity_auth.get("organizations")
    poid = auth.get("poid") or identity_auth.get("poid")
    claim_plan = auth.get("chatgpt_plan_type") or identity_auth.get("chatgpt_plan_type")
    if isinstance(claim_plan, str) and claim_plan.strip().lower() == "free":
        corrected["subscription_type"] = "free"
        corrected["workspace"] = "Personal"
    selected = None
    if isinstance(organizations, list):
        selected = next(
            (
                item
                for item in organizations
                if isinstance(item, dict) and poid and item.get("id") == poid
            ),
            next((item for item in organizations if isinstance(item, dict)), None),
        )
    if isinstance(selected, dict):
        title = next(
            (
                selected.get(key).strip()
                for key in ("title", "name", "display_name", "organization_name")
                if isinstance(selected.get(key), str) and selected.get(key).strip()
            ),
            "",
        )
        existing_workspace = str(corrected.get("workspace", "")).strip().lower()
        if title and existing_workspace in {
            "",
            "personal",
            "team",
            "workspace",
            "personal workspace",
        }:
            corrected["workspace"] = title
    if not corrected.get("workspace"):
        plan = str(corrected.get("subscription_type", "")).strip().lower()
        if "free" in plan:
            corrected["workspace"] = "Personal"
    return corrected
