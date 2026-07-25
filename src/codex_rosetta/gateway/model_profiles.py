"""Resolve immutable model profiles shared by Gateway and Codex catalog output."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from .model_presets import (
    MODEL_INFO_FIELDS,
    full_model_presets,
    match_full_model_preset,
)
from .provider_profiles import get_provider_catalog_entry

RUNTIME_CAPABILITY_FIELDS = frozenset(
    {"input_modalities", "supported_reasoning_levels"}
)
REQUIRED_MODEL_INFO_FIELDS = frozenset(
    {
        "slug",
        "display_name",
        "description",
        "priority",
        "context_window",
        "input_modalities",
        "supported_reasoning_levels",
    }
)


def deep_merge(base: Any, override: Any) -> Any:
    """Recursively apply *override* using config inheritance semantics."""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return copy.deepcopy(override)
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def deep_diff(value: Any, base: Any) -> Any:
    """Return the smallest recursive override that transforms *base* to *value*."""
    if isinstance(value, dict) and isinstance(base, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key not in base:
                result[key] = copy.deepcopy(item)
                continue
            difference = deep_diff(item, base[key])
            if difference is not _NO_DIFF:
                result[key] = difference
        return result if result else _NO_DIFF
    return _NO_DIFF if value == base else copy.deepcopy(value)


class _NoDiff:
    pass


_NO_DIFF = _NoDiff()


def normalized_deep_diff(value: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-compatible deep diff, normalizing an empty diff to ``{}``."""
    difference = deep_diff(value, base)
    return {} if difference is _NO_DIFF else difference


