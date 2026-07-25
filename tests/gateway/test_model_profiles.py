"""Tests for the shared resolved-model profile contract."""

from __future__ import annotations

import pytest

from codex_rosetta.gateway.model_profiles import (
    canonical_model_overrides,
    deep_merge,
    normalized_deep_diff,
    resolve_model_profile,
)


def test_deep_merge_replaces_arrays_and_preserves_explicit_null() -> None:
    base = {"nested": {"keep": 1, "array": [1, 2], "nullable": "value"}}
    override = {"nested": {"array": [3], "nullable": None}}

    assert deep_merge(base, override) == {
        "nested": {"keep": 1, "array": [3], "nullable": None}
    }


def test_deep_diff_round_trip_and_empty_normalization() -> None:
    base = {"nested": {"keep": 1, "array": [1, 2]}}
    value = {"nested": {"keep": 1, "array": [3]}}

    difference = normalized_deep_diff(value, base)

    assert difference == {"nested": {"array": [3]}}
    assert deep_merge(base, difference) == value
    assert normalized_deep_diff(base, base) == {}


def test_preset_matching_prefers_upstream_then_exposed_fallback() -> None:
    upstream = resolve_model_profile(
        exposed_model="gpt-5.6-terra",
        upstream_model="glm-5.2",
        provider_id="opencode_go",
    )
    fallback = resolve_model_profile(
        exposed_model="glm-5.2",
        upstream_model="unknown-upstream",
        provider_id="opencode_go",
    )

    assert upstream.preset_slug == "glm-5.2"
    assert fallback.preset_slug == "glm-5.2"


def test_runtime_override_wins_and_is_saved_as_minimal_override() -> None:
    profile = resolve_model_profile(
        exposed_model="glm-public",
        upstream_model="glm-5.2",
        provider_id="opencode_go",
        model_info_override={"context_window": 262_144},
        runtime_capabilities_override={
            "input_modalities": ["text"],
            "supported_reasoning_levels": ["high"],
        },
    )

    model_info, runtime = canonical_model_overrides(profile)

    assert profile.input_modalities == ("text",)
    assert profile.supported_reasoning_levels == ("high",)
    assert model_info == {
        "context_window": 262_144,
        "max_context_window": 262_144,
    }
    assert runtime == {
        "input_modalities": ["text"],
        "supported_reasoning_levels": ["high"],
    }


def test_provider_runtime_preset_is_copied_before_user_override() -> None:
    profile = resolve_model_profile(
        exposed_model="glm-public",
        upstream_model="glm-5.2",
        provider_id="opencode_go",
        runtime_capabilities_override={"input_modalities": ["text"]},
    )

    assert profile.runtime_preset == {}
    assert profile.runtime_capabilities == {"input_modalities": ["text"]}
    _model_info, runtime = canonical_model_overrides(profile)
    assert runtime == {"input_modalities": ["text"]}


def test_unknown_preset_requires_complete_model_info() -> None:
    with pytest.raises(ValueError, match="complete model_info"):
        resolve_model_profile(
            exposed_model="unknown-model",
            upstream_model=None,
            provider_id="custom",
        )


def test_legacy_eight_field_model_info_remains_readable() -> None:
    profile = resolve_model_profile(
        exposed_model="legacy-model",
        upstream_model=None,
        provider_id="custom",
        model_info_override={
            "slug": "legacy-model",
            "display_name": "Legacy",
            "description": "Legacy eight-field record",
            "identity": "Legacy",
            "priority": 1,
            "context_window": 32_768,
            "input_modalities": ["text"],
            "supported_reasoning_levels": ["medium", "high"],
        },
    )

    assert profile.model_info["max_context_window"] == 32_768
    assert [
        item["effort"] for item in profile.model_info["supported_reasoning_levels"]
    ] == ["medium", "high"]
