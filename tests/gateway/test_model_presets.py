"""Tests for bundled model detection shared by Admin and runtime config."""

import hashlib
from importlib import resources

import pytest

from codex_rosetta.gateway.model_presets import (
    MODEL_PRESET_IGNORED_CATALOG_FIELDS,
    detect_model_preset,
    full_model_presets,
    load_model_preset_resource,
    model_input_modalities,
    model_presets_for_admin,
    normalize_model_preset,
)


EXPECTED_RUNTIME_SHARED_OVERRIDES = {
    "support_verbosity": True,
    "default_verbosity": "low",
    "apply_patch_tool_type": "freeform",
    "web_search_tool_type": "text_and_image",
    "supports_image_detail_original": False,
    "truncation_policy": {"mode": "tokens", "limit": 10000},
    "supports_parallel_tool_calls": False,
    "supports_reasoning_summary_parameter": False,
    "tool_mode": "code_mode_only",
    "multi_agent_version": "v2",
    "use_responses_lite": True,
    "include_skills_usage_instructions": False,
    "include_plugin_usage_instructions": True,
    "include_apps_usage_instructions": True,
    "auto_review_model_override": None,
    "auto_compact_token_limit": None,
    "default_reasoning_summary": "none",
    "shell_type": "shell_command",
    "visibility": "list",
    "supported_in_api": True,
    "availability_nux": None,
    "upgrade": None,
    "experimental_supported_tools": [],
    "supports_search_tool": True,
    "default_service_tier": None,
    "service_tiers": [],
    "additional_speed_tiers": [],
}

CODEX_0147_MODEL_CATALOG_SHA256 = (
    "384ff2e0ca67f65d2866e422e2ec7dfa5ed9e3fec7a84fe14005247a7087a302"
)


def test_bundled_catalog_matches_reviewed_codex_0147_asset() -> None:
    raw = (
        resources.files("codex_rosetta.gateway")
        .joinpath("codex_models.json")
        .read_bytes()
    )

    assert hashlib.sha256(raw).hexdigest() == CODEX_0147_MODEL_CATALOG_SHA256


def test_shared_overrides_match_runtime_snapshot() -> None:
    resource = load_model_preset_resource()
    assert set(resource["context_window_presets"]) == {
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    }

    assert resource["template_slug"] == "gpt-5.6-terra"
    assert resource["shared_overrides"] == EXPECTED_RUNTIME_SHARED_OVERRIDES
    assert not (
        MODEL_PRESET_IGNORED_CATALOG_FIELDS & resource["shared_overrides"].keys()
    )


def test_context_window_presets_are_model_data_and_first_value_is_default() -> None:
    resource = load_model_preset_resource()
    kimi = next(model for model in resource["models"] if model["slug"] == "kimi-k3")

    assert kimi["context_window_presets"][0] == {
        "label": "1M",
        "context_window": 1048576,
        "effective_context_window_percent": 95,
        "auto_compact_token_limit": 838861,
    }
    assert kimi["context_window_presets"][1]["context_window"] == 500000
    normalized = normalize_model_preset(kimi, field="kimi-k3")
    assert normalized["context_window"] == 1048576
    assert normalized["effective_context_window_percent"] == 95
    assert normalized["auto_compact_token_limit"] == 838861
    assert normalized["context_window_presets"] == kimi["context_window_presets"]


def test_every_context_window_preset_has_complete_limits() -> None:
    resource = load_model_preset_resource()
    preset_groups = list(resource["context_window_presets"].values()) + [
        model["context_window_presets"] for model in resource["models"]
    ]

    for presets in preset_groups:
        for preset in presets:
            context_window = preset["context_window"]
            assert set(preset) == {
                "label",
                "context_window",
                "effective_context_window_percent",
                "auto_compact_token_limit",
            }
            assert preset["effective_context_window_percent"] == 95
            assert preset["auto_compact_token_limit"] == round(context_window * 0.8)
            assert preset["auto_compact_token_limit"] <= context_window
        if any(preset["context_window"] >= 1000000 for preset in presets):
            assert any(preset["context_window"] == 500000 for preset in presets)


