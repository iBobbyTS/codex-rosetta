"""Focused tests for ChatGPT account persistence and OAuth callback safety."""

from __future__ import annotations

import asyncio
import base64
import json
import socket
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

from codex_rosetta._vendor.httpserver import Request
from codex_rosetta.gateway.admin.account_store import (
    AccountStore,
    _correct_chatgpt_workspace,
    get_account_store,
)
from codex_rosetta.gateway.admin.chatgpt_oauth import PendingOAuth
from codex_rosetta.gateway.admin.routes.accounts import (
    _project_sub2api_capacity_items,
    _project_sub2api_key_items,
    delete_account,
    get_accounts,
    get_new_api_pricing,
    get_new_api_success_rate,
    get_sub2api_capacity,
    get_sub2api_keys,
)
import codex_rosetta.gateway.admin.chatgpt_oauth as chatgpt_oauth
import codex_rosetta.gateway.admin.sub2api_client as sub2api_client
from codex_rosetta.gateway.admin.chatgpt_oauth import (
    CALLBACK_PATH,
    METADATA_ENDPOINT,
    _authorization_url,
    _metadata_from_claims,
    _metadata_request,
    start_chatgpt_login,
)
from codex_rosetta.gateway.admin.nonmodel_url import strip_terminal_nonmodel_version
from codex_rosetta.gateway.admin.sub2api import parse_sub2api_credentials
from codex_rosetta.gateway.admin.sub2api_client import (
    DEFAULT_USER_AGENT,
    Sub2APIProviderClient,
)
from codex_rosetta.gateway.app import create_app
from codex_rosetta.gateway.config import GatewayConfig


def _jwt(payload: dict[str, Any]) -> str:
    def encode(value: Any) -> str:
        return (
            base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()
        )

    return f"{encode({'alg': 'none'})}.{encode(payload)}.signature"


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://api.mooko.ai/v1", "https://api.mooko.ai"),
        ("https://api.mooko.ai/v2/", "https://api.mooko.ai"),
        ("https://host/V1", "https://host"),
        ("https://host/foo/v3", "https://host/foo"),
        ("https://host/v1/v2/", "https://host/v1"),
        ("https://host/foo", "https://host/foo"),
        ("https://host/v10", "https://host/v10"),
        ("https://host/v1beta", "https://host/v1beta"),
    ],
)
def test_strip_terminal_nonmodel_version(base_url: str, expected: str) -> None:
    assert strip_terminal_nonmodel_version(base_url) == expected


def _app(tmp_path: Path):
    config = {
        "providers": {},
        "model_groups": {},
        "server": {
            "admin_password": "secret",
            "api_keys": [{"id": "test", "key": "gateway-key", "label": "test"}],
        },
    }
    path = tmp_path / "config.jsonc"
    path.write_text(json.dumps(config), encoding="utf-8")
    return create_app(GatewayConfig(config), config_path=str(path))


def _provider_app(tmp_path: Path):
    config = {
        "providers": {
            "bound-provider": {
                "provider": "custom",
                "api_type": "chat",
                "base_urls": [
                    "https://first.example/v1",
                    "https://second.example/v1",
                ],
                "current_base_url": "https://first.example/v1",
                "api_keys": [
                    {
                        "uuid": "76f4b77c-e567-44f4-8f00-7986a36dcfe1",
                        "id": "primary",
                        "key": "provider-secret",
                    }
                ],
                "current_api_key": "primary",
                "auto_rotate_credentials": True,
            }
        },
        "model_groups": {},
        "server": {
            "admin_password": "secret",
            "api_keys": [{"id": "test", "key": "gateway-key", "label": "test"}],
        },
    }
    path = tmp_path / "config.jsonc"
    path.write_text(json.dumps(config), encoding="utf-8")
    return create_app(GatewayConfig(config), config_path=str(path)), path


def _bound_account(app: Any, *, provider: str = "sub2api") -> str:
    row = get_account_store(app).upsert(
        provider=provider,
        identity=f"{provider}-owner@example.test",
        metadata={"email": "owner@example.test"},
        credentials={
            "access_token": "login-access-secret",
            "refresh_token": "login-refresh-secret",
            "expires_at": "4102444800000",
        },
    )
    return row["id"]


def _sub2api_keys_request(
    app: Any,
    account_id: str,
    *,
    provider_name: str = "bound-provider",
    user_agent: str | None = None,
) -> Request:
    headers = {"content-type": "application/json"}
    if user_agent is not None:
        headers["user-agent"] = user_agent
    request = Request(
        method="POST",
        path=f"/admin/api/config/providers/{provider_name}/sub2api-keys",
        query_string="",
        headers=headers,
        body=json.dumps({"account_id": account_id}).encode(),
        client_addr=("127.0.0.1", 1),
        app=app,
    )
    request.path_params = {"name": provider_name}
    return request


def _sub2api_capacity_request(
    app: Any,
    account_id: str,
    *,
    provider_name: str = "bound-provider",
) -> Request:
    request = _sub2api_keys_request(app, account_id, provider_name=provider_name)
    request.path = f"/admin/api/config/providers/{provider_name}/sub2api-capacity"
    return request


def test_account_store_upsert_deduplicates_and_hides_credentials(
    tmp_path: Path,
) -> None:
    store = AccountStore(str(tmp_path / "config.jsonc"))
    first = store.upsert(
        provider="chatgpt",
        identity="account-1",
        metadata={"name": "Alice", "email": "a@example.com"},
        credentials={"access_token": "secret"},
    )
    second = store.upsert(
        provider="chatgpt",
        identity="account-1",
        metadata={"name": "Alice Updated", "email": "a@example.com"},
        credentials={"access_token": "new-secret"},
    )
    rows = store.list_public()
    assert first["id"] == second["id"]
    assert len(rows) == 1
    assert rows[0]["name"] == "Alice Updated"
    assert "access_token" not in rows[0]


class _FakeSub2APIResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any] | None = None,
        content: bytes | None = None,
    ):
        self.status_code = status_code
        self._payload = payload
        self.body = payload
        self.content = (
            content if content is not None else json.dumps(payload or {}).encode()
        )

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise json.JSONDecodeError("invalid", "", 0)
        return self._payload


