"""Resource-lifecycle tests for Admin upstream model discovery."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from codex_rosetta.gateway.admin.routes import config as config_routes
from codex_rosetta.gateway.config import GatewayConfig
from codex_rosetta.gateway.transport import UpstreamProtocolError, UpstreamResponse


def _request(
    *,
    allow_redirects: bool = False,
    api_key: str = "sk-test",
    additional_api_keys: tuple[str, ...] = (),
    api_type: str = "chat",
) -> SimpleNamespace:
    config = GatewayConfig(
        {
            "providers": {
                "test-provider": {
                    "provider": "custom",
                    "api_keys": [
                        {
                            "uuid": "dbb39bde-4b7b-585e-9a17-21c5413a7998",
                            "id": "primary",
                            "key": api_key,
                        },
                        *(
                            {
                                "uuid": f"00000000-0000-4000-8000-{index + 1:012d}",
                                "id": f"additional-{index}",
                                "key": key,
                            }
                            for index, key in enumerate(additional_api_keys, start=1)
                        ),
                    ],
                    "current_api_key": "primary",
                    "base_urls": ["https://api.example.test/v1"],
                    "current_base_url": "https://api.example.test/v1",
                    "api_type": api_type,
                    "allow_redirects": allow_redirects,
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
            },
        }
    )
    return SimpleNamespace(
        app=SimpleNamespace(gateway_config=config, transport=AsyncMock()),
        path_params={"name": "test-provider"},
    )


def test_model_discovery_uses_common_provider_transport() -> None:
    request = _request()
    request.app.transport.send_passthrough.return_value = UpstreamResponse(
        status_code=200,
        body={"data": [{"id": "gpt-upstream"}]},
        raw_content=b'{"data":[{"id":"gpt-upstream"}]}',
    )

    response = asyncio.run(config_routes.fetch_upstream_models(request))

    assert json.loads(response.body)["models"] == ["gpt-upstream"]
    request.app.transport.send_passthrough.assert_awaited_once()
    args = request.app.transport.send_passthrough.await_args
    assert args.args[0] is request.app.gateway_config.providers["test-provider"]
    assert args.args[1] == "https://api.example.test/v1/models"
    assert args.kwargs["method"] == "GET"


def test_model_discovery_uses_provider_redirect_policy() -> None:
    request = _request(allow_redirects=True)
    request.app.transport.send_passthrough.return_value = UpstreamResponse(
        status_code=200, body={"data": []}, raw_content=b'{"data":[]}'
    )

    response = asyncio.run(config_routes.fetch_upstream_models(request))

    assert response.status_code == 200
    assert request.app.gateway_config.providers["test-provider"].allow_redirects is True
    request.app.transport.send_passthrough.assert_awaited_once()


def test_model_discovery_rejects_redirect_before_applying_models() -> None:
    request = _request()
    request.app.transport.send_passthrough.return_value = UpstreamResponse(
        status_code=302,
        body={"redirect": "ignored"},
        raw_content=b'{"redirect":"ignored"}',
    )

    response = asyncio.run(config_routes.fetch_upstream_models(request))

    assert json.loads(response.body) == {
        "error": (
            "Upstream returned HTTP 302. This provider may not support model listing."
        )
    }


def test_model_discovery_preserves_non_json_error() -> None:
    request = _request()
    request.app.transport.send_passthrough.side_effect = UpstreamProtocolError(
        "Upstream response is not valid JSON"
    )

    response = asyncio.run(config_routes.fetch_upstream_models(request))

    assert json.loads(response.body) == {"error": "Upstream returned non-JSON response"}


@pytest.mark.parametrize("outcome", ["success", "connection_error"])
def test_model_discovery_uses_current_key_and_blocks_additional_key(
    caplog: pytest.LogCaptureFixture,
    outcome: str,
) -> None:
    first_key = "admin-model-first-secret"
    wire_key = "admin-model-wire-secret"
    request = _request(api_key=first_key, additional_api_keys=(wire_key,))
    pinfo = request.app.gateway_config.providers["test-provider"]
    assert pinfo.auth_headers()["Authorization"] == f"Bearer {first_key}"
    if outcome == "connection_error":
        request.app.transport.send_passthrough.side_effect = RuntimeError(
            f"connection rejected credential={wire_key}"
        )
    else:
        request.app.transport.send_passthrough.return_value = UpstreamResponse(
            status_code=200,
            body={"data": [{"id": f"model-{wire_key}"}]},
            raw_content=b"{}",
        )

    response = asyncio.run(config_routes.fetch_upstream_models(request))

    response_text = response.body.decode("utf-8")
    assert first_key not in response_text
    assert wire_key not in response_text
    if outcome == "success":
        assert json.loads(response.body)["error"].endswith("response blocked")
    else:
        assert "Failed to connect to upstream" in response_text
        assert wire_key not in caplog.text
        assert "connection rejected credential=[REDACTED]" in caplog.text


@pytest.mark.parametrize(
    ("api_type", "payload"),
    [
        ("chat", []),
        ("chat", None),
        ("chat", "scalar"),
        ("chat", 7),
        ("chat", {}),
        ("chat", {"data": None}),
        ("chat", {"data": {"id": "not-a-list"}}),
        ("chat", {"data": [None]}),
        ("chat", {"data": [{"id": 7}]}),
        ("google", {}),
        ("google", {"models": None}),
        ("google", {"models": {"name": "models/not-a-list"}}),
        ("google", {"models": [None]}),
        ("google", {"models": [{"name": 7}]}),
    ],
)
def test_model_discovery_rejects_wrong_shape_json(
    api_type: str,
    payload: Any,
) -> None:
    request = _request(api_type=api_type)
    request.app.transport.send_passthrough.return_value = UpstreamResponse(
        status_code=200,
        body=payload,
        raw_content=b"{}",
    )

    response = asyncio.run(config_routes.fetch_upstream_models(request))

    assert json.loads(response.body) == {
        "error": "Upstream returned an invalid model list"
    }


@pytest.mark.parametrize(
    ("provider_type", "id_field", "body", "expected"),
    [
        ("openai_chat", None, {"data": [{"id": "z"}, {"id": "a"}]}, ["a", "z"]),
        ("anthropic", None, {"data": [{"id": "claude-test"}]}, ["claude-test"]),
        (
            "google",
            None,
            {"models": [{"name": "models/gemini-test", "__class__": "ignored"}]},
            ["gemini-test"],
        ),
        (
            "openai_chat",
            "internal_id",
            {"data": [{"id": "public", "internal_id": "private"}]},
            ["private"],
        ),
    ],
)
def test_normalize_upstream_model_ids_preserves_supported_schemas(
    provider_type: str,
    id_field: str | None,
    body: dict[str, Any],
    expected: list[str],
) -> None:
    assert (
        config_routes._normalize_upstream_model_ids(
            body,
            provider_type=provider_type,
            id_field=id_field,
        )
        == expected
    )
