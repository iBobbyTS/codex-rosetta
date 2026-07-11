"""Admin network diagnostics use the shared bounded auxiliary HTTP path."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

from codex_rosetta.gateway.admin.routes import observability
from codex_rosetta.gateway.transport.http.transport import BoundedHttpResponse


def test_network_diagnostics_uses_bounded_helper_for_both_requests(monkeypatch):
    calls: list[tuple[str, str]] = []

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    async def _fake_bounded(client, method, url, **kwargs):
        calls.append((method, url))
        if "ip-api.com" in url:
            return BoundedHttpResponse(
                status_code=200,
                headers={"content-type": "application/json"},
                content=(
                    b'{"query":"203.0.113.1","country":"CA",'
                    b'"city":"Calgary","isp":"Example"}'
                ),
            )
        return BoundedHttpResponse(status_code=204, headers={}, content=b"")

    monkeypatch.setattr(observability, "AsyncClient", _FakeClient)
    monkeypatch.setattr(observability, "request_bounded_response", _fake_bounded)
    monkeypatch.setattr(
        observability,
        "_detect_host_ip",
        lambda: {"ok": True, "ip": "172.17.0.1"},
    )
    request = SimpleNamespace(
        app=SimpleNamespace(gateway_config=SimpleNamespace(proxy=None))
    )

    response = asyncio.run(observability.network_diagnostics(request))
    body = json.loads(response.body)

    assert calls == [
        ("GET", "http://ip-api.com/json/?fields=query,country,city,isp"),
        ("GET", "https://www.google.com/generate_204"),
    ]
    assert body["ip"] == {
        "ok": True,
        "ip": "203.0.113.1",
        "country": "CA",
        "city": "Calgary",
        "isp": "Example",
    }
    assert body["google"] == {"ok": True, "status": 204}