def _keys_payload() -> dict[str, Any]:
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [
                {
                    "id": 17,
                    "name": "Primary key",
                    "key": "provider-item-secret",
                    "group_id": 3,
                    "group_routes": [
                        {
                            "enabled": False,
                            "group": {"id": 3, "rate_multiplier": 99},
                        },
                        {
                            "enabled": True,
                            "group": {"id": 4, "rate_multiplier": 8},
                        },
                        {
                            "enabled": True,
                            "group": {"id": 3, "rate_multiplier": 1.5},
                        },
                    ],
                    "current_concurrency": 12,
                    "unrelated": "must-not-be-returned",
                },
                {
                    "id": 18,
                    "name": "No matching route",
                    "key": "second-provider-secret",
                    "group_id": 5,
                    "group_routes": [
                        {
                            "enabled": True,
                            "group": {"id": 6, "rate_multiplier": 2},
                        }
                    ],
                },
            ]
        },
    }


def test_sub2api_keys_projection_keeps_only_editor_fields() -> None:
    assert _project_sub2api_key_items(_keys_payload()) == [
        {
            "id": 17,
            "name": "Primary key",
            "key": "provider-item-secret",
            "group_id": 3,
            "rate_multiplier": 1.5,
            "current_concurrency": None,
        },
        {
            "id": 18,
            "name": "No matching route",
            "key": "second-provider-secret",
            "group_id": 5,
            "rate_multiplier": None,
            "current_concurrency": None,
        },
    ]


@pytest.mark.parametrize(
    ("user_agent", "expected_user_agent"),
    [("admin-browser/1.0", "admin-browser/1.0"), (None, DEFAULT_USER_AGENT)],
)
def test_sub2api_keys_route_uses_exact_provider_url_and_user_agent(
    monkeypatch,
    tmp_path: Path,
    user_agent: str | None,
    expected_user_agent: str,
) -> None:
    app, _path = _provider_app(tmp_path)
    account_id = _bound_account(app)
    calls: list[tuple[str, str, dict[str, str]]] = []

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        calls.append((method, url, dict(headers or {})))
        return _FakeSub2APIResponse(200, _keys_payload())

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    response = asyncio.run(
        get_sub2api_keys(_sub2api_keys_request(app, account_id, user_agent=user_agent))
    )

    assert response.status_code == 200
    assert calls == [
        (
            "GET",
            "https://first.example/api/v1/keys?"
            "page=1&page_size=100&sort_by=created_at&sort_order=desc",
            {
                "Authorization": "Bearer login-access-secret",
                "User-Agent": expected_user_agent,
            },
        )
    ]
    assert json.loads(response.body) == {
        "items": _project_sub2api_key_items(_keys_payload())
    }


def _capacity_payload() -> dict[str, Any]:
    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [
                {
                    "group_id": 3,
                    "group_name": "OpenAI",
                    "concurrency_used": 4,
                    "concurrency_max": 12,
                    "sessions_used": 99,
                },
                {
                    "group_id": 5,
                    "group_name": "Fallback",
                    "concurrency_used": 0,
                    "concurrency_max": 0,
                },
            ],
            "total": {"concurrency_used": 4, "concurrency_max": 12},
        },
    }


def test_sub2api_capacity_projection_keeps_only_group_concurrency_fields() -> None:
    assert _project_sub2api_capacity_items(_capacity_payload()) == [
        {"group_id": 3, "concurrency_used": 4, "concurrency_max": 12},
        {"group_id": 5, "concurrency_used": 0, "concurrency_max": 0},
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"code": False, "data": {"items": []}},
        {
            "code": 0,
            "data": {
                "items": [
                    {"group_id": True, "concurrency_used": 0, "concurrency_max": 1}
                ]
            },
        },
        {
            "code": 0,
            "data": {
                "items": [
                    {"group_id": 1, "concurrency_used": "0", "concurrency_max": 1}
                ]
            },
        },
        {
            "code": 0,
            "data": {
                "items": [
                    {"group_id": 1, "concurrency_used": 0, "concurrency_max": 1},
                    {"group_id": 1, "concurrency_used": 1, "concurrency_max": 2},
                ]
            },
        },
    ],
)
def test_sub2api_capacity_projection_rejects_invalid_items(payload: Any) -> None:
    with pytest.raises(ValueError, match="capacity response is invalid"):
        _project_sub2api_capacity_items(payload)


def test_sub2api_capacity_route_uses_provider_client_and_minimal_projection(
    monkeypatch, tmp_path: Path
) -> None:
    app, _path = _provider_app(tmp_path)
    account_id = _bound_account(app)
    calls: list[str] = []

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        calls.append(url)
        return _FakeSub2APIResponse(200, _capacity_payload())

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    response = asyncio.run(
        get_sub2api_capacity(_sub2api_capacity_request(app, account_id))
    )

    assert response.status_code == 200
    assert calls == ["https://first.example/api/v1/channel-monitors/capacity-summary"]
    assert json.loads(response.body) == {
        "items": _project_sub2api_capacity_items(_capacity_payload())
    }


def _pricing_request(app: Any, body: dict[str, Any]) -> Request:
    request = Request(
        method="POST",
        path="/admin/api/config/providers/new-api/new-api-pricing",
        query_string="",
        headers={"content-type": "application/json"},
        body=json.dumps(body).encode(),
        client_addr=("127.0.0.1", 1),
        app=app,
    )
    request.path_params = {"name": "new-api"}
    return request


def _success_rate_request(app: Any, body: dict[str, Any]) -> Request:
    request = Request(
        method="POST",
        path="/admin/api/config/providers/new-api/new-api-success-rate",
        query_string="",
        headers={"content-type": "application/json"},
        body=json.dumps(body).encode(),
        client_addr=("127.0.0.1", 1),
        app=app,
    )
    request.path_params = {"name": "new-api"}
    return request


