"""Tests for the Gateway client of the optional web-run sidecar."""

from __future__ import annotations

import asyncio

import pytest

import codex_rosetta.gateway.web_run_sidecar as sidecar_module
from codex_rosetta.gateway.transport.http.transport import BoundedHttpResponse
from codex_rosetta.gateway.web_run_sidecar import (
    WebRunSidecarHTTPClient,
    WebRunSidecarInvalidRequest,
)


def test_sidecar_client_sends_scoped_bearer_authenticated_operation(
    monkeypatch,
) -> None:
    captured = {}

    async def fake_request(client, method, url, **kwargs):
        del client
        captured.update(method=method, url=url, **kwargs)
        return BoundedHttpResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            content=b'{"output":"Opened page"}',
        )

    monkeypatch.setattr(sidecar_module, "request_bounded_response", fake_request)
    client = WebRunSidecarHTTPClient("http://web-run:8080", "sidecar-secret", timeout=9)

    output = asyncio.run(
        client.execute(
            session_id="a" * 64,
            operation="open",
            arguments={"ref_id": "https://example.com"},
        )
    )

    assert output == "Opened page"
    assert captured["method"] == "POST"
    assert captured["url"] == "http://web-run:8080/v1/execute"
    assert captured["headers"]["Authorization"] == "Bearer sidecar-secret"
    assert captured["json"] == {
        "session_id": "a" * 64,
        "operation": "open",
        "arguments": {"ref_id": "https://example.com"},
    }
    assert captured["max_success_bytes"] == 1_000_000


def test_sidecar_client_maps_client_errors(monkeypatch) -> None:
    async def fake_request(client, method, url, **kwargs):
        del client, method, url, kwargs
        return BoundedHttpResponse(
            status_code=404,
            headers={"content-type": "application/json"},
            content=b'{"detail":"Unknown page reference"}',
        )

    monkeypatch.setattr(sidecar_module, "request_bounded_response", fake_request)

    with pytest.raises(WebRunSidecarInvalidRequest, match="Unknown page reference"):
        asyncio.run(
            WebRunSidecarHTTPClient("http://web-run:8080", "secret").execute(
                session_id="a" * 64,
                operation="click",
                arguments={"ref_id": "turn0fetch0", "id": 1},
            )
        )