def _string_array(value: Any, *, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ValueError(f"{field} must be a non-empty string array")
    return list(dict.fromkeys(item.strip() for item in value))


def normalize_runtime_capabilities(value: Any, *, field: str) -> dict[str, Any]:
    """Validate the deliberately small runtime-capability override schema."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    unknown = sorted(set(value) - RUNTIME_CAPABILITY_FIELDS)
    if unknown:
        raise ValueError(f"{field} contains unsupported fields: {unknown}")
    return {
        key: _string_array(item, field=f"{field}.{key}") for key, item in value.items()
    }


def _reasoning_efforts(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty array")
    efforts = [item.get("effort") if isinstance(item, dict) else item for item in value]
    return _string_array(efforts, field=field)


def validate_full_model_info(value: Any, *, field: str) -> dict[str, Any]:
    """Validate required fields while preserving the complete Codex record."""
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    missing = sorted(REQUIRED_MODEL_INFO_FIELDS - set(value))
    if missing:
        raise ValueError(f"{field} is missing required fields: {missing}")
    for key in ("slug", "display_name", "description"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError(f"{field}.{key} must be a non-empty string")
    for key in ("priority", "context_window"):
        if (
            not isinstance(value[key], int)
            or isinstance(value[key], bool)
            or value[key] <= 0
        ):
            raise ValueError(f"{field}.{key} must be a positive integer")
    _string_array(value["input_modalities"], field=f"{field}.input_modalities")
    efforts = _reasoning_efforts(
        value["supported_reasoning_levels"],
        field=f"{field}.supported_reasoning_levels",
    )
    normalized = copy.deepcopy(value)
    if all(isinstance(item, str) for item in value["supported_reasoning_levels"]):
        terra_levels = full_model_presets()["gpt-5.6-terra"][
            "supported_reasoning_levels"
        ]
        by_effort = {item["effort"]: item for item in terra_levels}
        missing = [effort for effort in efforts if effort not in by_effort]
        if missing:
            raise ValueError(
                f"{field}.supported_reasoning_levels contains unknown efforts: "
                f"{missing}"
            )
        normalized["supported_reasoning_levels"] = [
            copy.deepcopy(by_effort[effort]) for effort in efforts
        ]
    return normalized


def _legacy_override_base(
    exposed_model: str,
    preset: dict[str, Any] | None,
    override: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Expand the legacy eight-field document onto a complete catalog record."""
    if not override or not set(override) <= MODEL_INFO_FIELDS:
        return (copy.deepcopy(preset) if preset is not None else {}), override
    base = copy.deepcopy(preset or full_model_presets()["gpt-5.6-terra"])
    expanded = copy.deepcopy(override)
    expanded.pop("identity", None)
    efforts = expanded.get("supported_reasoning_levels")
    if isinstance(efforts, list) and all(isinstance(item, str) for item in efforts):
        terra_levels = full_model_presets()["gpt-5.6-terra"][
            "supported_reasoning_levels"
        ]
        by_effort = {item["effort"]: item for item in terra_levels}
        missing = [effort for effort in efforts if effort not in by_effort]
        if missing:
            raise ValueError(
                "model_info.supported_reasoning_levels contains unknown "
                f"legacy efforts: {missing}"
            )
        expanded["supported_reasoning_levels"] = [
            copy.deepcopy(by_effort[effort]) for effort in efforts
        ]
    if "context_window" in expanded:
        expanded["max_context_window"] = expanded["context_window"]
    expanded["slug"] = exposed_model
    return base, expanded


@dataclass(frozen=True, slots=True)
class ResolvedModelProfile:
    """One resolved model record used by catalog generation and the gateway."""

    exposed_model: str
    upstream_model: str
    preset_slug: str | None
    model_info: dict[str, Any]
    runtime_preset: dict[str, Any]
    runtime_capabilities: dict[str, Any]
    input_modalities: tuple[str, ...]
    supported_reasoning_levels: tuple[str, ...]

    def catalog_model(self) -> dict[str, Any]:
        """Return an isolated Codex catalog record for the exposed model."""
        result = copy.deepcopy(self.model_info)
        result["slug"] = self.exposed_model
        return result


def resolve_model_profile(
    *,
    exposed_model: str,
    upstream_model: str | None,
    provider_id: str,
    model_info_override: Any = None,
    runtime_capabilities_override: Any = None,
) -> ResolvedModelProfile:
    """Resolve preset inheritance and runtime overrides into one profile."""
    upstream = (
        upstream_model.strip()
        if isinstance(upstream_model, str) and upstream_model.strip()
        else exposed_model
    )
    preset = match_full_model_preset(exposed_model, upstream)
    raw_override = {} if model_info_override is None else model_info_override
    if not isinstance(raw_override, dict):
        raise ValueError("model_info must be an object")
    legacy_base, normalized_override = _legacy_override_base(
        exposed_model, preset, raw_override
    )
    if preset is None:
        if not normalized_override:
            raise ValueError(
                f"model {exposed_model!r} does not match a built-in preset; "
                "a complete model_info record is required"
            )
        model_info = validate_full_model_info(
            deep_merge(legacy_base, normalized_override), field="model_info"
        )
        preset_slug = None
    else:
        base = legacy_base
        base["slug"] = exposed_model
        model_info = validate_full_model_info(
            deep_merge(base, normalized_override), field="model_info"
        )
        preset_slug = preset["slug"]

    provider_entry = get_provider_catalog_entry(provider_id)
    if provider_entry is None:
        raise ValueError(f"unknown provider main identity {provider_id!r}")
    runtime_preset = normalize_runtime_capabilities(
        dict(provider_entry.get("runtime_capabilities", {})),
        field=f"provider {provider_id!r} runtime_capabilities",
    )
    runtime_override = normalize_runtime_capabilities(
        runtime_capabilities_override, field="runtime_capabilities"
    )
    runtime = deep_merge(runtime_preset, runtime_override)
    modalities = runtime.get("input_modalities", model_info["input_modalities"])
    reasoning = runtime.get(
        "supported_reasoning_levels",
        _reasoning_efforts(
            model_info["supported_reasoning_levels"],
            field="model_info.supported_reasoning_levels",
        ),
    )
    return ResolvedModelProfile(
        exposed_model=exposed_model,
        upstream_model=upstream,
        preset_slug=preset_slug,
        model_info=model_info,
        runtime_preset=runtime_preset,
        runtime_capabilities=runtime,
        input_modalities=tuple(modalities),
        supported_reasoning_levels=tuple(reasoning),
    )


def canonical_model_overrides(
    profile: ResolvedModelProfile,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return normalized minimal config overrides for a resolved profile."""
    if profile.preset_slug is None:
        model_diff = copy.deepcopy(profile.model_info)
    else:
        base = copy.deepcopy(full_model_presets()[profile.preset_slug])
        base["slug"] = profile.exposed_model
        model_diff = normalized_deep_diff(profile.model_info, base)
    runtime_diff = normalized_deep_diff(
        profile.runtime_capabilities, profile.runtime_preset
    )
    return model_diff, runtime_diff