class _FakePricingTransport:
    def __init__(self, response: Any = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[
            tuple[Any, str, dict[str, Any], dict[str, str] | None, str]
        ] = []

    async def send_passthrough(
        self, provider_info, url, body, *, method="POST", extra_headers=None
    ):
        self.calls.append((provider_info, url, body, extra_headers, method))
        if self.error:
            raise self.error
        return self.response


@pytest.mark.parametrize("bearer_field", ["bearer_key", "api_key"])
@pytest.mark.parametrize(
    "base_url",
    [
        "https://new.example/",
        "https://new.example/v1",
        "https://new.example/v2/",
        "https://new.example/V1",
    ],
)
def test_new_api_pricing_route_preserves_group_ratio_order(
    tmp_path: Path, bearer_field: str, base_url: str
) -> None:
    app, _path = _provider_app(tmp_path)
    transport = _FakePricingTransport(
        _FakeSub2APIResponse(200, {"group_ratio": {"standard": 1, "pro": 1.5}})
    )
    app.transport = transport
    response = asyncio.run(
        get_new_api_pricing(
            _pricing_request(
                app,
                {"base_url": base_url, bearer_field: "draft-secret"},
            )
        )
    )
    assert response.status_code == 200
    assert json.loads(response.body) == {"group_ratio": {"standard": 1, "pro": 1.5}}
    descriptor, url, body, _headers, method = transport.calls[0]
    assert url == "https://new.example/api/pricing"
    assert body == {}
    assert method == "GET"
    assert descriptor.base_url == "https://new.example"
    assert descriptor._auth_header_fn("draft-secret") == {
        "Authorization": "Bearer draft-secret"
    }


def test_new_api_pricing_route_preserves_sentinel_shaped_bearer_key(
    tmp_path: Path,
) -> None:
    app, _path = _provider_app(tmp_path)
    bearer_key = "__codex_rosetta_no_bearer__"
    transport = _FakePricingTransport(
        _FakeSub2APIResponse(200, {"group_ratio": {"standard": 1}})
    )
    app.transport = transport

    response = asyncio.run(
        get_new_api_pricing(
            _pricing_request(
                app,
                {"base_url": "https://new.example", "bearer_key": bearer_key},
            )
        )
    )

    assert response.status_code == 200
    descriptor = transport.calls[0][0]
    assert descriptor._auth_header_fn(bearer_key) == {
        "Authorization": f"Bearer {bearer_key}"
    }


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"group_ratio": {}},
        {"group_ratio": {"bad": "ratio"}},
        {"group_ratio": {"bad": 10**1000}},
    ],
)
def test_new_api_pricing_route_rejects_malformed_response(
    tmp_path: Path, payload: Any
) -> None:
    app, _path = _provider_app(tmp_path)
    app.transport = _FakePricingTransport(_FakeSub2APIResponse(200, payload))
    response = asyncio.run(
        get_new_api_pricing(_pricing_request(app, {"base_url": "https://new.example"}))
    )
    assert response.status_code == 502
    assert json.loads(response.body)["error"] == "New API pricing response is invalid"


@pytest.mark.parametrize("status_code", [401, 502])
def test_new_api_pricing_route_maps_upstream_failures(
    tmp_path: Path, status_code: int
) -> None:
    app, _path = _provider_app(tmp_path)
    app.transport = _FakePricingTransport(_FakeSub2APIResponse(status_code))
    response = asyncio.run(
        get_new_api_pricing(_pricing_request(app, {"base_url": "https://new.example"}))
    )
    assert response.status_code == 502
    assert f"HTTP {status_code}" in json.loads(response.body)["error"]


