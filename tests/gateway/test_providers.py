"""Tests for gateway provider metadata and auth behavior."""

from __future__ import annotations

import pytest

import codex_rosetta.gateway.transport.provider_info as provider_info_module

from codex_rosetta.gateway.config import GatewayConfig
from codex_rosetta.gateway.providers import (
    build_provider_info,
    normalize_provider_api_key,
    provider_api_key_values,
)


class TestBuildProviderInfo:
    def test_canonical_base_url_ring_preserves_configured_row_identity(self):
        info = build_provider_info(
            "openai_responses",
            {
                "api_keys": [{"id": "primary", "key": "test"}],
                "base_urls": [
                    "https://first.example/v1/",
                    "https://second.example/v1",
                ],
                "current_base_url": "https://second.example/v1",
                "request_encoding": "passthrough",
            },
            configured_id="second-row",
        )

        assert info.configured_id == "second-row"
        assert info.base_urls == (
            "https://first.example/v1",
            "https://second.example/v1",
        )
        assert info.base_url == "https://second.example/v1"

    def test_force_rosetta_compaction_is_propagated(self):
        info = build_provider_info(
            "openai_responses",
            {
                "api_keys": [{"id": "primary", "key": "test"}],
                "base_urls": ["https://upstream.example/v1"],
                "request_encoding": "passthrough",
                "force_rosetta_compaction": True,
            },
        )

        assert info.force_rosetta_compaction is True


def _gateway_config(provider: dict[str, object]) -> GatewayConfig:
    provider = dict(provider)
    if provider.get("api_type") == "responses":
        provider["request_encoding"] = "passthrough"
    return GatewayConfig(
        {
            "providers": {"upstream": provider},
            "model_groups": {
                "test": {
                    "provider": ["upstream"],
                    "type": "llm",
                    "models": {"test-model": {"upstream_model": "gpt-5.6-terra"}},
                }
            },
            "server": {
                "admin_password": "test-admin-password",
                "api_keys": [{"id": "test", "key": "gateway-key"}],
            },
        }
    )


def test_provider_canonical_parser_preserves_inventory_and_selects_first():
    value = [{"id": "first", "key": "first"}, {"id": "second", "key": "second"}]

    assert provider_api_key_values(value) == ("first", "second")
    assert normalize_provider_api_key(value) == "first"


def test_gateway_canonical_credentials_preserve_inventory_and_redaction():
    config = _gateway_config(
        {
            "provider": "custom",
            "api_type": "chat",
            "api_keys": [
                {
                    "uuid": "3e32528e-b812-5116-85d8-1c294c69565d",
                    "id": "first",
                    "key": "prefix",
                },
                {
                    "uuid": "4f476003-ce08-52a8-8eba-f79c3f857a0d",
                    "id": "second",
                    "key": "final",
                },
            ],
            "current_api_key": "first",
            "base_urls": ["https://upstream.example/v1"],
            "current_base_url": "https://upstream.example/v1",
        }
    )

    assert config._raw_providers["upstream"]["current_api_key"] == "first"
    assert config.providers["upstream"].credential_values == ("prefix", "final")
    assert config.providers["upstream"].auth_headers() == {
        "Authorization": "Bearer prefix"
    }
    assert {"prefix", "final"} <= config.token_values
    assert not hasattr(config.providers["upstream"], "key_ring")
    assert not hasattr(provider_info_module, "KeyRing")


def test_gateway_registers_environment_fallback_credential(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "environment-provider-key")

    config = _gateway_config(
        {
            "provider": "openai",
            "api_type": "chat",
            "base_urls": ["https://upstream.example/v1"],
            "current_base_url": "https://upstream.example/v1",
        }
    )

    assert config.providers["upstream"].credential_values == (
        "environment-provider-key",
    )
    assert "environment-provider-key" in config.token_values


def test_gateway_rejects_legacy_scalar_provider_credential():
    with pytest.raises(ValueError, match="api_key is unsupported; use api_keys"):
        _gateway_config(
            {
                "provider": "custom",
                "api_type": "chat",
                "api_key": "legacy-key",
                "base_urls": ["https://upstream.example/v1"],
            }
        )


def test_gateway_rejects_disabled_legacy_scalar_provider_credential():
    with pytest.raises(ValueError, match="api_key is unsupported; use api_keys"):
        _gateway_config(
            {
                "provider": "custom",
                "api_type": "chat",
                "api_key": "legacy-key",
                "base_urls": ["https://upstream.example/v1"],
                "enabled": False,
            }
        )


def test_gateway_requires_unique_credential_ids_and_member_current():
    common = {
        "provider": "custom",
        "api_type": "chat",
        "base_urls": ["https://upstream.example/v1"],
    }
    with pytest.raises(ValueError, match="api_keys IDs must be unique"):
        _gateway_config(
            {
                **common,
                "api_keys": [
                    {"id": "same", "key": "one"},
                    {"id": "same", "key": "two"},
                ],
            }
        )
    with pytest.raises(ValueError, match="current_api_key must be a member"):
        _gateway_config(
            {
                **common,
                "api_keys": [
                    {
                        "uuid": "968e8830-820e-5805-9c43-af08993cd504",
                        "id": "first",
                        "key": "one",
                    }
                ],
                "current_api_key": "missing",
            }
        )


def test_gateway_rejects_legacy_scalar_provider_base_url():
    with pytest.raises(ValueError, match="base_url is unsupported; use base_urls"):
        _gateway_config(
            {
                "provider": "custom",
                "api_type": "chat",
                "api_keys": [
                    {
                        "uuid": "5b207124-9439-5129-a6a4-011465dd9c3f",
                        "id": "primary",
                        "key": "test",
                    }
                ],
                "base_url": "https://upstream.example/v1",
            }
        )


def test_gateway_requires_current_base_url_to_belong_to_ring():
    with pytest.raises(ValueError, match="current_base_url must be a member"):
        _gateway_config(
            {
                "provider": "custom",
                "api_type": "chat",
                "api_keys": [
                    {
                        "uuid": "8eaf92e0-90c8-5663-8797-487f46e89403",
                        "id": "primary",
                        "key": "test",
                    }
                ],
                "base_urls": ["https://upstream.example/v1"],
                "current_base_url": "https://other.example/v1",
            }
        )
