"""Helpers for gateway request header forwarding."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any


# Request IDs are correlation metadata, not payloads.  Match the existing Codex
# window-ID envelope while leaving ample room for UUID, ULID, and trace IDs.
MAX_REQUEST_ID_BYTES = 128

_CANONICAL_HEADER_NAMES = {
    "accept": "Accept",
    "accept-encoding": "Accept-Encoding",
    "content-encoding": "Content-Encoding",
    "content-type": "Content-Type",
    "originator": "Originator",
    "session-id": "Session-Id",
    "thread-id": "Thread-Id",
    "x-client-request-id": "x-client-request-id",
    "x-codex-beta-features": "x-codex-beta-features",
    "x-codex-turn-metadata": "x-codex-turn-metadata",
    "x-codex-window-id": "x-codex-window-id",
    "x-oai-attestation": "x-oai-attestation",
    "x-openai-internal-codex-responses-lite": (
        "x-openai-internal-codex-responses-lite"
    ),
    "x-request-id": "x-request-id",
}

_DIRECT_RESPONSES_CREDENTIAL_HEADERS = frozenset(
    {
        "api-key",
        "authorization",
        "cookie",
        "proxy-authorization",
        "x-admin-token",
        "x-api-key",
        "x-goog-api-key",
    }
)
_DIRECT_RESPONSES_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "keep-alive",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_DIRECT_RESPONSES_NETWORK_IDENTITY_HEADERS = frozenset(
    {
        "cf-connecting-ip",
        "forwarded",
        "true-client-ip",
        "via",
        "x-real-ip",
    }
)
_DIRECT_RESPONSES_REBUILT_BODY_HEADERS = frozenset(
    {"content-encoding", "x-oai-attestation"}
)


def generate_request_id() -> str:
    """Return a Gateway-owned visible-ASCII correlation identifier."""

    return str(uuid.uuid4())


def resolve_request_id(value: Any) -> str:
    """Validate an external request ID or generate one when it is absent."""

    if value is None:
        return generate_request_id()
    if (
        not isinstance(value, str)
        or not value
        or any(ord(char) < 0x21 or ord(char) > 0x7E for char in value)
    ):
        raise ValueError("'x-request-id' must be a non-empty visible ASCII string")
    if len(value) > MAX_REQUEST_ID_BYTES:
        raise ValueError(
            f"'x-request-id' must be at most {MAX_REQUEST_ID_BYTES} ASCII bytes"
        )
    return value


def build_upstream_extra_headers(request: Any, request_id: str) -> dict[str, str]:
    """Build the explicit request headers that may be forwarded upstream."""
    extra_headers: dict[str, str] = {}

    if request_id:
        extra_headers["x-request-id"] = request_id

    user_agent = request.headers.get("user-agent")
    if user_agent:
        extra_headers["User-Agent"] = user_agent

    or_version = request.headers.get("openresponses-version")
    if or_version:
        extra_headers["OpenResponses-Version"] = or_version

    return extra_headers


def overlay_headers_case_insensitive(
    headers: dict[str, str], values: Mapping[str, str]
) -> None:
    """Overlay headers while replacing differently-cased existing names."""

    for name, value in values.items():
        output_name = str(name)
        normalized_name = output_name.lower()
        for existing_name in tuple(headers):
            if existing_name.lower() == normalized_name:
                del headers[existing_name]
        headers[output_name] = str(value)


def build_direct_responses_headers(
    headers: Mapping[str, str],
    request_id: str | None,
    *,
    preserve_wire: bool,
) -> dict[str, str]:
    """Sanitize client headers for a direct Responses upstream request.

    Unknown end-to-end headers pass through by default. Credentials,
    hop-by-hop framing, and client network identity are removed. Rebuilt JSON
    additionally drops the original content encoding and opaque attestation.
    """

    normalized: dict[str, tuple[str, str]] = {}
    for name, value in headers.items():
        original_name = str(name)
        normalized_name = original_name.lower()
        normalized[normalized_name] = (
            _CANONICAL_HEADER_NAMES.get(normalized_name, original_name),
            str(value),
        )

    connection_value = normalized.get("connection")
    connection_declared = (
        {
            token.strip().lower()
            for token in connection_value[1].split(",")
            if token.strip()
        }
        if connection_value is not None
        else set()
    )

    result: dict[str, str] = {}
    for normalized_name, (output_name, value) in normalized.items():
        if normalized_name in _DIRECT_RESPONSES_CREDENTIAL_HEADERS:
            continue
        if normalized_name in _DIRECT_RESPONSES_HOP_BY_HOP_HEADERS:
            continue
        if normalized_name in connection_declared:
            continue
        if normalized_name in _DIRECT_RESPONSES_NETWORK_IDENTITY_HEADERS:
            continue
        if normalized_name.startswith("x-forwarded-"):
            continue
        if normalized_name == "accept-encoding":
            continue
        if not preserve_wire and (
            normalized_name in _DIRECT_RESPONSES_REBUILT_BODY_HEADERS
            or normalized_name == "content-type"
            or normalized_name == "x-request-id"
        ):
            continue
        result[output_name] = value

    if not preserve_wire:
        result["Accept-Encoding"] = "identity"
        result["Content-Type"] = "application/json"
        if request_id:
            result["x-request-id"] = request_id
    return result


def build_codex_wire_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Build safe direct-Responses headers for an unchanged client wire body."""

    return build_direct_responses_headers(headers, None, preserve_wire=True)