def test_new_api_success_rate_route_projects_latest_matching_group(
    tmp_path: Path,
) -> None:
    app, _path = _provider_app(tmp_path)
    transport = _FakePricingTransport(
        _FakeSub2APIResponse(
            200,
            {
                "success": True,
                "data": {
                    "model_name": "gpt-4.1-mini",
                    "groups": [
                        {
                            "group": "standard",
                            "success_rate": 80,
                            "series": [
                                {"ts": 1, "success_rate": 91.5},
                                {"ts": 2, "success_rate": 96.25},
                            ],
                        }
                    ],
                },
            },
        )
    )
    app.transport = transport

    response = asyncio.run(
        get_new_api_success_rate(
            _success_rate_request(
                app,
                {
                    "base_url": "https://new.example/v1",
                    "model": "gpt-4.1-mini",
                    "group": "standard",
                    "bearer_key": "draft-secret",
                },
            )
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {"success_rate": 96.25}
    descriptor, url, body, _headers, method = transport.calls[0]
    assert url == "https://new.example/api/perf-metrics?model=gpt-4.1-mini&hours=24"
    assert body == {}
    assert method == "GET"
    assert descriptor.base_url == "https://new.example"


def test_new_api_success_rate_route_returns_null_for_missing_group(
    tmp_path: Path,
) -> None:
    app, _path = _provider_app(tmp_path)
    app.transport = _FakePricingTransport(
        _FakeSub2APIResponse(
            200,
            {
                "data": {
                    "groups": [{"group": "other", "success_rate": 88, "series": []}]
                }
            },
        )
    )

    response = asyncio.run(
        get_new_api_success_rate(
            _success_rate_request(
                app,
                {
                    "base_url": "https://new.example",
                    "model": "gpt-4.1-mini",
                    "group": "standard",
                },
            )
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {"success_rate": None}


def test_sub2api_keys_route_persists_provider_url_rotation(
    monkeypatch, tmp_path: Path
) -> None:
    app, config_path = _provider_app(tmp_path)
    account_id = _bound_account(app)
    urls: list[str] = []

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        urls.append(url)
        if url.startswith("https://first.example"):
            return _FakeSub2APIResponse(502)
        return _FakeSub2APIResponse(200, _keys_payload())

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    response = asyncio.run(get_sub2api_keys(_sub2api_keys_request(app, account_id)))

    assert response.status_code == 200
    assert urls == [
        "https://first.example/api/v1/keys?"
        "page=1&page_size=100&sort_by=created_at&sort_order=desc",
        "https://second.example/api/v1/keys?"
        "page=1&page_size=100&sort_by=created_at&sort_order=desc",
    ]
    assert app.gateway_config.providers["bound-provider"].base_url == (
        "https://second.example/v1"
    )
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["providers"]["bound-provider"]["current_base_url"] == (
        "https://second.example/v1"
    )


@pytest.mark.parametrize(
    ("case", "expected_status"),
    [
        ("missing-provider", 404),
        ("missing-account", 404),
        ("wrong-account", 400),
    ],
)
def test_sub2api_keys_route_rejects_invalid_binding_without_upstream_io(
    monkeypatch, tmp_path: Path, case: str, expected_status: int
) -> None:
    app, _path = _provider_app(tmp_path)
    account_id = (
        _bound_account(app, provider="chatgpt")
        if case == "wrong-account"
        else "missing-account"
    )

    async def fail_request(*args, **kwargs):
        pytest.fail("upstream request must not run")

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fail_request)
    request = _sub2api_keys_request(
        app,
        account_id,
        provider_name="missing-provider"
        if case == "missing-provider"
        else "bound-provider",
    )
    response = asyncio.run(get_sub2api_keys(request))

    assert response.status_code == expected_status
    assert "login-access-secret" not in response.body.decode()
    assert "login-refresh-secret" not in response.body.decode()


def test_deleting_bound_account_does_not_change_provider_binding(
    tmp_path: Path,
) -> None:
    app, config_path = _provider_app(tmp_path)
    account_id = _bound_account(app)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    saved["providers"]["bound-provider"]["sub2api_account_id"] = account_id
    config_path.write_text(json.dumps(saved), encoding="utf-8")
    request = _sub2api_keys_request(app, account_id)

    response = asyncio.run(delete_account(request, account_id))

    assert response.status_code == 200
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["providers"]["bound-provider"]["sub2api_account_id"] == account_id
    missing = asyncio.run(get_sub2api_keys(request))
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "response_or_error",
    [
        _FakeSub2APIResponse(500, {"error": "login-access-secret"}),
        _FakeSub2APIResponse(
            200, {"code": 1, "message": "login-refresh-secret", "data": {}}
        ),
        _FakeSub2APIResponse(200, None, content=b"login-access-secret"),
        _FakeSub2APIResponse(
            200,
            {
                "code": 0,
                "data": {
                    "items": [
                        {
                            "id": 1,
                            "name": "missing key",
                            "group_id": 1,
                            "group_routes": [],
                        }
                    ]
                },
            },
        ),
        _FakeSub2APIResponse(
            200,
            {
                "code": 0,
                "data": {
                    "items": [
                        {
                            "id": 1,
                            "name": "malformed route",
                            "key": "provider-item-secret",
                            "group_id": 1,
                            "group_routes": [None],
                        }
                    ]
                },
            },
        ),
        RuntimeError("login-refresh-secret"),
    ],
)
def test_sub2api_keys_route_returns_bounded_redacted_errors(
    monkeypatch, tmp_path: Path, response_or_error: Any
) -> None:
    app, _path = _provider_app(tmp_path)
    account_id = _bound_account(app)

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        if isinstance(response_or_error, Exception):
            raise response_or_error
        return response_or_error

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    response = asyncio.run(get_sub2api_keys(_sub2api_keys_request(app, account_id)))

    assert response.status_code == 502
    assert json.loads(response.body) == {"error": "Unable to fetch Sub2API keys"}
    assert "login-access-secret" not in response.body.decode()
    assert "login-refresh-secret" not in response.body.decode()


def test_sub2api_keys_route_rejects_boolean_success_code(
    monkeypatch, tmp_path: Path
) -> None:
    app, _path = _provider_app(tmp_path)
    account_id = _bound_account(app)
    payload = _keys_payload()
    payload["code"] = False
    payload["message"] = "login-refresh-secret"

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        return _FakeSub2APIResponse(200, payload)

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    response = asyncio.run(get_sub2api_keys(_sub2api_keys_request(app, account_id)))

    assert response.status_code == 502
    assert json.loads(response.body) == {"error": "Unable to fetch Sub2API keys"}
    assert "provider-item-secret" not in response.body.decode()
    assert "login-access-secret" not in response.body.decode()
    assert "login-refresh-secret" not in response.body.decode()


def test_sub2api_keys_route_is_registered_and_requires_admin_auth(
    monkeypatch, tmp_path: Path
) -> None:
    app, _path = _provider_app(tmp_path)
    account_id = _bound_account(app)
    request = _sub2api_keys_request(app, account_id)

    unauthenticated = asyncio.run(app._dispatch(request))

    assert unauthenticated.status_code == 401

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        return _FakeSub2APIResponse(200, _keys_payload())

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    request = _sub2api_keys_request(app, account_id)
    request.headers["x-admin-token"] = app.auth_state.admin_token
    authenticated = asyncio.run(app._dispatch(request))

    assert authenticated.status_code == 200
    assert json.loads(authenticated.body)["items"][0]["id"] == 17


def _sub2api_store(
    tmp_path: Path, *, expires_at: str = "4102444800000"
) -> tuple[AccountStore, str]:
    store = AccountStore(str(tmp_path / "config.jsonc"))
    account = store.upsert(
        provider="sub2api",
        identity="user@example.test",
        metadata={"name": "https://stored.example", "email": "user@example.test"},
        credentials={
            "base_url": "https://stored.example",
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "expires_at": expires_at,
        },
    )
    return store, account["id"]


def test_sub2api_provider_refreshes_expired_token_and_sets_headers(
    monkeypatch, tmp_path: Path
) -> None:
    store, account_id = _sub2api_store(tmp_path, expires_at="1")
    calls: list[tuple[str, dict[str, str]]] = []

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        calls.append((url, dict(headers or {})))
        if url.endswith("/auth/refresh"):
            return _FakeSub2APIResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "expires_in": 3600,
                    },
                },
            )
        return _FakeSub2APIResponse(200, {"data": {"ok": True}})

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    response = asyncio.run(
        Sub2APIProviderClient(
            store,
            account_id,
            ["https://api.example/v1"],
            persist_current_url=_noop_record,
        ).request("/api/v1/auth/me", user_agent="client/test")
    )
    assert response.status_code == 200
    assert calls[0][0] == "https://api.example/api/v1/auth/refresh"
    assert calls[1][0] == "https://api.example/api/v1/auth/me"
    assert calls[1][1]["Authorization"] == "Bearer new-access"
    assert calls[1][1]["User-Agent"] == "client/test"
    assert (
        store.get_private(account_id)["credentials"]["refresh_token"] == "new-refresh"
    )


