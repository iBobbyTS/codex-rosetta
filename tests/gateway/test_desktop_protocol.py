"""Tests for the versioned desktop sidecar protocol."""

from __future__ import annotations

import io
import json

import pytest

from codex_rosetta.gateway.desktop_protocol import (
    EVENT_PREFIX,
    MAX_LINE_BYTES,
    DesktopEvent,
    DesktopProtocolError,
    emit_event,
    parse_command,
    validate_admin_url,
)


def test_event_is_one_versioned_json_line() -> None:
    stream = io.StringIO()

    emit_event(stream, "ready", port=8765)

    line = stream.getvalue()
    assert line.startswith(EVENT_PREFIX)
    assert line.endswith("\n")
    assert json.loads(line.removeprefix(EVENT_PREFIX)) == {
        "protocol": 1,
        "event": "ready",
        "port": 8765,
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8765/admin",
        "http://localhost:8765/admin",
        "http://127.0.0.1:8765/",
        "http://127.0.0.1:8765/admin?next=evil",
        "http://user@127.0.0.1:8765/admin",
        "http://127.0.0.1:0/admin",
    ],
)
def test_admin_url_rejects_unowned_targets(url: str) -> None:
    with pytest.raises(DesktopProtocolError):
        validate_admin_url(url)


def test_admin_url_accepts_exact_loopback_admin_target() -> None:
    assert validate_admin_url("http://127.0.0.1:8765/admin") == (
        "127.0.0.1",
        8765,
    )


def test_command_parser_is_bounded_and_requires_object() -> None:
    assert parse_command(b'{"command":"shutdown"}\n') == {"command": "shutdown"}
    with pytest.raises(DesktopProtocolError, match="must be an object"):
        parse_command(b"[]")
    with pytest.raises(DesktopProtocolError, match="too large"):
        parse_command(b"x" * (MAX_LINE_BYTES + 1))


def test_event_serializer_rejects_oversized_payload() -> None:
    with pytest.raises(DesktopProtocolError, match="too large"):
        DesktopEvent("error", {"message": "x" * MAX_LINE_BYTES}).serialize()
