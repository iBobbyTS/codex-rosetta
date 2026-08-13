"""Tests for the immutable provider profile catalog."""

from __future__ import annotations

import pytest

from codex_rosetta.gateway.provider_profiles import (
    get_provider_catalog_entry,
    provider_catalog_for_admin,
    resolve_force_rosetta_compaction,
    resolve_provider_profile,
    resolve_soft_interrupt,
)
from codex_rosetta.pipeline import ConversionPipeline


def test_recommended_protocols_are_declared_per_provider() -> None:
    providers = provider_catalog_for_admin()["providers"]

    assert providers["openai"]["recommended_api_type"] == "responses"
    assert providers["anthropic"]["recommended_api_type"] == "anthropic"
    assert providers["google"]["recommended_api_type"] == "google"
    assert providers["opencode_go"]["recommended_api_type"] == "chat"
    assert providers["opencode_go"]["runtime_capability_fields"] == [
        "temperature",
        "top_p",
    ]
    assert providers["openai"]["runtime_capability_fields"] == []
    assert providers["opencode_go"]["runtime_capabilities_by_model"][
        "qwen3.7-plus"
    ] == {"temperature": 0.55, "top_p": 1.0}
    assert providers["openai"]["runtime_capabilities_by_model"] == {}
    assert providers["deepseek"]["soft_interrupt_default"] is True
    assert providers["openai"]["soft_interrupt_default"] is False
    assert {"argo", "volcengine", "xai"}.isdisjoint(providers)


def test_soft_interrupt_defaults_are_protocol_scoped_and_overridable() -> None:
    assert resolve_soft_interrupt("deepseek", "chat") is True
    assert resolve_soft_interrupt("deepseek", "chat", False) is False
    assert resolve_soft_interrupt("custom", "chat") is False
    assert resolve_soft_interrupt("deepseek", "anthropic") is False

    with pytest.raises(ValueError, match="supported only.*chat"):
        resolve_soft_interrupt("deepseek", "anthropic", True)
    with pytest.raises(ValueError, match="must be a boolean"):
        resolve_soft_interrupt("deepseek", "chat", "true")


def test_force_rosetta_compaction_is_responses_only_and_strict() -> None:
    assert resolve_force_rosetta_compaction("responses") is False
    assert resolve_force_rosetta_compaction("responses", True) is True
    assert resolve_force_rosetta_compaction("chat", False) is False

    with pytest.raises(ValueError, match="supported only.*responses"):
        resolve_force_rosetta_compaction("chat", True)
    with pytest.raises(ValueError, match="must be a boolean"):
        resolve_force_rosetta_compaction("responses", "true")


def test_unadapted_combination_uses_only_selected_standard() -> None:
    profile = resolve_provider_profile("deepseek", "anthropic")

    assert profile.target_provider == "anthropic"
    assert profile.shim_name is None
    assert profile.adapted is False


def test_opencode_go_is_one_openai_chat_profile() -> None:
    profile = resolve_provider_profile("opencode_go", "chat")

    assert profile.target_provider == "openai_chat"
    assert profile.shim_name == "opencode_go"
    assert profile.adapted is True


def test_unknown_provider_identity_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown provider main identity"):
        resolve_provider_profile("unknown", "chat")


def test_provider_catalog_is_recursively_immutable_and_admin_copy_isolated() -> None:
    entry = get_provider_catalog_entry("opencode_go")
    assert entry is not None
    with pytest.raises(TypeError):
        entry["adapted_api_types"]["chat"] = "other"

    admin = provider_catalog_for_admin()
    admin["providers"]["opencode_go"]["adapted_api_types"]["chat"] = "other"
    assert resolve_provider_profile("opencode_go", "chat").shim_name == "opencode_go"


def test_model_name_can_only_change_model_field_for_same_profile() -> None:
    def convert(model: str) -> dict[str, object]:
        pipeline = ConversionPipeline(
            "openai_responses",
            "openai_chat",
            shim="opencode_go",
            upstream_model=model,
            input_modalities=["text"],
            supported_reasoning_levels=["high"],
        )
        return pipeline.convert_request(
            {
                "model": model,
                "input": "hi",
                "reasoning": {"effort": "high"},
            }
        )

    first = convert("glm-5.2")
    second = convert("kimi-k3")
    assert first.pop("model") == "glm-5.2"
    assert second.pop("model") == "kimi-k3"
    assert first == second