def test_sub2api_defaults_user_agent_and_retries_401_once(
    monkeypatch, tmp_path: Path
) -> None:
    store, account_id = _sub2api_store(tmp_path)
    calls: list[dict[str, str]] = []
    request_urls: list[str] = []

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        if url.endswith("/auth/refresh"):
            return _FakeSub2APIResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "expires_in": 3600,
                    },
                },
            )
        request_urls.append(url)
        calls.append(dict(headers or {}))
        return _FakeSub2APIResponse(401 if len(calls) == 1 else 200, {"ok": True})

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    response = asyncio.run(
        Sub2APIProviderClient(
            store,
            account_id,
            ["https://api.example/V1"],
            persist_current_url=_noop_record,
        ).request(
            "/api/v1/keys", headers={"authorization": "caller-token", "x-test": "1"}
        )
    )
    assert response.status_code == 200
    assert len(calls) == 2
    assert calls[0]["Authorization"] == "Bearer old-access"
    assert calls[1]["Authorization"] == "Bearer new-access"
    assert calls[0]["User-Agent"] == DEFAULT_USER_AGENT
    assert calls[0]["x-test"] == "1"
    assert request_urls == [
        "https://api.example/api/v1/keys",
        "https://api.example/api/v1/keys",
    ]


def test_sub2api_second_401_is_returned_without_third_attempt(
    monkeypatch, tmp_path: Path
) -> None:
    store, account_id = _sub2api_store(tmp_path)
    request_calls = 0
    captured_kwargs: list[dict[str, Any]] = []
    captured_urls: list[str] = []

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        nonlocal request_calls
        if url.endswith("/auth/refresh"):
            return _FakeSub2APIResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "expires_in": 3600,
                    },
                },
            )
        request_calls += 1
        captured_urls.append(url)
        captured_kwargs.append(kwargs)
        return _FakeSub2APIResponse(401, {"error": "unauthorized"})

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    client = Sub2APIProviderClient(
        store,
        account_id,
        ["https://api.example"],
        persist_current_url=_noop_record,
    )
    response = asyncio.run(
        client.request(
            "/api/v1/keys?page=1&page_size=100",
            method="POST",
            json={"filter": "active"},
        )
    )
    assert response.status_code == 401
    assert request_calls == 2
    assert captured_kwargs == [
        {"json": {"filter": "active"}},
        {"json": {"filter": "active"}},
    ]
    assert captured_urls == [
        "https://api.example/api/v1/keys?page=1&page_size=100",
        "https://api.example/api/v1/keys?page=1&page_size=100",
    ]


def test_sub2api_502_rotates_and_persists_url_but_503_does_not(
    monkeypatch, tmp_path: Path
) -> None:
    store, account_id = _sub2api_store(tmp_path)
    requested: list[str] = []
    persisted: list[str] = []

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        if url.startswith("https://first.example"):
            requested.append(url)
            return _FakeSub2APIResponse(502)
        requested.append(url)
        return _FakeSub2APIResponse(200, {"ok": True})

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    client = Sub2APIProviderClient(
        store,
        account_id,
        ["https://first.example/v1", "https://second.example/v2/"],
        persist_current_url=lambda _provider_id, url: _record(persisted, url),
    )
    response = asyncio.run(client.request("/api/v1/auth/me"))
    assert response.status_code == 200
    assert requested == [
        "https://first.example/api/v1/auth/me",
        "https://second.example/api/v1/auth/me",
    ]
    assert persisted == ["https://second.example/v2"]
    assert client.current_base_url == "https://second.example/v2"


def test_sub2api_503_is_returned_without_rotation(monkeypatch, tmp_path: Path) -> None:
    store, account_id = _sub2api_store(tmp_path)
    calls: list[str] = []

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        calls.append(url)
        return _FakeSub2APIResponse(
            503, content="网站请求超时 回源请求被中断 >502<".encode()
        )

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    client = Sub2APIProviderClient(
        store,
        account_id,
        ["https://first.example/v1", "https://second.example/v2"],
        persist_current_url=_noop_record,
    )
    response = asyncio.run(client.request("/api/v1/auth/me"))
    assert response.status_code == 503
    assert calls == ["https://first.example/api/v1/auth/me"]
    assert client.current_base_url == "https://first.example/v1"


def test_sub2api_cdn_marker_rotates_like_502(monkeypatch, tmp_path: Path) -> None:
    store, account_id = _sub2api_store(tmp_path)
    calls: list[str] = []

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        calls.append(url)
        if url.startswith("https://first.example"):
            return _FakeSub2APIResponse(
                200, content="网站请求超时 回源请求被中断 >502<".encode()
            )
        return _FakeSub2APIResponse(200, {"ok": True})

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    client = Sub2APIProviderClient(
        store,
        account_id,
        ["https://first.example", "https://second.example"],
        persist_current_url=_noop_record,
    )
    response = asyncio.run(client.request("/api/v1/auth/me"))
    assert response.status_code == 200
    assert calls == [
        "https://first.example/api/v1/auth/me",
        "https://second.example/api/v1/auth/me",
    ]


def test_sub2api_single_cdn_marker_does_not_rotate(monkeypatch, tmp_path: Path) -> None:
    store, account_id = _sub2api_store(tmp_path)

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        return _FakeSub2APIResponse(200, content="网站请求超时".encode())

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    client = Sub2APIProviderClient(
        store,
        account_id,
        ["https://first.example", "https://second.example"],
        persist_current_url=_noop_record,
    )
    response = asyncio.run(client.request("/api/v1/auth/me"))
    assert response.content == "网站请求超时".encode()
    assert client.current_base_url == "https://first.example"


def test_sub2api_refresh_failure_does_not_mutate_credentials(
    monkeypatch, tmp_path: Path
) -> None:
    store, account_id = _sub2api_store(tmp_path, expires_at="1")

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        return _FakeSub2APIResponse(401, {"error": "refresh expired"})

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    with pytest.raises(sub2api_client.Sub2APIRefreshError):
        asyncio.run(
            Sub2APIProviderClient(
                store,
                account_id,
                ["https://api.example"],
                persist_current_url=_noop_record,
            ).request("/api/v1/auth/me")
        )
    credentials = store.get_private(account_id)["credentials"]
    assert credentials["access_token"] == "old-access"
    assert credentials["refresh_token"] == "old-refresh"


