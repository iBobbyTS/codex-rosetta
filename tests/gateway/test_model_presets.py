"""Tests for bundled model detection shared by Admin and runtime config."""

from codex_rosetta.gateway.model_presets import (
    detect_model_preset,
    model_capabilities,
    model_presets_for_admin,
)


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


def test_model_detection_uses_exact_upstream_slug_then_exposed_slug() -> None:
    upstream_match = detect_model_preset("alias", "gpt-5.4")
    exposed_match = detect_model_preset("gpt-5.4-mini")

    assert upstream_match is not None
    assert upstream_match["display_name"] == "GPT-5.4"
    assert exposed_match is not None
    assert exposed_match["display_name"] == "GPT-5.4-Mini"
    assert detect_model_preset("glm-5.2-flash") is None


def test_builtin_catalog_modalities_drive_runtime_capabilities() -> None:
    assert model_capabilities("gpt-5.6-sol", {}) == ["text", "vision"]
