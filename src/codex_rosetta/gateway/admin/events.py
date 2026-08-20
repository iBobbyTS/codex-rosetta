"""Process-local delivery of authenticated Admin model-group switch events."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from codex_rosetta._vendor.httpserver import JSONResponse, Response

from ..config import _ModelGroupProviderCandidate, GatewayConfig
from .routes._shared import _qp


@dataclass(frozen=True, slots=True)
class AutomaticSwitchEvent:
    """One automatic model-group candidate change for browser delivery."""

    id: int
    group: str
    old_candidate: dict[str, str | None]
    new_candidate: dict[str, str | None]
    old_rate: float | None
    new_rate: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "group": self.group,
            "old_candidate": self.old_candidate,
            "new_candidate": self.new_candidate,
            "old_rate": self.old_rate,
            "new_rate": self.new_rate,
        }


def _candidate_dict(
    candidate: _ModelGroupProviderCandidate, config: GatewayConfig
) -> dict[str, str | None]:
    credential_id: str | None = None
    if candidate.credential_uuid is not None:
        provider = config.providers.get(candidate.provider_name)
        if provider is not None:
            try:
                credential_id = provider.credential_id_for_uuid(candidate.credential_uuid)
            except ValueError:
                credential_id = None
    return {
        "provider": candidate.provider_name,
        "credential_id": credential_id,
    }


class AutomaticSwitchEventStore:
    """Bounded process-local cursor store; events are not persisted or replayed offline."""

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config
        self._next_id = 1
        self._events: deque[AutomaticSwitchEvent] = deque(maxlen=256)

    def update_config(self, config: GatewayConfig) -> None:
        self._config = config

    async def record(
        self,
        group: str,
        old_candidate: _ModelGroupProviderCandidate,
        new_candidate: _ModelGroupProviderCandidate,
    ) -> None:
        event = AutomaticSwitchEvent(
            id=self._next_id,
            group=group,
            old_candidate=_candidate_dict(old_candidate, self._config),
            new_candidate=_candidate_dict(new_candidate, self._config),
            old_rate=self._config.model_group_candidate_multiplier(old_candidate),
            new_rate=self._config.model_group_candidate_multiplier(new_candidate),
        )
        self._next_id += 1
        self._events.append(event)

    def after(self, cursor: int, group: str | None = None) -> list[dict[str, Any]]:
        return [
            event.as_dict()
            for event in self._events
            if event.id > cursor and (group is None or event.group == group)
        ]

    @property
    def cursor(self) -> int:
        return self._next_id - 1


async def get_model_group_switch_events(request: Any) -> Response:
    """Return automatic switch events newer than a process-local cursor."""
    raw_cursor = _qp(request, "cursor")
    store = getattr(request.app, "automatic_switch_events", None)
    if store is None:
        return JSONResponse({"cursor": 0, "events": []})
    if raw_cursor is None:
        return JSONResponse({"cursor": store.cursor, "events": []})
    try:
        cursor = max(0, int(raw_cursor))
    except (TypeError, ValueError):
        return JSONResponse({"error": "cursor must be an integer"}, status_code=400)
    group = _qp(request, "group", "").strip() or None
    return JSONResponse({"cursor": store.cursor, "events": store.after(cursor, group)})