def test_context_window_presets_reject_legacy_value_key() -> None:
    resource = load_model_preset_resource()
    model = next(model for model in resource["models"] if model["slug"] == "kimi-k3")
    model["context_window_presets"][0]["value"] = model["context_window_presets"][
        0
    ].pop("context_window")

    with pytest.raises(ValueError, match="must contain exactly"):
        normalize_model_preset(model, field="kimi-k3")


def test_every_shared_override_is_allowed_in_each_model_preset() -> None:
    resource = load_model_preset_resource()
    shared_overrides = resource["shared_overrides"]
    raw_preset = dict(resource["models"][0], **shared_overrides)

    normalized = normalize_model_preset(
        raw_preset,
        field="test preset",
        shared_overrides=shared_overrides,
    )

    for key, value in shared_overrides.items():
        assert key in normalized
        if key == "auto_compact_token_limit":
            assert normalized[key] == 800000
        else:
            assert normalized[key] == value


def test_admin_detection_combines_codex_catalog_and_third_party_presets() -> None:
    presets = {preset["slug"]: preset for preset in model_presets_for_admin()}

    assert presets["gpt-5.6-terra"]["display_name"] == "GPT-5.6-Terra"
    assert presets["gpt-5.6-terra"]["identity"] == "GPT-5.6-Terra"
    assert presets["gpt-5.6-terra"]["supported_reasoning_levels"] == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "ultra",
    ]
    assert presets["deepseek-v4-pro"]["display_name"] == "DeepSeek V4 Pro"
    assert presets["qwen3.7-max"]["comp_hash"] == "qwen3.7-max-text"
    assert presets["qwen3.7-max-2026-06-08"]["comp_hash"] == "qwen3.7-max-image"
    assert presets["minimax-m3"]["supports_reasoning_summary_parameter"] is True
    assert presets["minimax-m3"]["default_reasoning_summary"] == "none"
    assert presets["minimax-m3"]["truncation_policy"] == {
        "mode": "bytes",
        "limit": 10000,
    }
    assert "supports_parallel_tool_calls" not in presets["minimax-m3"]


def test_official_and_third_party_presets_preserve_codex_0147_guidance_fields() -> None:
    presets = full_model_presets()

    assert presets["gpt-5.6-terra"]["include_apps_usage_instructions"] is True
    assert presets["gpt-5.6-terra"]["include_plugin_usage_instructions"] is True
    assert "base_instructions" not in presets["gpt-5.6-terra"]
    assert presets["deepseek-v4-flash"]["include_apps_usage_instructions"] is True
    assert presets["deepseek-v4-flash"]["include_plugin_usage_instructions"] is True
    assert "base_instructions" not in presets["deepseek-v4-flash"]


def test_model_detection_uses_exact_upstream_slug_then_exposed_slug() -> None:
    upstream_match = detect_model_preset("alias", "gpt-5.4")
    exposed_match = detect_model_preset("gpt-5.4-mini")

    assert upstream_match is not None
    assert upstream_match["display_name"] == "GPT-5.4"
    assert exposed_match is not None
    assert exposed_match["display_name"] == "GPT-5.4-Mini"
    assert detect_model_preset("glm-5.2-flash") is None


def test_compact_preset_modalities_drive_runtime_input_filtering() -> None:
    assert model_input_modalities("qwen3.7-plus") == ["text", "image"]
    assert model_input_modalities("gpt-5.6-sol") is None
    assert model_input_modalities("unknown-model") is None


@pytest.mark.parametrize("comp_hash", ["", "   ", 123, None])
def test_model_preset_rejects_invalid_explicit_compaction_hash(
    comp_hash: object,
) -> None:
    preset = {
        "slug": "test-model",
        "display_name": "Test Model",
        "description": "Test model preset",
        "identity": "Test Model",
        "priority": 20,
        "context_window": 128_000,
        "input_modalities": ["text"],
        "supported_reasoning_levels": ["high"],
        "comp_hash": comp_hash,
    }

    with pytest.raises(ValueError, match="comp_hash must be a non-empty string"):
        normalize_model_preset(preset, field="test preset")
