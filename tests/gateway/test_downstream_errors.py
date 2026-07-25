"""Error-origin contract tests for Codex-facing HTTP and SSE responses."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from codex_rosetta.auto_detect import ProviderType
from codex_rosetta.gateway.downstream_errors import (
    CodexRosettaBlockedError,
    DownstreamErrorOrigin,
    SSEErrorPrefixer,
    classify_downstream_exception,
    format_downstream_error,
    format_stream_error_event,
    prefix_error_body,
    prefix_error_payload,
    prefix_protocol_error_event,
)
from codex_rosetta.gateway.transport import (
    UpstreamCredentialCollisionError,
    UpstreamNetworkError,
)


class _BlockedFailure(CodexRosettaBlockedError, RuntimeError):
    pass


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (DownstreamErrorOrigin.ROSETTA, "Codex Rosetta: broken"),
        (DownstreamErrorOrigin.BLOCKED, "Codex Rosetta blocked: broken"),
        (DownstreamErrorOrigin.UPSTREAM, "Upstream: broken"),
    ],
)
def test_format_downstream_error_uses_stable_idempotent_prefix(
    origin: DownstreamErrorOrigin, expected: str
) -> None:
    assert format_downstream_error("broken", origin) == expected
    assert format_downstream_error(expected, origin) == expected


def test_format_downstream_error_replaces_a_conflicting_origin_prefix() -> None:
    assert (
        format_downstream_error(
            "Codex Rosetta: Upstream: provider-selected label",
            DownstreamErrorOrigin.UPSTREAM,
        )
        == "Upstream: provider-selected label"
    )


def test_classify_downstream_exception_follows_wrapped_causes() -> None:
    blocked = RuntimeError("wrapped")
    blocked.__cause__ = _BlockedFailure("policy")
    assert classify_downstream_exception(blocked) is DownstreamErrorOrigin.BLOCKED
    assert (
        classify_downstream_exception(UpstreamCredentialCollisionError("secret"))
        is DownstreamErrorOrigin.BLOCKED
    )
    assert (
        classify_downstream_exception(UpstreamNetworkError("offline"))
        is DownstreamErrorOrigin.UPSTREAM
    )
    assert (
        classify_downstream_exception(RuntimeError("local"))
        is DownstreamErrorOrigin.ROSETTA
    )


@pytest.mark.parametrize(
    ("payload", "path"),
    [
        ({"error": {"message": "bad", "code": "quota"}}, ("error", "message")),
        ({"error": "bad"}, ("error",)),
        ({"message": "bad"}, ("message",)),
        ({"detail": {"message": "bad"}}, ("detail", "message")),
        ({"detail": "bad"}, ("detail",)),
    ],
)
def test_prefix_error_payload_only_changes_known_message_leaf(
    payload: dict[str, object], path: tuple[str, ...]
) -> None:
    result = prefix_error_payload(payload, DownstreamErrorOrigin.UPSTREAM)
    value = result
    for key in path:
        value = value[key]
    assert value == "Upstream: bad"
    if isinstance(payload.get("error"), dict):
        expected_error = cast(dict[str, Any], payload["error"])
        actual_error = cast(dict[str, Any], result["error"])
        assert actual_error.get("code") == expected_error.get("code")


def test_prefix_error_payload_does_not_scan_ordinary_strings() -> None:
    payload = {"output": "sk-ordinary-model-text", "code": "provider_code"}
    result = prefix_error_payload(payload, DownstreamErrorOrigin.UPSTREAM)
    assert result["output"] == payload["output"]
    assert result["code"] == payload["code"]
    assert result["error"]["message"].startswith("Upstream: ")


def test_prefix_error_body_wraps_non_json_upstream_text() -> None:
    body = prefix_error_body(b"provider exploded", DownstreamErrorOrigin.UPSTREAM)
    assert json.loads(body) == {"error": {"message": "Upstream: provider exploded"}}


def test_response_incomplete_becomes_prefixed_response_failed() -> None:
    result = prefix_protocol_error_event(
        {
            "type": "response.incomplete",
            "response": {"incomplete_details": {"reason": "max_output_tokens"}},
        },
        DownstreamErrorOrigin.UPSTREAM,
    )
    assert result["type"] == "response.failed"
    assert result["response"]["error"] == {
        "code": "incomplete_response",
        "message": (
            "Upstream: Incomplete response returned, reason: max_output_tokens"
        ),
    }


def test_response_failed_without_message_gets_prefixed_fallback() -> None:
    result = prefix_protocol_error_event(
        {"type": "response.failed", "response": {"status": "failed"}},
        DownstreamErrorOrigin.UPSTREAM,
    )
    assert result["response"]["error"]["message"] == (
        "Upstream: response.failed event received"
    )


def test_sse_error_prefixer_preserves_safe_frames_byte_for_byte() -> None:
    safe = b'event: response.output_text.delta\r\ndata: {"type":"response.output_text.delta","delta":"hello"}\r\n\r\n'
    prefixer = SSEErrorPrefixer(DownstreamErrorOrigin.UPSTREAM)
    output = b"".join(
        prefixer.feed(safe[index : index + 3]) for index in range(0, len(safe), 3)
    )
    assert output + prefixer.finish() == safe


def test_sse_error_prefixer_rewrites_failed_event_across_chunks() -> None:
    frame = (
        b"event: response.failed\n"
        b'data: {"type":"response.failed","response":{"error":'
        b'{"code":"bad","message":"provider failed"}}}\n\n'
    )
    prefixer = SSEErrorPrefixer(DownstreamErrorOrigin.UPSTREAM)
    output = b"".join(prefixer.feed(bytes([value])) for value in frame)
    assert b'"code":"bad"' in output
    assert b'"message":"Upstream: provider failed"' in output
    assert prefixer.finish() == b""


@pytest.mark.parametrize(
    "source_provider",
    ["openai_responses", "openai_chat", "anthropic", "google"],
)
def test_terminal_stream_error_is_protocol_framed(source_provider: str) -> None:
    event = format_stream_error_event(
        cast(ProviderType, source_provider),
        "disconnected",
        DownstreamErrorOrigin.UPSTREAM,
    )
    assert event.endswith(b"\n\n")
    assert b"Upstream: disconnected" in event
