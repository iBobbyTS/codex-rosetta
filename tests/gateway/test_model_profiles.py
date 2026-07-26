"""Tests for the shared resolved-model profile contract."""

from __future__ import annotations

import pytest

from codex_rosetta.gateway.model_profiles import (
    canonical_model_overrides,
    deep_merge,
    editable_model_info,
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
            "temperature": 0.55,
            "top_p": 1.0,
        },
    )

    model_info, runtime = canonical_model_overrides(profile)

    assert profile.input_modalities == ("text",)
    assert profile.supported_reasoning_levels == ("high", "max")
    assert model_info == {
        "context_window": 262_144,
        "max_context_window": 262_144,
    }
    assert runtime == {
        "temperature": 0.55,
        "top_p": 1.0,
    }


def test_provider_runtime_preset_is_copied_before_user_override() -> None:
    profile = resolve_model_profile(
        exposed_model="glm-public",
        upstream_model="glm-5.2",
        provider_id="opencode_go",
        runtime_capabilities_override={"temperature": 1.0},
    )

    assert profile.runtime_preset == {}
    assert profile.runtime_capabilities == {"temperature": 1.0}
    _model_info, runtime = canonical_model_overrides(profile)
    assert runtime == {"temperature": 1.0}


def test_provider_runtime_preset_matches_upstream_then_exposed_model() -> None:
    upstream_match = resolve_model_profile(
        exposed_model="public-qwen",
        upstream_model="qwen3.7-plus",
        provider_id="opencode_go",
    )
    exposed_fallback = resolve_model_profile(
        exposed_model="qwen3.7-plus",
        upstream_model="unknown-upstream",
        provider_id="opencode_go",
    )
    upstream_wins = resolve_model_profile(
        exposed_model="minimax-m2.5",
        upstream_model="qwen3.7-plus",
        provider_id="opencode_go",
    )

    expected = {"temperature": 0.55, "top_p": 1.0}
    assert upstream_match.runtime_preset == expected
    assert exposed_fallback.runtime_preset == expected
    assert upstream_wins.runtime_preset == expected
    assert canonical_model_overrides(upstream_match)[1] == {}


def test_provider_runtime_override_is_diffed_against_model_preset() -> None:
    profile = resolve_model_profile(
        exposed_model="qwen-public",
        upstream_model="qwen3.7-plus",
        provider_id="opencode_go",
        runtime_capabilities_override={"temperature": 0.4},
    )

    assert profile.runtime_capabilities == {"temperature": 0.4, "top_p": 1.0}
    assert canonical_model_overrides(profile)[1] == {"temperature": 0.4}


def test_explicit_null_runtime_override_is_preserved_by_canonical_diff() -> None:
    profile = resolve_model_profile(
        exposed_model="glm-public",
        upstream_model="glm-5.2",
        provider_id="opencode_go",
        runtime_capabilities_override={"temperature": None},
    )

    assert profile.runtime_capabilities == {"temperature": None}
    _model_info, runtime = canonical_model_overrides(profile)
    assert runtime == {"temperature": None}


def test_runtime_override_is_rejected_for_provider_without_declared_fields() -> None:
    with pytest.raises(ValueError, match="unsupported fields.*temperature"):
        resolve_model_profile(
            exposed_model="gpt-5.6-terra",
            upstream_model=None,
            provider_id="openai",
            runtime_capabilities_override={"temperature": 0.5},
        )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"temperature": 2.1}, "between 0 and 2"),
        ({"top_p": -0.1}, "between 0 and 1"),
        ({"temperature": True}, "number or null"),
    ],
)
def test_runtime_sampling_override_validation(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_model_profile(
            exposed_model="glm-5.2",
            upstream_model=None,
            provider_id="opencode_go",
            runtime_capabilities_override=override,
        )


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


def test_reasoning_config_is_compact_and_catalog_descriptions_are_canonical() -> None:
    profile = resolve_model_profile(
        exposed_model="glm-5.2",
        upstream_model=None,
        provider_id="opencode_go",
        model_info_override={
            "supported_reasoning_levels": [
                {"effort": "high", "description": "provider-specific text"}
            ]
        },
    )

    catalog_levels = profile.catalog_model()["supported_reasoning_levels"]
    assert catalog_levels == [
        {
            "effort": "high",
            "description": "Greater reasoning depth for complex problems",
        }
    ]
    assert editable_model_info(profile.catalog_model())[
        "supported_reasoning_levels"
    ] == ["high"]
    assert canonical_model_overrides(profile)[0] == {
        "supported_reasoning_levels": ["high"]
    }
