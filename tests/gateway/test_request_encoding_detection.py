"""Tests for bounded Responses request-encoding detection."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from codex_rosetta.gateway.admin.request_encoding_detection import (
    detect_responses_request_encoding,
)
from codex_rosetta.gateway.providers import build_provider_info


class _ProbeStream:
    def __init__(
        self,
        *,
        completed: bool = False,
        status_code: int = 200,
        error: str = "",
    ) -> None:
        self.status_code = status_code
        self._events = (
            [{"type": "response.created"}, {"type": "response.completed"}]
            if completed
            else [{"type": "response.created"}]
        )
        self._error = error
        self.closed = False

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    async def read_error(self) -> str:
        return self._error

    def __aiter__(self):
        async def events():
            for event in self._events:
                yield event

        return events()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args: Any) -> None:
        self.closed = True


class _ProbeTransport:
    def __init__(self, outcomes: dict[str, _ProbeStream | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[Any, str, dict[str, Any], str]] = []

    async def send_streaming(self, provider_info, target_provider, body, model, **_):
        self.calls.append((provider_info, target_provider, body, model))
        outcome = self.outcomes[provider_info.request_encoding]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _provider(request_encoding: str):
    return build_provider_info(
        "openai_responses",
        {
            "provider": "openai",
            "api_type": "responses",
            "request_encoding": request_encoding,
            "base_urls": ["https://current.example/v1"],
            "current_base_url": "https://current.example/v1",
            "api_keys": [{"id": "current", "key": "secret"}],
            "current_api_key": "current",
        },
    )


@pytest.mark.parametrize(
    ("identity_ok", "zstd_ok", "selected"),
    [
        (True, True, "passthrough"),
        (True, False, "identity"),
        (False, True, "zstd"),
        (False, False, None),
    ],
)
def test_detection_maps_two_probe_completion_matrix(
    identity_ok: bool,
    zstd_ok: bool,
    selected: str | None,
) -> None:
    transport = _ProbeTransport(
        {
            "identity": _ProbeStream(completed=identity_ok),
            "zstd": _ProbeStream(completed=zstd_ok),
        }
    )

    result = asyncio.run(
        detect_responses_request_encoding(
            transport,
            identity_provider=_provider("identity"),
            zstd_provider=_provider("zstd"),
            model="manual-model",
        )
    )

    assert result.selected == selected
    assert result.identity.ok is identity_ok
    assert result.zstd.ok is zstd_ok
    assert len(transport.calls) == 2
    assert {call[0].request_encoding for call in transport.calls} == {
        "identity",
        "zstd",
    }
    assert all(
        call[1:]
        == (
            "openai_responses",
            {"model": "manual-model", "input": "hi", "stream": True},
            "manual-model",
        )
        for call in transport.calls
    )


def test_detection_preserves_bounded_http_and_transport_errors() -> None:
    transport = _ProbeTransport(
        {
            "identity": _ProbeStream(status_code=400, error='{"error":"invalid JSON"}'),
            "zstd": RuntimeError("TLS handshake failed with details"),
        }
    )

    result = asyncio.run(
        detect_responses_request_encoding(
            transport,
            identity_provider=_provider("identity"),
            zstd_provider=_provider("zstd"),
            model="manual-model",
        )
    )

    assert result.selected is None
    assert result.identity.error == 'HTTP 400: {"error":"invalid JSON"}'
    assert result.zstd.error == "TLS handshake failed with details"
