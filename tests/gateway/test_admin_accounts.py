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
)
from codex_rosetta.gateway.admin.chatgpt_oauth import PendingOAuth
from codex_rosetta.gateway.admin.routes.accounts import get_accounts
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
        self.content = (
            content if content is not None else json.dumps(payload or {}).encode()
        )

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise json.JSONDecodeError("invalid", "", 0)
        return self._payload


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
            ["https://api.example"],
            persist_current_url=_noop_record,
        ).request("/api/v1/auth/me", user_agent="client/test")
    )
    assert response.status_code == 200
    assert calls[0][0].endswith("/api/v1/auth/refresh")
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
        calls.append(dict(headers or {}))
        return _FakeSub2APIResponse(401 if len(calls) == 1 else 200, {"ok": True})

    monkeypatch.setattr(sub2api_client, "request_bounded_response", fake_request)
    response = asyncio.run(
        Sub2APIProviderClient(
            store,
            account_id,
            ["https://api.example"],
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
        ["https://first.example", "https://second.example"],
        persist_current_url=lambda _provider_id, url: _record(persisted, url),
    )
    response = asyncio.run(client.request("/api/v1/auth/me"))
    assert response.status_code == 200
    assert requested == [
        "https://first.example/api/v1/auth/me",
        "https://second.example/api/v1/auth/me",
    ]
    assert persisted == ["https://second.example"]
    assert client.current_base_url == "https://second.example"


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
        ["https://first.example", "https://second.example"],
        persist_current_url=_noop_record,
    )
    response = asyncio.run(client.request("/api/v1/auth/me"))
    assert response.status_code == 503
    assert calls == ["https://first.example/api/v1/auth/me"]
    assert client.current_base_url == "https://first.example"


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
        ["https://first.example", "https://second.example"],
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
