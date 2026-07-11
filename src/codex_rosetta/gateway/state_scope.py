"""Authenticated ownership scope for gateway cross-request state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


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
