"""Focused Admin Codex Cockpit health route tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from codex_rosetta._vendor.httpserver import Request
from codex_rosetta._vendor.httpclient import CaseInsensitiveDict, StreamingResponse
from codex_rosetta.gateway.admin.routes.accounts import get_codex_cockpit_health
from codex_rosetta.gateway.app import create_app
from codex_rosetta.gateway.config import GatewayConfig


class _Response(StreamingResponse):
    __slots__ = ("_body",)

    def __init__(self, status_code: int, body: dict[str, Any]):
        self.status_code = status_code
        self.headers: CaseInsensitiveDict = CaseInsensitiveDict(
            {"content-type": "application/json"}
        )
        self.url = "https://cockpit.example/v1/health"
        self._body = body
        self._closed = False
        self._encoding = "utf-8"
        self._decompressor = None
        self._sync_resp = None
        self._sync_conn = None
        stream_reader: asyncio.StreamReader | None = None
        self._async_reader = stream_reader
        self._async_writer = None
        self._async_timeout = None
        self._is_chunked = False
        self._content_length = None
        self._bytes_remaining = None

    async def aiter_bytes(self, chunk_size: int = 4096):
        del chunk_size
        yield json.dumps(self._body).encode()

    async def aclose(self) -> None:
        self._closed = True


class _Client:
    def __init__(self, response: _Response):
        self.response = response
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.calls.append((method, url, dict(kwargs.get("headers", {}))))
        return self.response


class _Pool:
    def __init__(self, client: _Client):
        self.client = client

    def get(self, *_args: Any, **_kwargs: Any) -> _Client:
        return self.client


def _app(tmp_path: Path) -> Any:
    config = {
        "providers": {
            "cockpit": {
                "provider": "openai",
                "openai_variant": "codex_cockpit",
                "api_type": "responses",
                "base_urls": ["https://configured.example/v1"],
                "current_base_url": "https://configured.example/v1",
                "api_keys": [
                    {
                        "uuid": "0e1640a8-6acb-5f92-b9a7-56d7f2093d3b",
                        "id": "primary",
                        "key": "runtime-key",
                    }
                ],
                "current_api_key": "primary",
                "auto_rotate_credentials": True,
                "request_encoding": "identity",
            }
        },
        "model_groups": {},
        "server": {
            "admin_password": "secret",
            "api_keys": [{"id": "client", "key": "client-key"}],
        },
    }
    path = tmp_path / "config.jsonc"
    path.write_text(json.dumps(config), encoding="utf-8")
    return create_app(GatewayConfig(config), config_path=str(path))


def _request(app: Any, body: dict[str, Any], name: str = "cockpit") -> Request:
    request = Request(
        method="POST",
        path=f"/admin/api/config/providers/{name}/codex-cockpit-health",
        query_string="",
        headers={"content-type": "application/json"},
        body=json.dumps(body).encode(),
        client_addr=("127.0.0.1", 1),
        app=app,
    )
    request.path_params = {"name": name}
    return request


def test_route_probes_draft_url_and_key_and_updates_routing_state(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    client = _Client(_Response(200, {"available_accounts": 1, "all_accounts": 2}))
    app.transport._pool = _Pool(client)

    response = asyncio.run(
        get_codex_cockpit_health(
            _request(
                app,
                {"base_url": "https://draft.example/v1", "bearer_key": "draft-key"},
            )
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "available_accounts": 1,
        "all_accounts": 2,
        "available": True,
    }
    assert client.calls == [
        (
            "GET",
            "https://draft.example/v1/health",
            {
                "Authorization": "Bearer draft-key",
                "Accept-Encoding": "identity",
            },
        )
    ]
    assert app.gateway_config.codex_cockpit_health_exclusion_detail("cockpit") is None
    runtime_provider = app.gateway_config.providers["cockpit"]
    assert runtime_provider.base_url == "https://configured.example/v1"
    assert runtime_provider.current_credential_id == "primary"


def test_route_accepts_cockpit_draft_variant_without_mutating_runtime(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    runtime_provider = app.gateway_config.providers["cockpit"]
    runtime_provider.provider_variant = "custom"
    client = _Client(_Response(200, {"available_accounts": 2, "all_accounts": 3}))
    app.transport._pool = _Pool(client)

    response = asyncio.run(
        get_codex_cockpit_health(
            _request(
                app,
                {
                    "openai_variant": "codex_cockpit",
                    "base_url": "https://draft.example/v1",
                    "bearer_key": "draft-key",
                },
            )
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body)["available"] is True
    assert runtime_provider.provider_variant == "custom"
    assert app.gateway_config.providers["cockpit"].provider_variant == "custom"


def test_route_rejects_non_cockpit_draft_variant(tmp_path: Path) -> None:
    app = _app(tmp_path)
    response = asyncio.run(
        get_codex_cockpit_health(
            _request(
                app,
                {
                    "openai_variant": "custom",
                    "base_url": "https://draft.example/v1",
                    "bearer_key": "k",
                },
            )
        )
    )
    assert response.status_code == 400
    assert "not a Codex Cockpit provider" in json.loads(response.body)["error"]


def test_route_returns_502_with_retained_counts_on_probe_failure(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    client = _Client(_Response(200, {"available_accounts": 1, "all_accounts": 1}))
    app.transport._pool = _Pool(client)
    asyncio.run(
        get_codex_cockpit_health(
            _request(app, {"base_url": "https://draft.example/v1", "bearer_key": "k"})
        )
    )
    client.response = _Response(503, {})
    response = asyncio.run(
        get_codex_cockpit_health(
            _request(app, {"base_url": "https://draft.example/v1", "bearer_key": "k"})
        )
    )
    assert response.status_code == 502
    payload = json.loads(response.body)
    assert payload["available_accounts"] == 1
    assert payload["all_accounts"] == 1
    assert payload["available"] is False
    assert "error" in payload
    assert app.gateway_config.codex_cockpit_health_exclusion_detail("cockpit")


def test_route_rejects_wrong_variant_and_invalid_input(tmp_path: Path) -> None:
    app = _app(tmp_path)
    response = asyncio.run(
        get_codex_cockpit_health(
            _request(app, {"base_url": "not-a-url", "bearer_key": "k"})
        )
    )
    assert response.status_code == 400
    app.gateway_config.providers["cockpit"].provider_variant = "custom"
    response = asyncio.run(
        get_codex_cockpit_health(
            _request(app, {"base_url": "https://draft.example", "bearer_key": "k"})
        )
    )
    assert response.status_code == 400


def test_registered_route_requires_admin_auth(tmp_path: Path) -> None:
    app = _app(tmp_path)
    request = _request(app, {"base_url": "https://draft.example", "bearer_key": "k"})
    response = asyncio.run(app._dispatch(request))
    assert response.status_code == 401
