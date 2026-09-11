"""Authenticated ownership scope for gateway cross-request state."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any


_CODEX_SESSION_ID_MAX_BYTES = 512
_CODEX_TURN_METADATA_MAX_BYTES = 16 * 1024


def _bounded_utf8(value: str, limit: int) -> bool:
    try:
        return len(value.encode("utf-8")) <= limit
    except UnicodeEncodeError:
        return False


def _valid_session_id(value: Any) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or not _bounded_utf8(value, _CODEX_SESSION_ID_MAX_BYTES)
    ):
        return None
    return value


def codex_session_id(client_metadata: Any) -> str | None:
    """Return one trustworthy Codex session ID, or ``None`` for isolation.

    The direct ``client_metadata.session_id`` field is authoritative.  The
    embedded turn metadata is only a consistency check and is never a fallback.
    """
    if not isinstance(client_metadata, dict):
        return None
    session_id = _valid_session_id(client_metadata.get("session_id"))
    if session_id is None:
        return None

    raw_turn_metadata = client_metadata.get("x-codex-turn-metadata")
    if raw_turn_metadata is None:
        return session_id
    if not isinstance(raw_turn_metadata, str) or not _bounded_utf8(
        raw_turn_metadata, _CODEX_TURN_METADATA_MAX_BYTES
    ):
        return None
    try:
        turn_metadata = json.loads(raw_turn_metadata)
    except TypeError, ValueError:
        return None
    if not isinstance(turn_metadata, dict):
        return None
    embedded_session_id = _valid_session_id(turn_metadata.get("session_id"))
    if embedded_session_id != session_id:
        return None
    return session_id


@dataclass(frozen=True)
class GatewayStateScope:
    """Identify the authenticated owner and conversation of mutable state.

    ``conversation_id`` is either a client window ID or a request-local ID.
    Only scopes with ``persistent=True`` may be written to cross-request
    persistence.
    """

    principal_id: str
    provider_name: str
    model: str
    conversation_id: str
    persistent: bool

    @classmethod
    def for_request(
        cls,
        *,
        principal_id: str,
        provider_name: str,
        model: str,
        window_id: str | None,
    ) -> GatewayStateScope:
        """Build a persistent window scope or an isolated request-local scope."""
        if window_id:
            return cls(
                principal_id=principal_id,
                provider_name=provider_name,
                model=model,
                conversation_id=window_id,
                persistent=True,
            )
        return cls(
            principal_id=principal_id,
            provider_name=provider_name,
            model=model,
            conversation_id=f"request:{uuid.uuid4().hex}",
            persistent=False,
        )

    @classmethod
    def for_stream_failover(
        cls,
        *,
        principal_id: str,
        provider_name: str,
        model: str,
        client_metadata: Any,
    ) -> GatewayStateScope:
        """Build a session scope for stream failover or isolate this request."""
        return cls.for_request(
            principal_id=principal_id,
            provider_name=provider_name,
            model=model,
            window_id=codex_session_id(client_metadata),
        )
