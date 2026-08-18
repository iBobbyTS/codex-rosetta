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
from codex_rosetta.gateway.admin.account_store import AccountStore
from codex_rosetta.gateway.admin.chatgpt_oauth import PendingOAuth
from codex_rosetta.gateway.admin.routes.accounts import get_accounts
import codex_rosetta.gateway.admin.chatgpt_oauth as chatgpt_oauth
from codex_rosetta.gateway.admin.chatgpt_oauth import (
    CALLBACK_PATH,
    METADATA_ENDPOINT,
    _authorization_url,
    _metadata_from_claims,
    _metadata_request,
    start_chatgpt_login,
)
from codex_rosetta.gateway.admin.sub2api import parse_sub2api_credentials
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
        assert timeout == 15
        return FakeResponse()

    monkeypatch.setattr(chatgpt_oauth.urllib.request, "urlopen", fake_urlopen)
    assert _metadata_request("access-token", "target-account") == {
        "name": "Acme Workspace",
        "email": "alice@example.com",
        "workspace": "team",
        "subscription_type": "plus",
        "workspace_key": "",
    }
    assert fixture["accounts"][1]["account"]["structure"] == "team"


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
    assert metadata == {"email": "Owner@Example.test"}
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
        {"id": row["id"], "provider": "sub2api", "email": "owner@example.test"}
    ]
    assert store.delete(row["id"])
    assert store.list_public() == []
    assert not store.delete(row["id"])
