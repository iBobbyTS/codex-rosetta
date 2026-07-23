"""Versioned machine protocol for the local desktop sidecar."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TextIO
from urllib.parse import urlsplit


PROTOCOL_VERSION = 1
EVENT_PREFIX = f"ROSETTA_DESKTOP/{PROTOCOL_VERSION} "
MAX_LINE_BYTES = 64 * 1024


class DesktopProtocolError(ValueError):
    """Raised when a desktop protocol message violates its fixed schema."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DesktopEvent:
    """One allowlisted sidecar event."""

    event: str
    payload: dict[str, Any]

    def serialize(self) -> str:
        """Serialize this event as one bounded protocol line."""
        body = {"protocol": PROTOCOL_VERSION, "event": self.event, **self.payload}
        encoded = EVENT_PREFIX + json.dumps(
            body, ensure_ascii=True, separators=(",", ":")
        )
        if len(encoded.encode("utf-8")) > MAX_LINE_BYTES:
            raise DesktopProtocolError("event_too_large", "Desktop event is too large")
        return encoded


def emit_event(stream: TextIO, event: str, **payload: Any) -> None:
    """Write and flush one machine-readable event."""
    stream.write(DesktopEvent(event, payload).serialize() + "\n")
    stream.flush()


def parse_command(line: bytes) -> dict[str, Any]:
    """Parse one bounded JSON command from the owned stdin pipe."""
    if len(line) > MAX_LINE_BYTES:
        raise DesktopProtocolError("command_too_large", "Desktop command is too large")
    try:
        value = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DesktopProtocolError(
            "invalid_command", "Invalid desktop command"
        ) from exc
    if not isinstance(value, dict):
        raise DesktopProtocolError(
            "invalid_command", "Desktop command must be an object"
        )
    return value


def validate_admin_url(url: str) -> tuple[str, int]:
    """Validate and return the owned loopback Admin URL authority."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.path not in {"/admin", "/admin/"}
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise DesktopProtocolError("invalid_admin_url", "Invalid desktop Admin URL")
    try:
        port = parsed.port
    except ValueError as exc:
        raise DesktopProtocolError(
            "invalid_admin_url", "Invalid desktop Admin port"
        ) from exc
    if port is None or not 1 <= port <= 65535:
        raise DesktopProtocolError("invalid_admin_url", "Invalid desktop Admin port")
    return "127.0.0.1", port