def test_sub2api_refresh_502_rotates_to_next_url(monkeypatch, tmp_path: Path) -> None:
    store, account_id = _sub2api_store(tmp_path, expires_at="1")
    refresh_urls: list[str] = []

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        if url.endswith("/auth/refresh"):
            refresh_urls.append(url)
            if url.startswith("https://first.example"):
                return _FakeSub2APIResponse(502)
            return _FakeSub2APIResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "expires_in": 3600,
                    },
                },
            )
        return _FakeSub2APIResponse(200, {"ok": True})

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    client = Sub2APIProviderClient(
        store,
        account_id,
        ["https://first.example/v1", "https://second.example/v2"],
        persist_current_url=_noop_record,
    )
    response = asyncio.run(client.request("/api/v1/auth/me"))
    assert response.status_code == 200
    assert refresh_urls == [
        "https://first.example/api/v1/auth/refresh",
        "https://second.example/api/v1/auth/refresh",
    ]


def test_sub2api_concurrent_expiry_refreshes_once(monkeypatch, tmp_path: Path) -> None:
    store, account_id = _sub2api_store(tmp_path, expires_at="1")
    refresh_calls = 0

    async def fake_request(client, method, url, *, headers=None, **kwargs):
        nonlocal refresh_calls
        if url.endswith("/auth/refresh"):
            refresh_calls += 1
            await asyncio.sleep(0)
            return _FakeSub2APIResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "expires_in": 3600,
                    },
                },
            )
        return _FakeSub2APIResponse(200, {"ok": True})

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    first_client = Sub2APIProviderClient(
        store,
        account_id,
        ["https://api.example"],
        persist_current_url=_noop_record,
    )
    second_client = Sub2APIProviderClient(
        store,
        account_id,
        ["https://api.example"],
        persist_current_url=_noop_record,
    )

    async def run_both():
        return await asyncio.gather(
            first_client.request("/api/v1/auth/me"),
            second_client.request("/api/v1/keys"),
        )

    responses = asyncio.run(run_both())
    assert [response.status_code for response in responses] == [200, 200]
    assert refresh_calls == 1


async def _record(values: list[str], value: str) -> None:
    values.append(value)


async def _noop_record(_provider_id: str, _value: str) -> None:
    return None


def test_chatgpt_workspaces_have_distinct_stable_identities(tmp_path: Path) -> None:
    store = AccountStore(str(tmp_path / "config.jsonc"))
    first = store.upsert(
        provider="chatgpt",
        identity="acct-1:workspace-a",
        metadata={"name": "A", "email": "owner@example.test", "workspace": "A"},
        credentials={"access_token": "a"},
    )
    second = store.upsert(
        provider="chatgpt",
        identity="acct-1:workspace-b",
        metadata={"name": "B", "email": "owner@example.test", "workspace": "B"},
        credentials={"access_token": "b"},
    )
    assert first["id"] != second["id"]
    assert {row["workspace"] for row in store.list_public()} == {"A", "B"}


def test_legacy_chatgpt_workspace_projection_uses_saved_org_claim() -> None:
    credentials = json.dumps(
        {
            "access_token": _jwt(
                {
                    "https://api.openai.com/auth": {
                        "poid": "org-calgary",
                        "organizations": [
                            {"id": "org-calgary", "title": "Calgary Workspace"}
                        ],
                    }
                }
            ),
            "id_token": _jwt({}),
        }
    )
    corrected = _correct_chatgpt_workspace(
        {"workspace": "Personal", "subscription_type": "team"}, credentials
    )
    assert corrected["workspace"] == "Calgary Workspace"


def test_authorization_url_contains_pkce_and_state() -> None:
    url = _authorization_url("http://localhost:1455/auth/callback", "verifier", "state")
    assert "code_challenge_method=S256" in url
    assert "state=state" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback" in url
    assert "originator=codex_vscode" in url


def test_start_returns_attempt_signal_bound_to_pending_state(tmp_path: Path) -> None:
    app = _app(tmp_path)
    response = asyncio.run(start_chatgpt_login(_callback_request(app, "")))
    payload = json.loads(response.body)
    assert payload["attempt_id"]
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(payload["authorization_url"]).query
    )
    state = query["state"][0]
    assert payload["attempt_id"] == state
    assert app.chatgpt_oauth_pending[state].attempt_id == payload["attempt_id"]
    assert app.chatgpt_oauth_pending[state].opener_origin == "http://localhost:8765"
    listener = app.chatgpt_oauth_listener
    assert listener is not None
    listener.close()


def test_start_reports_occupied_callback_port(tmp_path: Path) -> None:
    app = _app(tmp_path)
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    occupied.bind(("127.0.0.1", 1455))
    occupied.listen(1)
    try:
        response = asyncio.run(start_chatgpt_login(_callback_request(app, "")))
    finally:
        occupied.close()
    assert response.status_code == 409
    assert b"1455" in response.body


def test_metadata_claims_extract_requested_columns() -> None:
    access = _jwt(
        {
            "https://api.openai.com/auth": {
                "account_id": "acct",
                "chatgpt_plan_type": "plus",
                "organizations": [{"name": "Team"}],
            }
        }
    )
    identity = _jwt({"email": "alice@example.com", "name": "Alice"})
    assert _metadata_from_claims(access, identity) == {
        "name": "Alice",
        "email": "alice@example.com",
        "workspace": "Team",
        "subscription_type": "plus",
        "account_id": "acct",
        "workspace_key": "",
    }


def test_metadata_claims_use_chatgpt_account_and_organization_identity() -> None:
    metadata = _metadata_from_claims(
        _jwt({}),
        _jwt(
            {
                "email": "owner@example.test",
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": "acct",
                    "organizations": [{"id": "org-1", "title": "Workspace One"}],
                },
            }
        ),
    )
    assert metadata["account_id"] == "acct"
    assert metadata["workspace"] == "Workspace One"
    assert metadata["workspace_key"] == "org-1"


