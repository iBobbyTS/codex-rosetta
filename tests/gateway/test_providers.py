"""Tests for gateway provider metadata and auth behavior."""

from __future__ import annotations

import codex_rosetta.gateway.transport.provider_info as provider_info_module

from codex_rosetta.gateway.config import GatewayConfig
from codex_rosetta.gateway.providers import (
    build_provider_info,
    normalize_provider_api_key,
    provider_api_key_values,
)
from codex_rosetta.shims.providers import load_providers


class TestBuildProviderInfo:
    def test_force_rosetta_compaction_is_propagated(self):
        info = build_provider_info(
            "openai_responses",
            {
                "api_key": "test",
                "base_url": "https://upstream.example/v1",
                "force_rosetta_compaction": True,
            },
        )

        assert info.force_rosetta_compaction is True

    def test_argo_openai_chat_uses_bearer_auth(self, monkeypatch):
        load_providers()
        monkeypatch.setenv("ARGO_API_KEY", "pding")

        info = build_provider_info("argo--openai_chat", {})

        assert info.auth_headers() == {"Authorization": "Bearer pding"}
        assert (
            info.upstream_url("gpt5")
            == "https://apps.inside.anl.gov/argoapi/v1/chat/completions"
        )

    def test_argo_anthropic_uses_x_api_key_auth(self, monkeypatch):
        load_providers()
        monkeypatch.setenv("ARGO_API_KEY", "pding")

        info = build_provider_info("argo--anthropic", {})

        assert info.auth_headers() == {
            "x-api-key": "pding",
            "anthropic-version": "2023-06-01",
        }
        assert (
            info.upstream_url("claudeopus47")
            == "https://apps.inside.anl.gov/argoapi/v1/messages"
        )


def _gateway_config(provider: dict[str, object]) -> GatewayConfig:
    return GatewayConfig(
        {
            "providers": {"upstream": provider},
            "model_groups": {
                "test": {
                    "provider": "upstream",
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


def test_provider_legacy_parser_preserves_inventory_and_selects_first_non_empty():
    value = " first , , second,first, third ,, "

    assert provider_api_key_values(value) == ("first", "second", "first", "third")
    assert normalize_provider_api_key(value) == "first"
    assert normalize_provider_api_key(" , , ") == ""


def test_gateway_canonicalizes_legacy_csv_and_redacts_every_discarded_credential():
    raw_keys = " prefix ,prefix-long, , prefix,final "
    config = _gateway_config(
        {
            "provider": "custom",
            "api_type": "chat",
            "api_key": raw_keys,
            "base_url": "https://upstream.example/v1",
        }
    )

    assert config._raw_providers["upstream"]["api_key"] == "prefix"
    assert config.providers["upstream"].credential_values == ("prefix",)
    assert config.providers["upstream"].auth_headers() == {
        "Authorization": "Bearer prefix"
    }
    assert config.providers["upstream"].auth_headers() == {
        "Authorization": "Bearer prefix"
    }
    assert {raw_keys, "prefix", "prefix-long", "final"} <= config.token_values
    assert not hasattr(config.providers["upstream"], "key_ring")
    assert not hasattr(provider_info_module, "KeyRing")


def test_gateway_registers_environment_fallback_credential(monkeypatch):
    monkeypatch.setenv(
        "OPENAI_API_KEY", " environment-provider-key,discarded-environment-key "
    )

    config = _gateway_config(
        {
            "provider": "openai",
            "api_type": "chat",
            "base_url": "https://upstream.example/v1",
        }
    )

    assert config.providers["upstream"].credential_values == (
        "environment-provider-key",
    )
    assert {"environment-provider-key", "discarded-environment-key"} <= (
        config.token_values
    )
