"""Tests for upstream header forwarding from gateway handlers."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from unittest.mock import MagicMock

import codex_rosetta.gateway.app as app_module
import pytest
from codex_rosetta._vendor.httpserver import JSONResponse, Request, StreamingResponse
from codex_rosetta.auto_detect import ProviderType
from codex_rosetta.gateway.auth import api_key_principal_var
from codex_rosetta.gateway.config import GatewayConfig, _ModelGroupProviderCandidate
from codex_rosetta.gateway.admin.routes.config import reload_config
from codex_rosetta.gateway.headers import (
    MAX_REQUEST_ID_BYTES,
    build_codex_wire_headers,
    build_direct_responses_headers,
    build_upstream_extra_headers,
    resolve_request_id,
)
from codex_rosetta.routing import ResolvedRoute


def _gateway_config(*, admin_cors_origins: list[str] | None = None) -> dict[str, Any]:
    return {
        "providers": {
            "test-provider": {
                "provider": "custom",
                "api_keys": [
                    {
                        "uuid": "0488ffa0-e7b7-59ed-b1d0-6d43275607f5",
                        "id": "primary",
                        "key": "sk-test",
                    }
                ],
                "current_api_key": "primary",
                "auto_rotate_credentials": True,
                "base_urls": ["https://api.example.test/v1"],
                "current_base_url": "https://api.example.test/v1",
                "api_type": "chat",
            }
        },
        "model_groups": {
            "test": {
                "provider": ["test-provider"],
                "type": "llm",
                "models": {"gpt-test": {"upstream_model": "gpt-5.6-terra"}},
            }
        },
        "server": {
            "admin_password": "test-admin-password",
            "api_keys": [
                {
                    "id": "test-client",
                    "label": "Test client",
                    "key": "test-gateway-key",
                }
            ],
            "admin_cors_origins": admin_cors_origins or [],
        },
    }


def _two_provider_gateway_config() -> GatewayConfig:
    raw = _gateway_config()
    raw["providers"]["second-provider"] = {
        **raw["providers"]["test-provider"],
        "base_urls": ["https://second.example.test/v1"],
        "current_base_url": "https://second.example.test/v1",
    }
    raw["model_groups"]["test"]["provider"] = [
        "test-provider",
        "second-provider",
    ]
    return GatewayConfig(raw)


def _proxy_request(config: GatewayConfig, *, stream: bool = False) -> MagicMock:
    request = MagicMock()
    request.headers = {}
    request.json.return_value = {
        "model": "gpt-test",
        "messages": [],
        **({"stream": True} if stream else {}),
    }
    request.app.metadata_store = MagicMock()
    request.app.codex_tool_store = MagicMock()
    request.app.transport = MagicMock()
    request.app.metrics = None
    request.app.request_log = None
    request.app.persistence = None
    request.app.profiler_state = None
    request.app.gateway_config = config
    return request


def _app_request(
    app: Any,
    *,
    method: str,
    path: str,
    headers: dict[str, str],
) -> Request:
    return Request(
        method=method,
        path=path,
        query_string="",
        headers=headers,
        body=b"",
        client_addr=("198.51.100.10", 12345),
        app=app,
    )


def test_create_app_stores_resolved_codex_home(tmp_path):
    codex_home = tmp_path / "codex-home"

    app: Any = app_module.create_app(
        GatewayConfig(_gateway_config()), codex_home=str(codex_home)
    )

    assert app.codex_home == str(codex_home)


@pytest.fixture(autouse=True)
def _authenticated_principal():
    token = api_key_principal_var.set("test-client")
    yield
    api_key_principal_var.reset(token)


def test_build_upstream_extra_headers_preserves_user_agent_and_responses_version():
    """Only explicitly supported client headers should be forwarded upstream."""
    request = MagicMock()
    request.headers = {
        "user-agent": "codex-cli/1.2.3",
        "openresponses-version": "2025-06-18",
        "authorization": "Bearer client-key",
    }

    headers = build_upstream_extra_headers(request, "req-123")

    assert headers == {
        "x-request-id": "req-123",
        "User-Agent": "codex-cli/1.2.3",
        "OpenResponses-Version": "2025-06-18",
    }


def test_build_direct_responses_headers_removes_only_codex_authorization() -> None:
    headers = build_direct_responses_headers(
        {
            "Accept": "text/event-stream",
            "Accept-Encoding": "gzip",
            "AUTHORIZATION": "Bearer gateway-client-key",
            "Proxy-Authorization": "Basic private",
            "x-api-key": "private",
            "api-key": "private",
            "x-goog-api-key": "private",
            "Cookie": "session=private",
            "x-admin-token": "private",
            "Connection": "keep-alive, X-Connection-Private",
            "X-Connection-Private": "drop-me",
            "Keep-Alive": "timeout=5",
            "TE": "trailers",
            "Trailer": "X-Checksum",
            "Transfer-Encoding": "chunked",
            "Upgrade": "websocket",
            "Proxy-Connection": "keep-alive",
            "Host": "gateway.example",
            "Content-Length": "123",
            "Content-Encoding": "zstd",
            "Content-Type": "application/custom+json",
            "Forwarded": "for=192.0.2.1",
            "X-Forwarded-For": "192.0.2.1",
            "Via": "1.1 gateway",
            "CF-Connecting-IP": "192.0.2.1",
            "True-Client-IP": "192.0.2.1",
            "X-Real-IP": "192.0.2.1",
            "Originator": "Codex CLI",
            "Session-Id": "session-1",
            "Thread-Id": "thread-1",
            "x-codex-beta-features": "remote_compaction_v2",
            "x-codex-window-id": "window-1",
            "x-oai-attestation": "opaque-proof",
            "X-Future-Codex-Capability": "preserve-me",
        },
        "req-123",
        preserve_wire=False,
    )

    assert headers == {
        "Accept": "text/event-stream",
        "Proxy-Authorization": "Basic private",
        "x-api-key": "private",
        "api-key": "private",
        "x-goog-api-key": "private",
        "Cookie": "session=private",
        "x-admin-token": "private",
        "Originator": "Codex CLI",
        "Session-Id": "session-1",
        "Thread-Id": "thread-1",
        "x-codex-beta-features": "remote_compaction_v2",
        "x-codex-window-id": "window-1",
        "X-Future-Codex-Capability": "preserve-me",
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
        "x-request-id": "req-123",
    }


def test_build_codex_wire_headers_removes_authorization_and_preserves_wire_contract() -> (
    None
):
    headers = build_codex_wire_headers(
        {
            "accept": "text/event-stream",
            "authorization": "Bearer gateway-client-key",
            "content-encoding": "zstd",
            "content-length": "123",
            "content-type": "application/json",
            "cookie": "session=private",
            "host": "gateway.example",
            "originator": "Codex Desktop",
            "session-id": "session-1",
            "thread-id": "thread-1",
            "x-client-request-id": "request-1",
            "x-codex-beta-features": "remote_compaction_v2",
            "x-codex-turn-metadata": "{}",
            "x-codex-window-id": "window-1",
            "x-oai-attestation": "signed-wire-proof",
            "x-openai-internal-codex-responses-lite": "true",
            "x-unrelated": "preserve-me",
        }
    )

    assert headers == {
        "Accept": "text/event-stream",
        "Content-Encoding": "zstd",
        "Content-Type": "application/json",
        "cookie": "session=private",
        "Originator": "Codex Desktop",
        "Session-Id": "session-1",
        "Thread-Id": "thread-1",
        "x-client-request-id": "request-1",
        "x-codex-beta-features": "remote_compaction_v2",
        "x-codex-turn-metadata": "{}",
        "x-codex-window-id": "window-1",
        "x-oai-attestation": "signed-wire-proof",
        "x-openai-internal-codex-responses-lite": "true",
        "x-unrelated": "preserve-me",
    }


def test_request_id_boundary_accepts_exact_limit_and_generates_missing_id():
    exact = "r" * MAX_REQUEST_ID_BYTES
    generated = resolve_request_id(None)

    assert resolve_request_id(exact) == exact
    assert str(uuid.UUID(generated)) == generated


@pytest.mark.parametrize(
    "request_id",
    ["", " ", "req\x1b[2J", "req\x7f", "请求", "r" * (MAX_REQUEST_ID_BYTES + 1)],
)
def test_request_id_boundary_rejects_unsafe_external_values(request_id: str):
    with pytest.raises(ValueError, match="x-request-id"):
        resolve_request_id(request_id)


@pytest.mark.parametrize("mode", ["normal", "error", "stream"])
@pytest.mark.parametrize(
    "request_id",
    ["req\x1b[2J", "r" * (MAX_REQUEST_ID_BYTES + 1)],
)
def test_invalid_request_id_is_rejected_before_gateway_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    request_id: str,
) -> None:
    gateway_logger = MagicMock()
    stats = MagicMock()
    monkeypatch.setattr(app_module, "logger", gateway_logger)
    monkeypatch.setattr(app_module, "record_request_stat", stats)

    request = MagicMock()
    request.headers = {"x-request-id": request_id}
    request.json.return_value = {
        "model": "gpt-test",
        "messages": [],
        "stream": mode == "stream",
    }
    if mode == "error":
        request.json.side_effect = ValueError("body must remain unread")
    request.app.gateway_config = MagicMock()
    request.app.persistence = MagicMock()
    request.app.stream_trace_state = MagicMock()
    request.app.metadata_store = MagicMock()
    request.app.codex_tool_store = MagicMock()

    response = asyncio.run(app_module._proxy_handler(request, "openai_responses"))

    assert response.status_code == 400
    assert not isinstance(response, StreamingResponse)
    assert request_id not in response.headers.values()
    uuid.UUID(response.headers["x-request-id"])
    request.json.assert_not_called()
    request.app.gateway_config.resolve.assert_not_called()
    assert request.app.persistence.mock_calls == []
    assert request.app.stream_trace_state.mock_calls == []
    assert request.app.metadata_store.mock_calls == []
    assert request.app.codex_tool_store.mock_calls == []
    assert gateway_logger.mock_calls == []
    stats.assert_not_called()


def test_request_log_client_ip_ignores_untrusted_forwarded_headers():
    request = MagicMock()
    request.headers = {
        "x-forwarded-for": "203.0.113.99, 192.0.2.10",
        "x-real-ip": "203.0.113.100",
    }
    request.client_addr = ("198.51.100.10", 12345)

    assert app_module._extract_client_ip(request) == "198.51.100.10"


def test_admin_cors_preflight_and_actual_request_require_correct_boundaries(tmp_path):
    config_data = _gateway_config(admin_cors_origins=["https://admin.example"])
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    app = app_module.create_app(
        GatewayConfig(config_data), config_path=str(config_path)
    )
    try:
        allowed = asyncio.run(
            app._dispatch(
                _app_request(
                    app,
                    method="OPTIONS",
                    path="/admin/api/config",
                    headers={"origin": "https://admin.example"},
                )
            )
        )
        assert allowed.status_code == 204
        assert allowed.headers["Access-Control-Allow-Origin"] == (
            "https://admin.example"
        )

        denied = asyncio.run(
            app._dispatch(
                _app_request(
                    app,
                    method="OPTIONS",
                    path="/admin/api/config",
                    headers={"origin": "https://attacker.example"},
                )
            )
        )
        assert denied.status_code == 403
        assert "Access-Control-Allow-Origin" not in denied.headers

        substring = asyncio.run(
            app._dispatch(
                _app_request(
                    app,
                    method="OPTIONS",
                    path="/admin/api/config",
                    headers={"origin": "https://admin"},
                )
            )
        )
        assert substring.status_code == 403
        assert "Access-Control-Allow-Origin" not in substring.headers

        unauthenticated = asyncio.run(
            app._dispatch(
                _app_request(
                    app,
                    method="GET",
                    path="/admin/api/config",
                    headers={"origin": "https://admin.example"},
                )
            )
        )
        assert unauthenticated.status_code == 401
        assert unauthenticated.headers["Access-Control-Allow-Origin"] == (
            "https://admin.example"
        )
        assert unauthenticated.headers["Vary"] == "Origin"

        denied_actual = asyncio.run(
            app._dispatch(
                _app_request(
                    app,
                    method="GET",
                    path="/admin/api/config",
                    headers={"origin": "https://attacker.example"},
                )
            )
        )
        assert denied_actual.status_code == 401
        assert "Access-Control-Allow-Origin" not in denied_actual.headers

        authenticated = asyncio.run(
            app._dispatch(
                _app_request(
                    app,
                    method="GET",
                    path="/admin/api/config",
                    headers={
                        "origin": "https://admin.example",
                        "x-admin-token": getattr(app, "auth_state").admin_token,
                    },
                )
            )
        )
        assert authenticated.status_code == 200
        assert authenticated.headers["Access-Control-Allow-Origin"] == (
            "https://admin.example"
        )
    finally:
        persistence = getattr(app, "persistence", None)
        if persistence is not None:
            persistence.close()


@pytest.mark.parametrize("path", ["/v1/responses", "/v1/models"])
def test_protected_v1_preflight_reaches_public_cors_route(path: str):
    app = app_module.create_app(GatewayConfig(_gateway_config()))

    response = asyncio.run(
        app._dispatch(
            _app_request(
                app,
                method="OPTIONS",
                path=path,
                headers={
                    "origin": "https://browser.example",
                    "access-control-request-method": "POST",
                    "access-control-request-headers": "authorization",
                },
            )
        )
    )

    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert response.headers["Access-Control-Allow-Headers"] == "*"


def test_protected_v1_auth_failure_remains_browser_readable():
    app = app_module.create_app(GatewayConfig(_gateway_config()))

    response = asyncio.run(
        app._dispatch(
            _app_request(
                app,
                method="POST",
                path="/v1/responses",
                headers={
                    "origin": "https://browser.example",
                    "authorization": "Bearer wrong-key",
                },
            )
        )
    )

    assert response.status_code == 401
    assert response.headers["Access-Control-Allow-Origin"] == "*"


def test_dynamically_registered_v1_route_fails_closed():
    app = app_module.create_app(GatewayConfig(_gateway_config()))

    @app.post("/v1/dynamic")
    async def dynamic_route(request: Any) -> JSONResponse:
        return JSONResponse({"reached": True})

    unauthenticated = asyncio.run(
        app._dispatch(_app_request(app, method="POST", path="/v1/dynamic", headers={}))
    )
    authenticated = asyncio.run(
        app._dispatch(
            _app_request(
                app,
                method="POST",
                path="/v1/dynamic",
                headers={"authorization": "Bearer test-gateway-key"},
            )
        )
    )

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200


def test_unknown_v1_path_requires_key_then_reaches_router_error():
    app = app_module.create_app(GatewayConfig(_gateway_config()))

    unauthenticated = asyncio.run(
        app._dispatch(_app_request(app, method="GET", path="/v1/unknown", headers={}))
    )
    authenticated = asyncio.run(
        app._dispatch(
            _app_request(
                app,
                method="GET",
                path="/v1/unknown",
                headers={"authorization": "Bearer test-gateway-key"},
            )
        )
    )

    assert unauthenticated.status_code == 401
    # The wildcard OPTIONS route makes the current router report 405 for an
    # unknown non-OPTIONS method. Authentication must run before that result.
    assert authenticated.status_code == 405


def test_unknown_v1_preflight_remains_public():
    app = app_module.create_app(GatewayConfig(_gateway_config()))

    response = asyncio.run(
        app._dispatch(
            _app_request(
                app,
                method="OPTIONS",
                path="/v1/unknown",
                headers={"origin": "https://browser.example"},
            )
        )
    )

    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == "*"


def test_admin_cors_preflight_uses_hot_reloaded_allowlist(tmp_path):
    config_path = tmp_path / "config.jsonc"
    initial_data = _gateway_config(admin_cors_origins=["https://old-admin.example"])
    config_path.write_text(json.dumps(initial_data), encoding="utf-8")
    app = app_module.create_app(
        GatewayConfig(initial_data), config_path=str(config_path)
    )
    try:
        updated_data = _gateway_config(admin_cors_origins=["https://new-admin.example"])
        config_path.write_text(json.dumps(updated_data), encoding="utf-8")

        reload_response = asyncio.run(reload_config(MagicMock(app=app)))
        assert reload_response.status_code == 200

        old_origin = asyncio.run(
            app._dispatch(
                _app_request(
                    app,
                    method="OPTIONS",
                    path="/admin/api/config",
                    headers={"origin": "https://old-admin.example"},
                )
            )
        )
        new_origin = asyncio.run(
            app._dispatch(
                _app_request(
                    app,
                    method="OPTIONS",
                    path="/admin/api/config",
                    headers={"origin": "https://new-admin.example"},
                )
            )
        )

        assert old_origin.status_code == 403
        assert new_origin.status_code == 204
        assert new_origin.headers["Access-Control-Allow-Origin"] == (
            "https://new-admin.example"
        )
    finally:
        persistence = getattr(app, "persistence", None)
        if persistence is not None:
            persistence.close()


def test_proxy_handler_forwards_user_agent_to_non_streaming_proxy(monkeypatch):
    """The main proxy handler should pass client User-Agent to the upstream call."""
    captured_headers: dict[str, str] = {}

    class _Config:
        models = {"gpt-test": "test-provider"}

        def resolve(self, source_provider: ProviderType, model: str):
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_chat",
                    provider_name="test-provider",
                ),
                MagicMock(),
            )

    async def _fake_handle_non_streaming(*args: Any, **kwargs: Any):
        captured_headers.update(kwargs["extra_headers"])
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", _fake_handle_non_streaming)

    request = MagicMock()
    request.headers = {
        "user-agent": "codex-cli/1.2.3",
        "x-future-codex-capability": "direct-only",
    }
    request.json.return_value = {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "hello"}],
    }
    request.app.metadata_store = MagicMock()
    request.app.metrics = None
    request.app.request_log = None
    request.app.persistence = None
    request.app.profiler_state = None
    request.app.gateway_config = _Config()

    response = asyncio.run(app_module._proxy_handler(request, "openai_chat"))

    assert response.status_code == 200
    assert captured_headers["User-Agent"] == "codex-cli/1.2.3"
    assert "x-request-id" in captured_headers
    assert "x-future-codex-capability" not in captured_headers


def test_proxy_handler_uses_denylist_only_for_direct_responses(monkeypatch):
    captured_headers: dict[str, str] = {}

    class _Config:
        models = {"gpt-test": "test-provider"}

        def resolve(self, source_provider: ProviderType, model: str):
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_responses",
                    provider_name="test-provider",
                ),
                MagicMock(),
            )

    async def _fake_handle_non_streaming(*args: Any, **kwargs: Any):
        captured_headers.update(kwargs["extra_headers"])
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", _fake_handle_non_streaming)

    request = MagicMock()
    request.headers = {
        "Authorization": "Bearer gateway-client-key",
        "Content-Encoding": "zstd",
        "User-Agent": "codex_cli_rs/0.145.0",
        "x-codex-beta-features": "remote_compaction_v2",
        "x-future-codex-capability": "preserve-me",
        "x-oai-attestation": "opaque-proof",
    }
    request.json.return_value = {
        "model": "gpt-test",
        "input": [{"role": "user", "content": "hello"}],
    }
    request.app.metadata_store = MagicMock()
    request.app.metrics = None
    request.app.request_log = None
    request.app.persistence = None
    request.app.profiler_state = None
    request.app.transport = MagicMock()
    request.app.gateway_config = _Config()

    response = asyncio.run(app_module._proxy_handler(request, "openai_responses"))

    assert response.status_code == 200
    assert captured_headers["User-Agent"] == "codex_cli_rs/0.145.0"
    assert captured_headers["x-codex-beta-features"] == "remote_compaction_v2"
    assert captured_headers["x-future-codex-capability"] == "preserve-me"
    assert captured_headers["Content-Type"] == "application/json"
    assert captured_headers["Accept-Encoding"] == "identity"
    assert "x-request-id" in captured_headers
    assert not any(name.lower() == "authorization" for name in captured_headers)
    assert not any(name.lower() == "content-encoding" for name in captured_headers)
    assert not any(name.lower() == "x-oai-attestation" for name in captured_headers)


def test_proxy_stats_use_original_upstream_model_name(monkeypatch):
    """Stats must not expose the public model alias as the counter key."""
    recorded_models: list[str] = []

    class _Config:
        models = {"public-alias": "test-provider"}

        def resolve(self, source_provider: ProviderType, model: str):
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_chat",
                    provider_name="test-provider",
                    upstream_model="provider-original-model",
                ),
                MagicMock(),
            )

    async def _fake_handle_non_streaming(*args: Any, **kwargs: Any):
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", _fake_handle_non_streaming)
    monkeypatch.setattr(app_module, "record_request_stat", recorded_models.append)

    request = MagicMock()
    request.headers = {}
    request.json.return_value = {"model": "public-alias", "messages": []}
    request.app.metadata_store = MagicMock()
    request.app.metrics = None
    request.app.request_log = None
    request.app.persistence = None
    request.app.profiler_state = None
    request.app.gateway_config = _Config()

    response = asyncio.run(app_module._proxy_handler(request, "openai_chat"))

    assert response.status_code == 200
    assert recorded_models == ["provider-original-model"]


def test_proxy_success_survives_request_log_persistence_failure(monkeypatch):
    """Observability storage is best-effort and cannot replace a proxy response."""

    class _Config:
        models = {"gpt-test": "test-provider"}

        def resolve(self, source_provider: ProviderType, model: str):
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_chat",
                    provider_name="test-provider",
                ),
                MagicMock(),
            )

    async def _fake_handle_non_streaming(*args: Any, **kwargs: Any):
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", _fake_handle_non_streaming)

    request = MagicMock()
    request.headers = {}
    request.json.return_value = {"model": "gpt-test", "messages": []}
    request.app.metadata_store = MagicMock()
    request.app.codex_tool_store = MagicMock()
    request.app.transport = MagicMock()
    request.app.metrics = None
    request.app.request_log.add.side_effect = RuntimeError("sqlite unavailable")
    request.app.persistence = None
    request.app.profiler_state = None
    request.app.gateway_config = _Config()

    response = asyncio.run(app_module._proxy_handler(request, "openai_chat"))

    assert response.status_code == 200
    assert isinstance(response, JSONResponse)
    assert json.loads(response.body) == {"ok": True}


def test_proxy_handler_rotates_model_group_after_upstream_failure(monkeypatch):
    class _Ring:
        current = "first"
        generation = 0

        async def await_attempt(self):
            return (self.current, self.generation), False, False

        def observe(self):
            return self.current, self.generation

        async def claim_observation(self, observed):
            assert observed == (self.current, self.generation)
            self.generation += 1
            return True, False

        def mark_failed(self, provider):
            assert provider == "first"

        def available(self):
            return ("first", "second")

        async def select_automatically(self, provider):
            self.current = provider

        async def publish(self):
            return None

        async def handoff(self):
            return None

    class _Config:
        models = {"gpt-test": "first"}
        model_group_names_by_model = {"gpt-test": "main"}

        def __init__(self):
            self.ring = _Ring()
            self.model_group_rings = {"main": self.ring}
            self.providers = {"first": MagicMock(), "second": MagicMock()}
            self.calls: list[str] = []

        def resolve(self, source_provider: ProviderType, model: str):
            self.calls.append(self.ring.current)
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_chat",
                    provider_name=self.ring.current,
                ),
                self.providers[self.ring.current],
            )

    config = _Config()
    calls = 0

    async def _fake_handle_non_streaming(*args: Any, **kwargs: Any):
        nonlocal calls
        calls += 1
        if calls == 1:
            return JSONResponse({"error": "first failed"}, status_code=502), {
                "upstream_provider_failure": True,
                "provider_failure_origin": "upstream_response",
            }
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", _fake_handle_non_streaming)
    request = MagicMock()
    request.headers = {}
    request.json.return_value = {"model": "gpt-test", "messages": []}
    request.app.metadata_store = MagicMock()
    request.app.metrics = None
    request.app.request_log = None
    request.app.persistence = None
    request.app.profiler_state = None
    request.app.gateway_config = config

    response = asyncio.run(app_module._proxy_handler(request, "openai_chat"))

    assert response.status_code == 200
    assert calls == 2
    assert config.calls == ["first", "second"]
    assert config.ring.current == "second"


def test_proxy_handler_rotates_fixed_credential_candidate_without_provider_selection(
    monkeypatch,
) -> None:
    first_uuid = "0488ffa0-e7b7-59ed-b1d0-6d43275607f5"
    second_uuid = "00000000-0000-4000-8000-000000000002"
    raw = _gateway_config()
    raw["providers"]["test-provider"].update(
        auto_rotate_credentials=False,
        api_keys=[
            *raw["providers"]["test-provider"]["api_keys"],
            {
                "uuid": second_uuid,
                "id": "renamed-second",
                "key": "sk-second",
            },
        ],
    )
    raw["model_groups"]["test"]["provider"] = [
        {"provider": "test-provider", "credential_uuid": first_uuid},
        {"provider": "test-provider", "credential_uuid": second_uuid},
    ]
    config = GatewayConfig(raw)
    attempts: list[str] = []

    async def fake_handle(_route, provider, *_args: Any, **_kwargs: Any):
        attempts.append(provider.current_credential_id)
        if provider.current_credential_id == "primary":
            return JSONResponse({"error": "failed"}, status_code=503), {
                "upstream_provider_failure": True,
                "provider_failure_origin": "upstream_response",
            }
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", fake_handle)

    response = asyncio.run(
        app_module._proxy_handler(_proxy_request(config), "openai_chat")
    )

    assert response.status_code == 200
    assert attempts == ["primary", "renamed-second"]
    assert config.providers["test-provider"].current_credential_id == "primary"
    assert config.model_group_rings["test"].current.credential_uuid == second_uuid


def test_proxy_handler_does_not_rotate_pair_on_transport_exhaustion(
    monkeypatch,
) -> None:
    first_uuid = "0488ffa0-e7b7-59ed-b1d0-6d43275607f5"
    second_uuid = "00000000-0000-4000-8000-000000000002"
    raw = _gateway_config()
    raw["providers"]["test-provider"].update(
        auto_rotate_credentials=False,
        api_keys=[
            *raw["providers"]["test-provider"]["api_keys"],
            {
                "uuid": second_uuid,
                "id": "second",
                "key": "sk-second",
            },
        ],
    )
    raw["model_groups"]["test"]["provider"] = [
        {"provider": "test-provider", "credential_uuid": first_uuid},
        {"provider": "test-provider", "credential_uuid": second_uuid},
    ]
    config = GatewayConfig(raw)
    ring = config.model_group_rings["test"]
    writes: list[Any] = []
    attempts: list[str] = []

    async def record(_group: str, candidate: Any) -> None:
        writes.append(candidate)

    ring.bind_recorder(record)

    async def fake_handle(_route, provider, *_args: Any, **_kwargs: Any):
        attempts.append(provider.current_credential_id)
        if provider.current_credential_id == "primary":
            return JSONResponse({"error": "unavailable"}, status_code=503), {
                "upstream_provider_failure": True,
                "provider_failure_origin": "transport_exhaustion",
            }
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", fake_handle)

    response = asyncio.run(
        app_module._proxy_handler(_proxy_request(config), "openai_chat")
    )

    assert response.status_code == 503
    assert attempts == ["primary"]
    assert writes == []
    assert ring.current.credential_uuid == first_uuid
    assert ring.status_snapshot() == (
        (ring.candidates[0], "available"),
        (ring.candidates[1], "available"),
    )


def test_concurrent_provider_failure_blocks_waiter_then_makes_one_fresh_attempt(
    monkeypatch,
) -> None:
    config = _two_provider_gateway_config()
    ring = config.model_group_rings["test"]
    writes: list[tuple[str, _ModelGroupProviderCandidate]] = []
    first_attempts = 0
    second_attempts = 0
    both_first_started = asyncio.Event()
    release_first_failures = asyncio.Event()
    leader_second_started = asyncio.Event()
    release_leader_success = asyncio.Event()

    async def record(group: str, provider: _ModelGroupProviderCandidate) -> None:
        writes.append((group, provider))

    ring.bind_recorder(record)

    async def fake_handle(route, *_args: Any, **_kwargs: Any):
        nonlocal first_attempts, second_attempts
        if route.provider_name == "test-provider":
            first_attempts += 1
            if first_attempts == 2:
                both_first_started.set()
            await both_first_started.wait()
            await release_first_failures.wait()
            return JSONResponse({"error": "failed"}, status_code=502), {
                "upstream_provider_failure": True,
                "provider_failure_origin": "upstream_response",
            }
        second_attempts += 1
        if second_attempts == 1:
            leader_second_started.set()
            await release_leader_success.wait()
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", fake_handle)

    async def scenario() -> tuple[Any, Any]:
        first = asyncio.create_task(
            app_module._proxy_handler(_proxy_request(config), "openai_chat")
        )
        second = asyncio.create_task(
            app_module._proxy_handler(_proxy_request(config), "openai_chat")
        )
        await both_first_started.wait()
        release_first_failures.set()
        await leader_second_started.wait()
        await asyncio.sleep(0)
        assert second_attempts == 1
        release_leader_success.set()
        return await asyncio.gather(first, second)

    responses = asyncio.run(scenario())

    assert [response.status_code for response in responses] == [200, 200]
    assert first_attempts == 2
    assert second_attempts == 2
    assert writes == [("test", "second-provider")]


def test_provider_failover_leader_cancellation_hands_gate_to_waiter(
    monkeypatch,
) -> None:
    config = _two_provider_gateway_config()
    second_attempts = 0
    leader_second_started = asyncio.Event()
    never_release = asyncio.Event()

    async def fake_handle(route, *_args: Any, **_kwargs: Any):
        nonlocal second_attempts
        if route.provider_name == "test-provider":
            return JSONResponse({"error": "failed"}, status_code=502), {
                "upstream_provider_failure": True,
                "provider_failure_origin": "upstream_response",
            }
        second_attempts += 1
        if second_attempts == 1:
            leader_second_started.set()
            await never_release.wait()
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", fake_handle)

    async def scenario() -> Any:
        leader = asyncio.create_task(
            app_module._proxy_handler(_proxy_request(config), "openai_chat")
        )
        await leader_second_started.wait()
        waiter = asyncio.create_task(
            app_module._proxy_handler(_proxy_request(config), "openai_chat")
        )
        await asyncio.sleep(0)
        leader.cancel()
        with pytest.raises(asyncio.CancelledError):
            await leader
        return await asyncio.wait_for(waiter, timeout=0.2)

    response = asyncio.run(scenario())

    assert response.status_code == 200
    assert second_attempts == 2


def test_provider_persistence_failure_preserves_state_and_hands_off_gate(
    monkeypatch,
) -> None:
    config = _two_provider_gateway_config()
    ring = config.model_group_rings["test"]

    async def fail_record(_group: str, _provider: _ModelGroupProviderCandidate) -> None:
        raise RuntimeError("config write failed")

    ring.bind_recorder(fail_record)

    async def fake_handle(*_args: Any, **_kwargs: Any):
        return JSONResponse({"error": "failed"}, status_code=502), {
            "upstream_provider_failure": True,
            "provider_failure_origin": "upstream_response",
        }

    monkeypatch.setattr(app_module, "handle_non_streaming", fake_handle)

    async def scenario() -> tuple[Any, bool]:
        response = await app_module._proxy_handler(
            _proxy_request(config), "openai_chat"
        )
        _observation, _waited, inherited_leader = await ring.await_attempt()
        await ring.publish()
        return response, inherited_leader

    response, inherited_leader = asyncio.run(scenario())

    assert response.status_code == 500
    assert inherited_leader is True
    assert ring.current == "test-provider"
    assert ring.status_snapshot() == (
        ("test-provider", "available"),
        ("second-provider", "available"),
    )


def test_provider_attempt_loop_preserves_wire_and_single_ingress_telemetry(
    monkeypatch,
) -> None:
    config = _two_provider_gateway_config()
    request = _proxy_request(config, stream=True)
    wire = object()
    captured_wire: list[object] = []
    captured_bodies: list[dict[str, Any]] = []
    telemetry: list[dict[str, Any]] = []
    stats: list[str] = []

    monkeypatch.setattr(app_module, "take_inbound_wire_request", lambda: wire)
    monkeypatch.setattr(
        app_module,
        "bind_inbound_wire_request",
        lambda inbound, body: (inbound, dict(body)),
    )
    monkeypatch.setattr(
        app_module,
        "_record_telemetry",
        lambda _request, **kwargs: telemetry.append(kwargs),
    )
    monkeypatch.setattr(app_module, "record_request_stat", stats.append)

    async def fake_handle(route, _provider, body, **kwargs: Any):
        captured_wire.append(kwargs["inbound_wire_request"])
        captured_bodies.append(dict(body))
        body["mutated"] = route.provider_name
        if route.provider_name == "test-provider":
            return JSONResponse({"error": "failed"}, status_code=502), {
                "upstream_provider_failure": True,
                "provider_failure_origin": "upstream_response",
            }
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_streaming", fake_handle)

    response = asyncio.run(app_module._proxy_handler(request, "openai_chat"))

    assert response.status_code == 200
    assert captured_wire == [wire, wire]
    assert all("mutated" not in body for body in captured_bodies)
    assert len(stats) == 1
    assert len(telemetry) == 1
    assert request.json.call_count == 1


def test_empty_204_provider_failure_rotates_model_group(monkeypatch) -> None:
    config = _two_provider_gateway_config()
    attempted_providers: list[str] = []

    async def fake_handle(route, *_args: Any, **_kwargs: Any):
        attempted_providers.append(route.provider_name)
        if route.provider_name == "test-provider":
            return JSONResponse({}, status_code=204), {
                "upstream_provider_failure": True,
                "provider_failure_origin": "upstream_response",
            }
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", fake_handle)

    response = asyncio.run(
        app_module._proxy_handler(_proxy_request(config), "openai_chat")
    )

    assert response.status_code == 200
    assert attempted_providers == ["test-provider", "second-provider"]
    assert config.model_group_rings["test"].current == "second-provider"


@pytest.mark.parametrize(
    ("case", "expected_status", "expected_error"),
    [
        ("unknown-model", 404, "Unknown model"),
        ("missing-principal", 401, "Authenticated principal is unavailable"),
    ],
)
def test_early_proxy_errors_record_exact_telemetry_status(
    monkeypatch,
    case: str,
    expected_status: int,
    expected_error: str,
) -> None:
    config = GatewayConfig(_gateway_config())
    request = _proxy_request(config)
    telemetry: list[dict[str, Any]] = []
    monkeypatch.setattr(
        app_module,
        "_record_telemetry",
        lambda _request, **kwargs: telemetry.append(kwargs),
    )
    if case == "unknown-model":
        request.json.return_value = {"model": "unknown", "messages": []}
        principal_token = None
    else:
        principal_token = api_key_principal_var.set(None)

    try:
        response = asyncio.run(app_module._proxy_handler(request, "openai_chat"))
    finally:
        if principal_token is not None:
            api_key_principal_var.reset(principal_token)

    assert response.status_code == expected_status
    assert len(telemetry) == 1
    assert telemetry[0]["status_code"] == expected_status
    assert expected_error in telemetry[0]["error_detail"]


def test_all_disabled_model_group_returns_configuration_unavailable(
    monkeypatch,
) -> None:
    raw = _gateway_config()
    raw["providers"]["test-provider"]["enabled"] = False
    config = GatewayConfig(raw)
    request = _proxy_request(config)

    async def unexpected_attempt(*_args: Any, **_kwargs: Any):
        raise AssertionError("an all-disabled group cannot issue an upstream request")

    monkeypatch.setattr(app_module, "handle_non_streaming", unexpected_attempt)

    response = asyncio.run(app_module._proxy_handler(request, "openai_chat"))

    assert response.status_code == 503
    assert isinstance(response, JSONResponse)
    assert b"configuration unavailable" in response.body
    assert b"Codex Rosetta blocked" in response.body


def test_proxy_handler_does_not_rotate_an_already_open_stream(monkeypatch):
    class _Ring:
        current = "first"

        async def await_attempt(self):
            return (self.current, 0), False, False

        async def handoff(self):
            raise AssertionError("an open stream must not own provider failover")

    class _Config:
        models = {"gpt-test": "first"}
        model_group_names_by_model = {"gpt-test": "main"}
        model_group_rings = {"main": _Ring()}

        def resolve(self, source_provider: ProviderType, model: str):
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_chat",
                    provider_name="first",
                ),
                MagicMock(),
            )

    async def _empty_stream():
        if False:
            yield b""

    async def _fake_handle_streaming(*args: Any, **kwargs: Any):
        return StreamingResponse(_empty_stream(), content_type="text/event-stream"), {
            "upstream_provider_failure": True
        }

    monkeypatch.setattr(app_module, "handle_streaming", _fake_handle_streaming)
    request = MagicMock()
    request.headers = {}
    request.json.return_value = {"model": "gpt-test", "messages": [], "stream": True}
    request.app.metadata_store = MagicMock()
    request.app.metrics = None
    request.app.request_log = None
    request.app.persistence = None
    request.app.profiler_state = None
    request.app.gateway_config = _Config()

    response = asyncio.run(app_module._proxy_handler(request, "openai_chat"))

    assert isinstance(response, StreamingResponse)


def test_proxy_handler_does_not_rotate_rosetta_generated_error(monkeypatch):
    class _Ring:
        current = "first"

        async def await_attempt(self):
            return (self.current, 0), False, False

        async def handoff(self):
            raise AssertionError("Rosetta-generated errors must not own failover")

    class _Config:
        models = {"gpt-test": "first"}
        model_group_names_by_model = {"gpt-test": "main"}
        model_group_rings = {"main": _Ring()}

        def resolve(self, source_provider: ProviderType, model: str):
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_chat",
                    provider_name="first",
                ),
                MagicMock(),
            )

    async def _fake_handle_non_streaming(*args: Any, **kwargs: Any):
        return JSONResponse({"error": "payload too large"}, status_code=413), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", _fake_handle_non_streaming)
    request = MagicMock()
    request.headers = {}
    request.json.return_value = {"model": "gpt-test", "messages": []}
    request.app.metadata_store = MagicMock()
    request.app.metrics = None
    request.app.request_log = None
    request.app.persistence = None
    request.app.profiler_state = None
    request.app.gateway_config = _Config()

    response = asyncio.run(app_module._proxy_handler(request, "openai_chat"))

    assert response.status_code == 413


def test_proxy_handler_passes_codex_window_id_to_streaming_proxy(monkeypatch):
    """Codex window id scopes stream-only final-answer phase decisions."""
    captured_kwargs: dict[str, Any] = {}

    class _Config:
        models = {"glm-5.2": "test-provider"}
        web_search: dict[str, Any] = {}

        def resolve(self, source_provider: ProviderType, model: str):
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_chat",
                    provider_name="test-provider",
                ),
                MagicMock(),
            )

    async def _fake_handle_streaming(*args: Any, **kwargs: Any):
        captured_kwargs.update(kwargs)

        async def _empty_stream():
            if False:
                yield ""

        return StreamingResponse(_empty_stream(), content_type="text/event-stream"), {}

    monkeypatch.setattr(app_module, "handle_streaming", _fake_handle_streaming)

    request = MagicMock()
    request.headers = {
        "user-agent": "codex-cli/1.2.3",
        "x-codex-window-id": "thread-abc:0",
    }
    request.json.return_value = {
        "model": "glm-5.2",
        "input": [{"role": "user", "content": "hello"}],
        "stream": True,
    }
    request.app.metadata_store = MagicMock()
    request.app.metrics = None
    request.app.request_log = None
    request.app.persistence = None
    request.app.profiler_state = None
    request.app.stream_trace_state = None
    request.app.transport = MagicMock()
    request.app.gateway_config = _Config()

    response = asyncio.run(app_module._proxy_handler(request, "openai_responses"))

    assert response.status_code == 200
    assert captured_kwargs["codex_window_id"] == "thread-abc:0"
    scope = captured_kwargs["state_scope"]
    assert scope.principal_id == "test-client"
    assert scope.provider_name == "test-provider"
    assert scope.model == "glm-5.2"
    assert scope.conversation_id == "thread-abc:0"
    assert scope.persistent is True
    assert "x-codex-window-id" not in captured_kwargs["extra_headers"]


def test_proxy_handler_rewrites_enabled_late_codex_developer_before_conversion(
    monkeypatch,
):
    captured_body: dict[str, Any] = {}

    class _Config:
        models = {"deepseek-v4-flash": "test-provider"}
        web_search: dict[str, Any] = {}

        def resolve(self, source_provider: ProviderType, model: str):
            provider_info = MagicMock()
            provider_info.soft_interrupt = True
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_chat",
                    provider_name="test-provider",
                ),
                provider_info,
            )

    async def _fake_handle_streaming(*args: Any, **kwargs: Any):
        captured_body.update(args[2])

        async def _empty_stream():
            if False:
                yield ""

        return StreamingResponse(_empty_stream(), content_type="text/event-stream"), {}

    monkeypatch.setattr(app_module, "handle_streaming", _fake_handle_streaming)
    request = MagicMock()
    request.headers = {}
    request.json.return_value = {
        "model": "deepseek-v4-flash",
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "You are Codex."}],
            },
            {"type": "message", "role": "user", "content": "Initial task."},
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "Late context."}],
            },
            {"type": "message", "role": "user", "content": "Continue."},
        ],
        "client_metadata": {
            "x-codex-turn-metadata": json.dumps(
                {
                    "request_kind": "turn",
                    "session_id": "session-a",
                    "thread_id": "thread-a",
                    "turn_id": "turn-b",
                }
            )
        },
        "stream": True,
    }
    request.app.metadata_store = MagicMock()
    request.app.codex_tool_store = MagicMock()
    request.app.metrics = None
    request.app.request_log = None
    request.app.persistence = None
    request.app.profiler_state = None
    request.app.stream_trace_state = None
    request.app.transport = MagicMock()
    request.app.gateway_config = _Config()

    response = asyncio.run(app_module._proxy_handler(request, "openai_responses"))

    assert response.status_code == 200
    assert captured_body["input"][0]["role"] == "developer"
    assert captured_body["input"][1]["role"] == "user"
    assert captured_body["input"][2] == {
        "type": "message",
        "role": "user",
        "content": [
            {
                "type": "input_text",
                "text": "<system>\nLate context.\n</system>",
            }
        ],
    }
    assert captured_body["input"][3] == {
        "type": "message",
        "role": "user",
        "content": "Continue.",
    }


def test_proxy_handler_passes_codex_window_id_to_non_streaming_proxy(monkeypatch):
    """Codex window id is available to non-streaming request conversion."""
    captured_kwargs: dict[str, Any] = {}

    class _Config:
        models = {"glm-5.2": "test-provider"}

        def resolve(self, source_provider: ProviderType, model: str):
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_chat",
                    provider_name="test-provider",
                ),
                MagicMock(),
            )

    async def _fake_handle_non_streaming(*args: Any, **kwargs: Any):
        captured_kwargs.update(kwargs)
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", _fake_handle_non_streaming)

    request = MagicMock()
    request.headers = {"x-codex-window-id": "thread-abc:0"}
    request.json.return_value = {
        "model": "glm-5.2",
        "input": [{"role": "user", "content": "hello"}],
    }
    request.app.metadata_store = MagicMock()
    request.app.metrics = None
    request.app.request_log = None
    request.app.persistence = None
    request.app.profiler_state = None
    request.app.transport = MagicMock()
    request.app.gateway_config = _Config()

    response = asyncio.run(app_module._proxy_handler(request, "openai_responses"))

    assert response.status_code == 200
    assert captured_kwargs["codex_window_id"] == "thread-abc:0"
    scope = captured_kwargs["state_scope"]
    assert scope.principal_id == "test-client"
    assert scope.provider_name == "test-provider"
    assert scope.model == "glm-5.2"
    assert scope.conversation_id == "thread-abc:0"
    assert scope.persistent is True
    assert "x-codex-window-id" not in captured_kwargs["extra_headers"]


@pytest.mark.parametrize(
    "window_id",
    [
        "x" * 129,
        "é" * 65,
    ],
)
def test_proxy_handler_rejects_oversized_window_id_before_state(
    monkeypatch, window_id: str
):
    called = False

    class _Config:
        models = {"glm-5.2": "test-provider"}

        def resolve(self, source_provider: ProviderType, model: str):
            raise AssertionError("oversized window id reached routing")

    async def _fake_handle_non_streaming(*args: Any, **kwargs: Any):
        nonlocal called
        called = True
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", _fake_handle_non_streaming)
    request = MagicMock()
    request.headers = {"x-codex-window-id": window_id}
    request.json.return_value = {"model": "glm-5.2", "input": []}
    request.app.gateway_config = _Config()

    response = asyncio.run(app_module._proxy_handler(request, "openai_responses"))

    assert response.status_code == 400
    assert not isinstance(response, StreamingResponse)
    assert json.loads(response.body)["error"]["message"] == (
        "Codex Rosetta: 'x-codex-window-id' must be at most 128 UTF-8 bytes"
    )
    assert called is False


def test_proxy_handler_accepts_exact_window_id_byte_limit(monkeypatch):
    captured_kwargs: dict[str, Any] = {}

    class _Config:
        models = {"glm-5.2": "test-provider"}

        def resolve(self, source_provider: ProviderType, model: str):
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_chat",
                    provider_name="test-provider",
                ),
                MagicMock(),
            )

    async def _fake_handle_non_streaming(*args: Any, **kwargs: Any):
        captured_kwargs.update(kwargs)
        return JSONResponse({"ok": True}), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", _fake_handle_non_streaming)
    window_id = "é" * 64
    request = MagicMock()
    request.headers = {"x-codex-window-id": window_id}
    request.json.return_value = {"model": "glm-5.2", "input": []}
    request.app.metadata_store = MagicMock()
    request.app.codex_tool_store = MagicMock()
    request.app.metrics = None
    request.app.request_log = None
    request.app.persistence = None
    request.app.profiler_state = None
    request.app.transport = MagicMock()
    request.app.gateway_config = _Config()

    response = asyncio.run(app_module._proxy_handler(request, "openai_responses"))

    assert response.status_code == 200
    assert captured_kwargs["codex_window_id"] == window_id
    assert captured_kwargs["state_scope"].conversation_id == window_id