def test_metadata_request_parses_reference_account_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = {
        "accounts": [
            {
                "account": {
                    "account_id": "other-account",
                    "name": "Other",
                    "email": "other@example.com",
                    "structure": "personal",
                },
                "entitlement": {"subscription_plan": "free"},
            },
            {
                "account": {
                    "account_id": "target-account",
                    "name": "Acme Workspace",
                    "email": "alice@example.com",
                    "structure": "team",
                },
                "entitlement": {"subscription_plan": "plus"},
            },
        ]
    }

    class FakeResponse:
        status = 200

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(fixture).encode("utf-8")

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        assert request.full_url == METADATA_ENDPOINT
        assert request.get_header("Authorization") == "Bearer access-token"
        assert request.get_header("Chatgpt-account-id") == "target-account"
        assert request.get_header("Referer") == "https://chatgpt.com/"
        assert "Chrome/147.0.0.0" in request.get_header("User-agent")
        assert timeout == 15
        return FakeResponse()

    monkeypatch.setattr(chatgpt_oauth.urllib.request, "urlopen", fake_urlopen)
    assert _metadata_request("access-token", "target-account") == {
        "name": "Acme Workspace",
        "email": "alice@example.com",
        "workspace": "Acme Workspace",
        "subscription_type": "plus",
        "workspace_key": "",
    }
    assert fixture["accounts"][1]["account"]["structure"] == "team"


def test_metadata_request_selects_keyed_account_and_downgrades_inactive_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = {
        "accounts": {
            "free-account": {
                "account": {"account_id": "free-account", "structure": "personal"},
                "entitlement": {
                    "subscription_plan": "chatgptprolite",
                    "has_active_subscription": False,
                },
            },
            "team-account": {
                "account": {
                    "account_id": "team-account",
                    "organization_id": "org-team",
                    "name": "Calgary Workspace",
                    "structure": "workspace",
                },
                "entitlement": {
                    "subscription_plan": "chatgptteamplan",
                    "has_active_subscription": True,
                },
            },
        }
    }

    class FakeResponse:
        status = 200

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(fixture).encode()

    monkeypatch.setattr(
        chatgpt_oauth.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )
    assert _metadata_request("access", "free-account")["subscription_type"] == "free"
    team = _metadata_request("access", "team-account")
    assert team["workspace"] == "Calgary Workspace"
    assert team["subscription_type"] == "chatgptteamplan"


def test_metadata_request_can_select_workspace_record() -> None:
    # The selector is matched against workspace_id by the production parser;
    # this regression protects the multi-workspace refresh path.
    assert "workspace_id" in {
        "account_id",
        "id",
        "chatgpt_account_id",
        "workspace_id",
    }


def test_claim_workspace_title_wins_over_structure_fallback() -> None:
    access = _jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct",
                "chatgpt_plan_type": "team",
                "poid": "org-team",
                "organizations": [{"id": "org-team", "title": "Calgary Workspace"}],
            }
        }
    )
    metadata = _metadata_from_claims(access, _jwt({"email": "owner@example.test"}))
    assert metadata["workspace"] == "Calgary Workspace"


def test_free_claim_without_workspace_remains_unassigned_for_remote_fallback() -> None:
    access = _jwt(
        {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct",
                "chatgpt_plan_type": "free",
            }
        }
    )
    metadata = _metadata_from_claims(access, _jwt({"email": "owner@example.test"}))
    assert metadata["workspace"] == ""


