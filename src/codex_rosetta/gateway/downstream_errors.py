"""Stable error-origin labels for responses returned by the Gateway.

This module owns the only three model-facing error prefixes.  Callers retain
their provider-specific HTTP or SSE envelopes and delegate only the human
readable message value to this module.
"""

from __future__ import annotations

import copy
import json
from enum import StrEnum
from typing import Any

from codex_rosetta.auto_detect import ProviderType

from .transport._base import UpstreamConnectionError, UpstreamSafetyError


class DownstreamErrorOrigin(StrEnum):
    """Origin visible to a Codex client."""

    ROSETTA = "Codex Rosetta"
    BLOCKED = "Codex Rosetta blocked"
    UPSTREAM = "Upstream"


class CodexRosettaBlockedError:
    """Mixin marking a local policy decision that intentionally blocks work."""


_PREFIXES = tuple(f"{origin.value}: " for origin in DownstreamErrorOrigin)


def classify_downstream_exception(exc: BaseException) -> DownstreamErrorOrigin:
    """Classify a transport or Gateway exception by its user-visible owner."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (CodexRosettaBlockedError, UpstreamSafetyError)):
            return DownstreamErrorOrigin.BLOCKED
        if isinstance(current, UpstreamConnectionError):
            return DownstreamErrorOrigin.UPSTREAM
        current = current.__cause__ or current.__context__
    return DownstreamErrorOrigin.ROSETTA


def format_downstream_error(
    message: object,
    origin: DownstreamErrorOrigin,
) -> str:
    """Prefix one message exactly once with its stable error origin."""
    text = str(message).strip() or "Unknown error"
    # A remote or nested error cannot select a different owner by spoofing one
    # or more of our labels.  Normalize every leading label at this trusted
    # boundary; formatting remains idempotent because the intended one is then
    # applied exactly once.
    while True:
        matched = next(
            (prefix for prefix in _PREFIXES if text.startswith(prefix)), None
        )
        if matched is None:
            break
        text = text.removeprefix(matched).lstrip()
    # Retire the former, less precise connection-error spelling at the single
    # compatibility boundary where it can still arrive from older helpers.
    if origin is DownstreamErrorOrigin.UPSTREAM and text.startswith(
        "Upstream request failed: "
    ):
        text = text.removeprefix("Upstream request failed: ")
    text = text or "Unknown error"
    return f"{origin.value}: {text}"


def prefix_error_payload(
    payload: Any,
    origin: DownstreamErrorOrigin,
    *,
    fallback: str = "HTTP error response did not include a message",
) -> Any:
    """Prefix the known human-readable message leaf in an error payload.

    Provider fields and codes are preserved.  Only documented error-message
    locations are considered; arbitrary response strings are never scanned.
    """
    result = copy.deepcopy(payload)
    if not isinstance(result, dict):
        return {"error": {"message": format_downstream_error(fallback, origin)}}

    error = result.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        error["message"] = format_downstream_error(error["message"], origin)
        return result
    if isinstance(error, str):
        result["error"] = format_downstream_error(error, origin)
        return result
    if isinstance(result.get("message"), str):
        result["message"] = format_downstream_error(result["message"], origin)
        return result
    detail = result.get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        detail["message"] = format_downstream_error(detail["message"], origin)
        return result
    if isinstance(detail, str):
        result["detail"] = format_downstream_error(detail, origin)
        return result

    result["error"] = {"message": format_downstream_error(fallback, origin)}
    return result


def prefix_error_body(
    body: bytes | str,
    origin: DownstreamErrorOrigin,
    *,
    fallback: str = "HTTP error response did not include a message",
) -> bytes:
    """Return a JSON error body whose known message leaf has an origin prefix."""
    raw = body.encode("utf-8") if isinstance(body, str) else body
    try:
        payload = json.loads(raw)
    except UnicodeDecodeError, json.JSONDecodeError:
        text = raw.decode("utf-8", errors="replace").strip()
        payload = {
            "error": {
                "message": format_downstream_error(text or fallback, origin),
            }
        }
    else:
        payload = prefix_error_payload(payload, origin, fallback=fallback)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def prefix_protocol_error_event(
    event: dict[str, Any],
    origin: DownstreamErrorOrigin,
) -> dict[str, Any]:
    """Prefix exact protocol error fields without touching normal model text."""
    result = copy.deepcopy(event)
    event_type = result.get("type")
    if event_type == "response.failed":
        response = result.get("response")
        if not isinstance(response, dict):
            response = {}
            result["response"] = response
        error = response.get("error")
        if not isinstance(error, dict):
            error = {}
            response["error"] = error
        message = error.get("message")
        error["message"] = format_downstream_error(
            message if isinstance(message, str) else "response.failed event received",
            origin,
        )
        return result
    if event_type == "response.incomplete":
        response = result.get("response")
        reason = "unknown"
        if isinstance(response, dict):
            details = response.get("incomplete_details")
            if isinstance(details, dict) and isinstance(details.get("reason"), str):
                reason = details["reason"]
        result["type"] = "response.failed"
        result["response"] = {
            **(response if isinstance(response, dict) else {}),
            "status": "failed",
            "error": {
                "code": "incomplete_response",
                "message": format_downstream_error(
                    f"Incomplete response returned, reason: {reason}", origin
                ),
            },
        }
        return result
    return prefix_error_payload(result, origin)


def format_stream_error_event(
    source_provider: ProviderType,
    message: object,
    origin: DownstreamErrorOrigin,
) -> bytes:
    """Build one protocol-valid terminal SSE error event."""
    formatted = format_downstream_error(message, origin)
    if source_provider in {"openai_responses", "open_responses"}:
        payload = {
            "type": "response.failed",
            "response": {
                "status": "failed",
                "error": {"code": "codex_rosetta_error", "message": formatted},
            },
        }
        return _sse_bytes(payload, event="response.failed")
    if source_provider == "anthropic":
        payload = {
            "type": "error",
            "error": {"type": "api_error", "message": formatted},
        }
        return _sse_bytes(payload, event="error")
    if source_provider == "google":
        return _sse_bytes(
            {"error": {"code": 502, "message": formatted, "status": "UNKNOWN"}}
        )
    return _sse_bytes(
        {"error": {"message": formatted, "type": "api_error", "code": None}}
    )


def _sse_bytes(payload: dict[str, Any], *, event: str | None = None) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    prefix = f"event: {event}\n" if event is not None else ""
    return f"{prefix}data: {data}\n\n".encode()


class SSEErrorPrefixer:
    """Rewrite only complete upstream SSE error events, preserving safe bytes."""

    def __init__(self, origin: DownstreamErrorOrigin) -> None:
        self._origin = origin
        self._pending = bytearray()

    def feed(self, chunk: bytes) -> bytes:
        """Accept arbitrary wire chunks and release every complete SSE frame."""
        self._pending.extend(chunk)
        output = bytearray()
        while True:
            boundary = _next_sse_boundary(self._pending)
            if boundary is None:
                break
            end, separator = boundary
            frame = bytes(self._pending[:end])
            del self._pending[: end + separator]
            output.extend(self._rewrite_frame(frame))
            output.extend(b"\n\n" if separator == 2 else b"\r\n\r\n")
        return bytes(output)

    def finish(self) -> bytes:
        """Release a final unterminated safe fragment without inventing framing."""
        remaining = bytes(self._pending)
        self._pending.clear()
        return self._rewrite_frame(remaining)

    def _rewrite_frame(self, frame: bytes) -> bytes:
        lines = frame.replace(b"\r\n", b"\n").split(b"\n")
        data_lines = [
            line[5:].lstrip(b" ") for line in lines if line.startswith(b"data:")
        ]
        if not data_lines:
            return frame
        try:
            event = json.loads(b"\n".join(data_lines))
        except UnicodeDecodeError, json.JSONDecodeError:
            return frame
        if not isinstance(event, dict) or event.get("type") not in {
            "response.failed",
            "response.incomplete",
        }:
            return frame
        rewritten = prefix_protocol_error_event(event, self._origin)
        event_name = rewritten.get("type")
        kept = [
            line
            for line in lines
            if not line.startswith(b"data:") and not line.startswith(b"event:")
        ]
        prefix = (
            [f"event: {event_name}".encode()] if isinstance(event_name, str) else []
        )
        data = json.dumps(rewritten, ensure_ascii=False, separators=(",", ":")).encode()
        return b"\n".join([*prefix, *kept, b"data: " + data])


def _next_sse_boundary(buffer: bytearray) -> tuple[int, int] | None:
    lf = buffer.find(b"\n\n")
    crlf = buffer.find(b"\r\n\r\n")
    candidates = [(lf, 2), (crlf, 4)]
    valid = [candidate for candidate in candidates if candidate[0] >= 0]
    return min(valid, key=lambda item: item[0]) if valid else None
