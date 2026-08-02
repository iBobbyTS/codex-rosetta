"""Tests for Admin diagnostics that exercise the public Codex Search path."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from codex_rosetta._vendor.httpserver import JSONResponse
from codex_rosetta.gateway.admin.routes import network_search
from codex_rosetta.gateway.auth import (
    INTERNAL_ADMIN_PRINCIPAL,
    api_key_principal_var,
)
from codex_rosetta.gateway.codex_search_references import CodexSearchReferenceStore
from codex_rosetta.gateway.config import GatewayConfig
from codex_rosetta.gateway.transport._base import UpstreamResponse


def _config() -> GatewayConfig:
    return GatewayConfig(
        {
            "providers": {
                "model-provider": {
                    "provider": "openai",
                    "api_type": "responses",
                    "base_url": "https://model.example/v1",
                    "api_key": "model-key",
                },
                "search-provider": {
                    "provider": "openai",
                    "api_type": "responses",
                    "base_url": "https://search.example/v1",
                    "api_key": "search-key",
                },
            },
            "model_groups": {
                "Models": {
                    "provider": "model-provider",
                    "type": "llm",
                    "models": {"gpt-5.6-terra": {}},
                }
            },
            "server": {
                "admin_password": "test-admin-password",
                "api_keys": [
                    {"id": "test-client", "label": "Test", "key": "gateway-key"}
                ],
                "web_search": {
                    "provider": "configured_responses_provider",
                    "responses_model": "gpt-5.6-luna",
                    "responses_provider": "search-provider",
                },
            },
        }
    )


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
        "error": "Gateway configuration is unavailable"
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
    config.web_search = {"provider": "tavily", "tavily_api_key": "tvly-test"}
    config.models.clear()

    response = asyncio.run(
        network_search.test_network_search(
            SimpleNamespace(app=SimpleNamespace(gateway_config=config))
        )
    )

    assert response.status_code == 409
    assert json.loads(response.body) == {
        "error": "No configured model has an enabled web.run search route"
    }


def test_search_test_reaches_selected_responses_alpha_search() -> None:
    transport = SimpleNamespace(
        send_passthrough=AsyncMock(
            return_value=UpstreamResponse(
                status_code=200,
                body={"result": "Python 3.test"},
                raw_content=b'{"result":"Python 3.test"}',
            )
        )
    )
    app = SimpleNamespace(
        gateway_config=_config(),
        transport=transport,
        metrics=None,
        request_log=None,
        codex_search_reference_store=CodexSearchReferenceStore(),
    )

    response = asyncio.run(network_search.test_network_search(SimpleNamespace(app=app)))

    assert response.status_code == 200
    provider, url, body = transport.send_passthrough.await_args.args
    assert provider.base_url == "https://search.example/v1"
    assert url == "https://search.example/v1/alpha/search"
    assert body["commands"] == {
        "search_query": [{"q": network_search.SEARCH_TEST_QUERY}]
    }
    assert body["model"] == "gpt-5.6-luna"


def test_search_test_preserves_upstream_error_envelope() -> None:
    transport = SimpleNamespace(
        send_passthrough=AsyncMock(
            return_value=UpstreamResponse(
                status_code=502,
                body={
                    "error": {
                        "message": "Upstream search failed",
                        "type": "upstream_error",
                    }
                },
                raw_content=b'{"error":{"message":"Upstream search failed","type":"upstream_error"}}',
            )
        )
    )
    app = SimpleNamespace(
        gateway_config=_config(),
        transport=transport,
        metrics=None,
        request_log=None,
        codex_search_reference_store=CodexSearchReferenceStore(),
    )

    response = asyncio.run(network_search.test_network_search(SimpleNamespace(app=app)))

    assert response.status_code == 502
    assert json.loads(response.body) == {
        "error": {
            "message": "Upstream: Upstream search failed",
            "type": "upstream_error",
        }
    }