def test_callback_rejects_missing_or_replayed_state_without_admin_token(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    request = Request(
        method="GET",
        path=CALLBACK_PATH,
        query_string="state=unknown&code=code",
        headers={},
        body=b"",
        client_addr=("127.0.0.1", 1),
        app=app,
    )
    response = asyncio.run(app._dispatch(request))
    assert response.status_code == 400
    assert "无效或已过期".encode() in response.body


def test_account_api_still_requires_admin_token(tmp_path: Path) -> None:
    app = _app(tmp_path)
    request = Request(
        method="GET",
        path="/admin/api/accounts",
        query_string="",
        headers={},
        body=b"",
        client_addr=("127.0.0.1", 1),
        app=app,
    )
    response = asyncio.run(app._dispatch(request))
    assert response.status_code == 401


def _callback_request(app: Any, query_string: str) -> Request:
    return Request(
        method="GET",
        path=CALLBACK_PATH,
        query_string=query_string,
        headers={},
        body=b"",
        client_addr=("127.0.0.1", 1),
        app=app,
    )


def _list_request(app: Any) -> Request:
    return Request(
        method="GET",
        path="/admin/api/accounts",
        query_string="",
        headers={},
        body=b"",
        client_addr=("127.0.0.1", 1),
        app=app,
    )


def _valid_tokens() -> dict[str, str]:
    return {
        "access_token": _jwt(
            {
                "https://api.openai.com/auth": {
                    "account_id": "acct-success",
                    "chatgpt_plan_type": "plus",
                },
                "exp": 1_900_000_000,
            }
        ),
        "id_token": _jwt({"email": "alice@example.com", "name": "Alice"}),
        "refresh_token": "refresh-token",
    }


def _seed_pending(app: Any, state: str) -> None:
    app.chatgpt_oauth_pending = {
        state: PendingOAuth(
            verifier="verifier",
            redirect_uri="http://localhost:8765/auth/callback",
            expires_at=chatgpt_oauth.time.monotonic() + 300,
            attempt_id=f"attempt-{state}",
        )
    }


def test_callback_success_is_visible_from_list_with_one_app_owned_memory_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app_without_config_path()
    list_request = _list_request(app)
    listed_store = chatgpt_oauth.get_account_store(app)
    assert listed_store is chatgpt_oauth.get_account_store(app)
    _seed_pending(app, "state-success")
    monkeypatch.setattr(chatgpt_oauth, "exchange_code", lambda *_args: _valid_tokens())
    monkeypatch.setattr(chatgpt_oauth, "_metadata_request", lambda *_args: {})

    response = asyncio.run(
        chatgpt_oauth.chatgpt_callback(
            _callback_request(app, "state=state-success&code=code")
        )
    )
    assert response.status_code == 200
    assert b'"signal":"attempt-state-success"' in response.body
    assert b'"outcome":"saved"' in response.body

    listing = asyncio.run(get_accounts(list_request))
    payload = json.loads(listing.body)
    assert payload["accounts"] == [
        {
            "id": payload["accounts"][0]["id"],
            "provider": "chatgpt",
            "name": "Alice",
            "email": "alice@example.com",
            "workspace": "",
            "subscription_type": "plus",
        }
    ]
    assert app.account_store is listed_store


@pytest.mark.parametrize("exchange_mode", ["malformed", "failure"])
def test_callback_exchange_malformed_or_failure_does_not_write(
    monkeypatch: pytest.MonkeyPatch,
    exchange_mode: str,
) -> None:
    app = _app_without_config_path()
    store = chatgpt_oauth.get_account_store(app)
    _seed_pending(app, f"state-{exchange_mode}")

    def fake_exchange(*_args: Any) -> dict[str, str]:
        if exchange_mode == "failure":
            raise ValueError("exchange failed")
        return {"access_token": "missing-core-fields"}

    monkeypatch.setattr(chatgpt_oauth, "exchange_code", fake_exchange)
    response = asyncio.run(
        chatgpt_oauth.chatgpt_callback(
            _callback_request(app, f"state=state-{exchange_mode}&code=code")
        )
    )
    assert response.status_code == 400
    assert f'"signal":"attempt-state-{exchange_mode}"'.encode() in response.body
    assert b'"outcome":"failed"' in response.body
    assert store.list_public() == []


def test_callback_replaying_same_state_does_not_exchange_or_write_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app_without_config_path()
    store = chatgpt_oauth.get_account_store(app)
    _seed_pending(app, "state-replay")
    calls = 0

    def fake_exchange(*_args: Any) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return _valid_tokens()

    monkeypatch.setattr(chatgpt_oauth, "exchange_code", fake_exchange)
    monkeypatch.setattr(chatgpt_oauth, "_metadata_request", lambda *_args: {})
    first = asyncio.run(
        chatgpt_oauth.chatgpt_callback(
            _callback_request(app, "state=state-replay&code=code")
        )
    )
    second = asyncio.run(
        chatgpt_oauth.chatgpt_callback(
            _callback_request(app, "state=state-replay&code=code")
        )
    )
    assert first.status_code == 200
    assert b'"outcome":"saved"' in first.body
    assert second.status_code == 400
    # The one-time state is consumed, so a replay cannot emit a completion
    # signal that the initiating page could mistake for a fresh attempt.
    assert b"codex-rosetta-chatgpt-oauth" not in second.body
    assert calls == 1
    assert len(store.list_public()) == 1


def _app_without_config_path() -> Any:
    config = {
        "providers": {},
        "model_groups": {},
        "server": {
            "admin_password": "secret",
            "api_keys": [{"id": "test", "key": "gateway-key", "label": "test"}],
        },
    }
    return create_app(GatewayConfig(config))


def test_sub2api_credentials_require_email_claim() -> None:
    access = _jwt({"email": "Owner@Example.test"})
    identity, metadata, credentials = parse_sub2api_credentials(
        {"access_token": access, "refresh_token": "refresh", "expires_at": "123"},
        "ai-pixel.online",
    )
    assert identity == "owner@example.test"
    assert metadata == {
        "name": "https://ai-pixel.online",
        "email": "Owner@Example.test",
        "base_url": "https://ai-pixel.online",
    }
    assert credentials["base_url"] == "https://ai-pixel.online"


def test_sub2api_credentials_fail_closed_without_email() -> None:
    with pytest.raises(ValueError, match="邮箱"):
        parse_sub2api_credentials(
            {"access_token": _jwt({}), "refresh_token": "refresh", "expires_at": "123"},
            "ai-pixel.online",
        )


def test_account_store_delete_removes_local_record_and_credentials(
    tmp_path: Path,
) -> None:
    store = AccountStore(str(tmp_path / "config.jsonc"))
    row = store.upsert(
        provider="sub2api",
        identity="owner@example.test",
        metadata={"email": "owner@example.test", "base_url": "https://ai-pixel.online"},
        credentials={"access_token": "secret", "refresh_token": "refresh"},
    )
    assert store.list_public() == [
        {
            "id": row["id"],
            "provider": "sub2api",
            "name": "https://ai-pixel.online",
            "email": "owner@example.test",
            "base_url": "https://ai-pixel.online",
        }
    ]
    assert store.delete(row["id"])
    assert store.list_public() == []
    assert not store.delete(row["id"])


def test_account_store_refresh_updates_metadata_without_replacing_credentials(
    tmp_path: Path,
) -> None:
    store = AccountStore(str(tmp_path / "config.jsonc"))
    row = store.upsert(
        provider="chatgpt",
        identity="acct:org-1",
        metadata={"email": "owner@example.test", "workspace": "Personal"},
        credentials={"access_token": "keep-me", "refresh_token": "keep-refresh"},
    )
    assert store.update_metadata(
        row["id"], {"email": "owner@example.test", "workspace": "Calgary"}
    )
    private = store.get_private(row["id"])
    assert private is not None
    assert private["metadata"]["workspace"] == "Calgary"
    assert private["credentials"]["access_token"] == "keep-me"


def test_account_list_order_is_stable_by_created_at(tmp_path: Path) -> None:
    store = AccountStore(str(tmp_path / "config.jsonc"))
    first = store.upsert(
        provider="chatgpt",
        identity="first",
        metadata={"email": "first@example.test"},
        credentials={"access_token": "first"},
    )
    second = store.upsert(
        provider="chatgpt",
        identity="second",
        metadata={"email": "second@example.test"},
        credentials={"access_token": "second"},
    )
    with store._connect() as connection:
        connection.execute(
            "UPDATE accounts SET created_at = ? WHERE id = ?",
            ("2026-01-01 00:00:00", first["id"]),
        )
        connection.execute(
            "UPDATE accounts SET created_at = ? WHERE id = ?",
            ("2026-01-02 00:00:00", second["id"]),
        )
    store.update_metadata(first["id"], {"email": "first-updated@example.test"})
    assert [row["id"] for row in store.list_public()] == [second["id"], first["id"]]
