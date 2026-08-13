"""Tests for Admin diagnostics that exercise the public Codex Search path."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from codex_rosetta._vendor.httpserver import JSONResponse, Request
from codex_rosetta.gateway.admin.routes import network_search
from codex_rosetta.gateway.app import create_app
from codex_rosetta.gateway.auth import (
    INTERNAL_ADMIN_PRINCIPAL,
    api_key_principal_var,
)
from codex_rosetta.gateway.codex_search_references import CodexSearchReferenceStore
from codex_rosetta.gateway.config import GatewayConfig, WebSearchConfig
from codex_rosetta.gateway.search_provider_chain import (
    SearchProviderAttemptCategory,
    SearchProviderAttemptError,
    SearchProviderChainCoordinator,
)
from codex_rosetta.gateway.search_provider_executor import SearchProviderExecutor
from codex_rosetta.gateway.search_provider_candidates import (
    TavilySearchProviderCandidate,
    build_search_provider_candidates,
)
from codex_rosetta.gateway.search_usage import TavilyUsage, TavilyUsageState
from codex_rosetta.gateway.tool_profiles import tool_profile_contract
from codex_rosetta.gateway.transport._base import UpstreamResponse


def _config() -> GatewayConfig:
    profile = tool_profile_contract()["readonly"]["builtin"]
    tools = dict(profile["tools"])
    tools["hosted.tool_search"] = "passthrough"
    tools["namespace.web.run"] = "modified"
    return GatewayConfig(
        {
            "tool_profiles": {
                "modified-search": {
                    "api_types": ["responses"],
                    "tools": tools,
                    "inputs": {
                        item_id: dict(values)
                        for item_id, values in profile["inputs"].items()
                    },
                }
            },
            "providers": {
                "model-provider": {
                    "provider": "openai",
                    "api_type": "responses",
                    "base_urls": ["https://model.example/v1"],
                    "current_base_url": "https://model.example/v1",
                    "api_keys": [{"id": "primary", "key": "model-key"}],
                    "current_api_key": "primary",
                },
                "search-provider": {
                    "provider": "openai",
                    "api_type": "responses",
                    "base_urls": ["https://search.example/v1"],
                    "current_base_url": "https://search.example/v1",
                    "api_keys": [{"id": "primary", "key": "search-key"}],
                    "current_api_key": "primary",
                },
            },
            "model_groups": {
                "Models": {
                    "provider": "model-provider",
                    "type": "llm",
                    "tool_profile": "modified-search",
                    "models": {"gpt-5.6-terra": {}},
                }
            },
            "server": {
                "admin_password": "test-admin-password",
                "api_keys": [
                    {"id": "test-client", "label": "Test", "key": "gateway-key"}
                ],
                "web_search": {
                    "providers": [
                        {
                            "id": "responses-search",
                            "provider": "configured_responses_provider",
                            "responses_model": "gpt-5.6-luna",
                            "responses_provider": "search-provider",
                        }
                    ],
                },
            },
        }
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/admin/api/network-search/usage"),
        ("POST", "/admin/api/network-search/test"),
    ],
)
def test_network_search_admin_endpoints_require_authentication(
    method: str, path: str
) -> None:
    app = create_app(_config())
    request = Request(
        method=method,
        path=path,
        query_string="",
        headers={},
        body=b"",
        client_addr=("127.0.0.1", 12345),
        app=app,
    )

    response = asyncio.run(app._dispatch(request))

    assert isinstance(response, JSONResponse)
    assert response.status_code == 401
    assert json.loads(response.body) == {"error": "Admin authentication required"}


def test_search_test_uses_public_auxiliary_handler(monkeypatch: Any) -> None:
    app = SimpleNamespace(gateway_config=_config())
    request = SimpleNamespace(app=app)
    captured: dict[str, Any] = {}

    async def fake_handle(
        adapted_request: Any, config: GatewayConfig, upstream_path: str
    ) -> JSONResponse:
        captured.update(
            request=adapted_request,
            config=config,
            upstream_path=upstream_path,
            body=adapted_request.json(),
            principal_id=api_key_principal_var.get(),
        )
        return JSONResponse({"result": "Python 3.test"})

    monkeypatch.setattr(network_search, "handle_codex_auxiliary", fake_handle)

    response = asyncio.run(network_search.test_network_search(request))

    assert response.status_code == 200
    assert json.loads(response.body) == {"result": "Python 3.test"}
    assert captured["request"].app is app
    assert captured["config"] is app.gateway_config
    assert captured["upstream_path"] == "alpha/search"
    assert captured["principal_id"] == INTERNAL_ADMIN_PRINCIPAL
    assert api_key_principal_var.get() is None
    assert captured["body"]["model"] == "gpt-5.6-terra"
    assert captured["body"]["commands"] == {
        "search_query": [{"q": network_search.SEARCH_TEST_QUERY}]
    }
    assert captured["body"]["settings"] == {
        "allowed_callers": ["direct"],
        "external_web_access": True,
    }


def test_search_test_requires_live_gateway_config() -> None:
    request = SimpleNamespace(app=SimpleNamespace())

    response = asyncio.run(network_search.test_network_search(request))

    assert response.status_code == 503
    assert json.loads(response.body) == {
        "error": "Gateway configuration is unavailable",
        "code": "network_search_test_configuration_unavailable",
    }


def test_search_test_restores_principal_after_handler_failure(monkeypatch: Any) -> None:
    async def fail_handle(*_args: Any, **_kwargs: Any) -> JSONResponse:
        assert api_key_principal_var.get() == INTERNAL_ADMIN_PRINCIPAL
        raise RuntimeError("sentinel failure")

    monkeypatch.setattr(network_search, "handle_codex_auxiliary", fail_handle)

    with pytest.raises(RuntimeError, match="sentinel failure"):
        asyncio.run(
            network_search.test_network_search(
                SimpleNamespace(app=SimpleNamespace(gateway_config=_config()))
            )
        )

    assert api_key_principal_var.get() is None


def test_search_test_rejects_config_without_eligible_model() -> None:
    config = _config()
    config.web_search = WebSearchConfig(
        [{"id": "tavily", "provider": "tavily", "tavily_api_key": "tvly-test"}]
    )
    config.models.clear()

    response = asyncio.run(
        network_search.test_network_search(
            SimpleNamespace(app=SimpleNamespace(gateway_config=config))
        )
    )

    assert response.status_code == 409
    assert json.loads(response.body) == {
        "error": "No configured model has an enabled web.run search route",
        "code": "network_search_test_no_eligible_model",
    }


def test_search_test_reaches_selected_responses_alpha_search() -> None:
    calls: list[tuple[Any, dict[str, Any]]] = []

    async def search(candidate: Any, body: dict[str, Any]) -> dict[str, Any]:
        calls.append((candidate, body))
        return {"output": "Python 3.test", "results": []}

    transport = SimpleNamespace(send_passthrough=AsyncMock())
    app = SimpleNamespace(
        gateway_config=_config(),
        transport=transport,
        metrics=None,
        request_log=None,
        codex_search_reference_store=CodexSearchReferenceStore(),
        search_provider_executor=SearchProviderExecutor(responses_client=search),
    )

    response = asyncio.run(network_search.test_network_search(SimpleNamespace(app=app)))

    assert response.status_code == 200
    assert len(calls) == 1
    candidate, body = calls[0]
    assert candidate.responses_provider == "search-provider"
    assert body["commands"] == {
        "search_query": [{"q": network_search.SEARCH_TEST_QUERY}]
    }
    assert body["model"] == "gpt-5.6-luna"
    transport.send_passthrough.assert_not_awaited()


def test_search_test_replaces_configured_responses_error_with_safe_dto() -> None:
    provider_detail = "debug endpoint http://10.0.0.5:9000, upstream request abc-123"

    async def fail_search(candidate: Any, body: dict[str, Any]) -> Any:
        del candidate, body
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.UPSTREAM_FAILURE)

    transport = SimpleNamespace(send_passthrough=AsyncMock())
    app = SimpleNamespace(
        gateway_config=_config(),
        transport=transport,
        metrics=None,
        request_log=None,
        codex_search_reference_store=CodexSearchReferenceStore(),
        search_provider_executor=SearchProviderExecutor(responses_client=fail_search),
    )

    response = asyncio.run(network_search.test_network_search(SimpleNamespace(app=app)))

    assert response.status_code == 502
    assert json.loads(response.body) == {
        "error": "Search provider is unavailable",
        "code": "network_search_test_unavailable",
    }
    assert provider_detail.encode() not in response.body
    transport.send_passthrough.assert_not_awaited()


def test_search_test_maps_real_terminal_rejection_to_safe_rejected_dto() -> None:
    provider_detail = "private provider URL http://10.0.0.5 request abc-123"
    transport = SimpleNamespace(
        send_passthrough=AsyncMock(
            return_value=UpstreamResponse(
                status_code=400,
                body=None,
                raw_content=json.dumps({"error": provider_detail}).encode(),
            )
        )
    )
    coordinator = SearchProviderChainCoordinator()
    config = _config()
    app = SimpleNamespace(
        gateway_config=config,
        transport=transport,
        metrics=None,
        request_log=None,
        codex_search_reference_store=CodexSearchReferenceStore(),
        search_provider_coordinator=coordinator,
    )

    response = asyncio.run(network_search.test_network_search(SimpleNamespace(app=app)))

    assert response.status_code == 422
    assert json.loads(response.body) == {
        "error": "Search request was rejected",
        "code": "network_search_test_rejected",
    }
    assert provider_detail.encode() not in response.body
    transport.send_passthrough.assert_awaited_once()
    assert coordinator.is_cooling(config.web_search_candidates[0]) is False


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (302, "network_search_test_rejected"),
        (400, "network_search_test_rejected"),
        (401, "network_search_test_authorization_failed"),
        (403, "network_search_test_authorization_failed"),
        (408, "network_search_test_timed_out"),
        (429, "network_search_test_rate_limited"),
        (500, "network_search_test_unavailable"),
        (504, "network_search_test_timed_out"),
    ],
)
def test_search_test_normalizes_every_handler_failure_category(
    monkeypatch: Any, status_code: int, expected_code: str
) -> None:
    provider_detail = "provider debug body http://internal.example/request/secret"

    async def fake_handle(*_args: Any, **_kwargs: Any) -> JSONResponse:
        return JSONResponse(
            {"error": {"message": provider_detail}}, status_code=status_code
        )

    monkeypatch.setattr(network_search, "handle_codex_auxiliary", fake_handle)

    response = asyncio.run(
        network_search.test_network_search(
            SimpleNamespace(app=SimpleNamespace(gateway_config=_config()))
        )
    )

    assert response.status_code == status_code
    assert json.loads(response.body)["code"] == expected_code
    assert provider_detail.encode() not in response.body


def test_usage_returns_only_safe_tavily_dto_rows() -> None:
    config = _config()
    config.web_search = WebSearchConfig(
        [
            {"id": "tavily-row", "provider": "tavily", "tavily_api_key": "secret"},
            {"id": "other-row", "provider": "self_hosted_google"},
        ]
    )
    state = TavilyUsageState()

    async def run() -> Any:
        async def fetch() -> dict[str, object]:
            return {"account": {"plan_usage": 4.9, "plan_limit": 10.9}}

        await state.get("secret", fetcher=fetch)
        return await network_search.get_network_search_usage(
            SimpleNamespace(
                app=SimpleNamespace(gateway_config=config, tavily_usage_state=state)
            )
        )

    response = asyncio.run(run())
    entry = json.loads(response.body)["entries"][0]

    assert {key: entry[key] for key in ("id", "status", "used", "limit")} == {
        "id": "tavily-row",
        "status": "ok",
        "used": 4,
        "limit": 10,
    }
    assert set(entry) == {"id", "status", "used", "limit", "reset_date"}
    assert "secret" not in response.body.decode()


def test_usage_with_no_tavily_rows_performs_no_io() -> None:
    config = _config()
    config.web_search = WebSearchConfig(
        [{"id": "other", "provider": "self_hosted_google"}]
    )

    class NoIOState(TavilyUsageState):
        async def get(self, *_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("usage transport must not run")

    response = asyncio.run(
        network_search.get_network_search_usage(
            SimpleNamespace(
                app=SimpleNamespace(
                    gateway_config=config,
                    tavily_usage_state=NoIOState(),
                )
            )
        )
    )

    assert json.loads(response.body) == {"entries": []}


def test_admin_usage_zero_marks_tavily_row_quota_exhausted() -> None:
    config = _config()
    config.web_search = WebSearchConfig(
        [{"id": "tavily-row", "provider": "tavily", "tavily_api_key": "secret"}]
    )
    tavily_candidate = network_search.TavilySearchProviderCandidate(
        row_id="tavily-row", api_key="secret", identity="identity"
    )
    config.web_search_candidates = (tavily_candidate,)
    state = TavilyUsageState()
    coordinator = SearchProviderChainCoordinator()

    async def run() -> Any:
        async def fetch() -> dict[str, object]:
            return {"account": {"plan_usage": 10, "plan_limit": 10}}

        await state.get("secret", fetcher=fetch)
        return await network_search.get_network_search_usage(
            SimpleNamespace(
                app=SimpleNamespace(
                    gateway_config=config,
                    tavily_usage_state=state,
                    search_provider_coordinator=coordinator,
                )
            )
        )

    response = asyncio.run(run())

    assert response.status_code == 200
    assert coordinator.is_quota_exhausted(tavily_candidate)


def test_status_exposes_only_current_and_routing_status_per_row() -> None:
    config = _config()
    config.web_search = WebSearchConfig(
        [
            {"id": "cooling", "provider": "self_hosted_google"},
            {"id": "available", "provider": "self_hosted_bing"},
            {"id": "empty", "provider": "tavily", "tavily_api_key": "secret"},
        ]
    )
    config.web_search_candidates = tuple(
        build_search_provider_candidates(
            config.web_search.providers,
            config.providers,
            {name: value["api_type"] for name, value in config._raw_providers.items()},
            allowed_responses_models=("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"),
        )
    )
    coordinator = SearchProviderChainCoordinator()
    cooling, _available, exhausted = config.web_search_candidates
    assert isinstance(exhausted, TavilySearchProviderCandidate)
    coordinator.mark_failed(
        cooling,
        SearchProviderAttemptError(SearchProviderAttemptCategory.UPSTREAM_FAILURE),
    )
    coordinator.apply_tavily_usage(
        exhausted,
        TavilyUsage(status="ok", used=10, limit=10, available_credits=0),
    )

    response = asyncio.run(
        network_search.get_network_search_status(
            SimpleNamespace(
                app=SimpleNamespace(
                    gateway_config=config,
                    search_provider_coordinator=coordinator,
                )
            )
        )
    )

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["current_provider_id"] == "cooling"
    assert body["providers"] == [
        {"id": "cooling", "status": "cooling", "current": True},
        {"id": "available", "status": "available", "current": False},
        {"id": "empty", "status": "exhausted", "current": False},
    ]
    assert "secret" not in response.body.decode()
    assert all(set(item) == {"id", "status", "current"} for item in body["providers"])


def test_manual_current_selection_clears_cooldown_and_rejects_exhausted() -> None:
    config = _config()
    config.web_search = WebSearchConfig(
        [
            {"id": "available", "provider": "self_hosted_google"},
            {"id": "cooling", "provider": "self_hosted_bing"},
            {"id": "empty", "provider": "tavily", "tavily_api_key": "secret"},
        ]
    )
    config.web_search_candidates = tuple(
        build_search_provider_candidates(
            config.web_search.providers,
            config.providers,
            {name: value["api_type"] for name, value in config._raw_providers.items()},
            allowed_responses_models=("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"),
        )
    )
    coordinator = SearchProviderChainCoordinator()
    _available, cooling, exhausted = config.web_search_candidates
    assert isinstance(exhausted, TavilySearchProviderCandidate)
    coordinator.mark_failed(
        cooling,
        SearchProviderAttemptError(SearchProviderAttemptCategory.UPSTREAM_FAILURE),
    )
    coordinator.apply_tavily_usage(
        exhausted,
        TavilyUsage(status="ok", used=10, limit=10, available_credits=0),
    )
    app = SimpleNamespace(
        gateway_config=config,
        search_provider_coordinator=coordinator,
    )

    selected = asyncio.run(
        network_search.select_network_search_provider(
            SimpleNamespace(app=app, json=lambda: {"current_provider_id": "cooling"})
        )
    )

    assert selected.status_code == 200
    assert json.loads(selected.body) == {"ok": True, "current_provider_id": "cooling"}
    assert coordinator.current_candidate(config.web_search_candidates) is cooling
    assert coordinator.is_cooling(cooling) is False

    rejected = asyncio.run(
        network_search.select_network_search_provider(
            SimpleNamespace(app=app, json=lambda: {"current_provider_id": "empty"})
        )
    )
    assert rejected.status_code == 409
    assert json.loads(rejected.body) == {"error": "Search provider quota is exhausted"}
    assert coordinator.current_candidate(config.web_search_candidates) is cooling
