"""Shared validation and lookup helpers for bundled Codex model presets."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from importlib import resources
from typing import Any, cast

PRESET_RESOURCE = "codex_model_presets.json"
MODEL_CATALOG_RESOURCE = "codex_models.json"
MODEL_INFO_STRING_FIELDS = ("slug", "display_name", "description", "identity")
MODEL_INFO_INTEGER_FIELDS = ("priority", "context_window")
MODEL_INFO_LIST_FIELDS = ("input_modalities", "supported_reasoning_levels")
MODEL_INFO_FIELDS = frozenset(
    (*MODEL_INFO_STRING_FIELDS, *MODEL_INFO_INTEGER_FIELDS, *MODEL_INFO_LIST_FIELDS)
)
MODEL_PRESET_EXTRA_OVERRIDE_FIELDS = frozenset(
    {"comp_hash", "supports_reasoning_summary_parameter", "context_window_presets"}
)
MODEL_PRESET_LEGACY_FIELDS = frozenset({"effective_context_window_percent"})
MODEL_PRESET_IGNORED_CATALOG_FIELDS = frozenset(
    {
        "available_in_plans",
        "minimal_client_version",
        "prefer_websockets",
        "reasoning_summary_format",
    }
)
MODEL_PRESET_TEMPLATE_FIELDS = frozenset(
    {
        "default_reasoning_level",
        "max_context_window",
        "model_messages",
    }
)


@lru_cache(maxsize=1)
def _cached_model_preset_resource() -> dict[str, Any]:
    raw = (
        resources.files("codex_rosetta.gateway")
        .joinpath(PRESET_RESOURCE)
        .read_text("utf-8")
    )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("bundled Codex model presets must be an object")
    if not isinstance(value.get("shared_overrides"), dict):
        raise ValueError("bundled Codex model presets have invalid shared overrides")
    if not isinstance(value.get("models"), list):
        raise ValueError("bundled Codex model presets have invalid models")
    return value


def load_model_preset_resource() -> dict[str, Any]:
    """Return an isolated copy of the bundled model-preset resource."""
    return copy.deepcopy(_cached_model_preset_resource())


def normalize_context_window_presets(value: Any, *, field: str) -> list[dict[str, Any]]:
    required = {
        "label",
        "context_window",
        "effective_context_window_percent",
        "auto_compact_token_limit",
    }
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty preset array")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError(f"{item_field} must contain exactly {sorted(required)}")
        item = cast(dict[str, Any], item)
        label = item["label"]
        context_window = item["context_window"]
        percent = item["effective_context_window_percent"]
        compact_limit = item["auto_compact_token_limit"]
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"{item_field}.label must be a non-empty string")
        for key, number in (
            ("context_window", context_window),
            ("effective_context_window_percent", percent),
            ("auto_compact_token_limit", compact_limit),
        ):
            if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
                raise ValueError(f"{item_field}.{key} must be a positive integer")
        if percent > 100:
            raise ValueError(
                f"{item_field}.effective_context_window_percent must not exceed 100"
            )
        if compact_limit > context_window:
            raise ValueError(
                f"{item_field}.auto_compact_token_limit must not exceed context_window"
            )
        normalized.append(
            {
                "label": label.strip(),
                "context_window": context_window,
                "effective_context_window_percent": percent,
                "auto_compact_token_limit": compact_limit,
            }
        )
    return normalized


def context_window_presets_for_admin() -> dict[str, list[dict[str, Any]]]:
    """Return the configured context-window choices keyed by exact model slug."""
    resource = _cached_model_preset_resource()
    presets = resource.get("context_window_presets", {})
    if not isinstance(presets, dict):
        raise ValueError("bundled Codex context window presets must be an object")
    return {
        slug: normalize_context_window_presets(
            value, field=f"bundled context window presets for {slug}"
        )
        for slug, value in presets.items()
    }


@lru_cache(maxsize=1)
def _cached_model_catalog_resource() -> dict[str, Any]:
    raw = (
        resources.files("codex_rosetta.gateway")
        .joinpath(MODEL_CATALOG_RESOURCE)
        .read_text("utf-8")
    )
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("models"), list):
        raise ValueError("bundled Codex model catalog has invalid models")
    return value


def _catalog_model_info(value: Any, *, index: int) -> dict[str, Any]:
    """Project one full Codex catalog model into editable model-info fields."""
    if not isinstance(value, dict):
        raise ValueError(
            f"bundled Codex catalog model at index {index} must be an object"
        )
    reasoning = value.get("supported_reasoning_levels")
    if not isinstance(reasoning, list):
        raise ValueError(
            f"bundled Codex catalog model at index {index} has invalid reasoning levels"
        )
    efforts = [
        level.get("effort") if isinstance(level, dict) else level for level in reasoning
    ]
    projected = {
        "slug": value.get("slug"),
        "display_name": value.get("display_name"),
        "description": value.get("description"),
        "identity": value.get("display_name"),
        "priority": value.get("priority"),
        "context_window": value.get("context_window"),
        "input_modalities": value.get("input_modalities"),
        "supported_reasoning_levels": efforts,
    }
    return normalize_model_info(
        projected, field=f"bundled Codex catalog model at index {index}"
    )


def normalize_model_info(value: Any, *, field: str) -> dict[str, Any]:
    """Validate one editable model-info document in preset-resource shape."""
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    unknown = sorted(set(value) - MODEL_INFO_FIELDS)
    if unknown:
        raise ValueError(f"{field} contains unsupported fields: {unknown}")

    normalized: dict[str, Any] = {}
    for key in MODEL_INFO_STRING_FIELDS:
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field}.{key} must be a non-empty string")
        normalized[key] = item.strip()

    for key in MODEL_INFO_INTEGER_FIELDS:
        item = value.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            raise ValueError(f"{field}.{key} must be a positive integer")
        normalized[key] = item

    for key in MODEL_INFO_LIST_FIELDS:
        item = value.get(key)
        if (
            not isinstance(item, list)
            or not item
            or not all(isinstance(entry, str) and entry.strip() for entry in item)
        ):
            raise ValueError(f"{field}.{key} must be a non-empty string array")
        normalized[key] = list(dict.fromkeys(entry.strip() for entry in item))
    return normalized


def _normalize_special_preset_overrides(
    value: dict[str, Any], *, field: str
) -> dict[str, Any]:
    """Validate preset overrides whose values affect Rosetta-owned behavior."""
    normalized: dict[str, Any] = {}
    if "comp_hash" in value:
        comp_hash = value["comp_hash"]
        if not isinstance(comp_hash, str) or not comp_hash.strip():
            raise ValueError(f"{field}.comp_hash must be a non-empty string")
        normalized["comp_hash"] = comp_hash.strip()

    if "context_window_presets" in value:
        normalized["context_window_presets"] = normalize_context_window_presets(
            value["context_window_presets"],
            field=f"{field}.context_window_presets",
        )

    for key in (
        "supports_reasoning_summary_parameter",
        "supports_parallel_tool_calls",
    ):
        if key in value:
            item = value[key]
            if not isinstance(item, bool):
                raise ValueError(f"{field}.{key} must be a boolean")
            normalized[key] = item

    if "default_reasoning_summary" in value:
        summary = value["default_reasoning_summary"]
        if summary not in {"none", "auto", "concise", "detailed"}:
            raise ValueError(
                f"{field}.default_reasoning_summary has an unsupported value"
            )
        normalized["default_reasoning_summary"] = summary

    if "truncation_policy" in value:
        truncation = value["truncation_policy"]
        if not isinstance(truncation, dict):
            raise ValueError(f"{field}.truncation_policy must be an object")
        if set(truncation) != {"mode", "limit"}:
            raise ValueError(f"{field}.truncation_policy must contain mode and limit")
        mode = truncation.get("mode")
        if mode not in {"bytes", "tokens"}:
            raise ValueError(
                f"{field}.truncation_policy.mode must be 'bytes' or 'tokens'"
            )
        limit = truncation.get("limit")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError(
                f"{field}.truncation_policy.limit must be a positive integer"
            )
        normalized["truncation_policy"] = {"mode": mode, "limit": limit}
    return normalized


def normalize_model_preset(
    value: Any,
    *,
    field: str,
    shared_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one bundled preset and its optional catalog-only overrides."""
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    shared_override_fields = frozenset(shared_overrides or ())
    unknown = sorted(
        set(value)
        - MODEL_INFO_FIELDS
        - MODEL_PRESET_EXTRA_OVERRIDE_FIELDS
        - shared_override_fields
    )
    if unknown:
        raise ValueError(f"{field} contains unsupported fields: {unknown}")

    special_overrides = _normalize_special_preset_overrides(value, field=field)
    model_info = {key: value.get(key) for key in MODEL_INFO_FIELDS}
    if model_info.get("context_window") is None:
        context_presets = special_overrides.get("context_window_presets")
        if context_presets:
            model_info["context_window"] = context_presets[0]["context_window"]
    normalized = normalize_model_info(
        model_info,
        field=field,
    )
    normalized.update(
        {
            key: copy.deepcopy(value[key])
            for key in shared_override_fields
            if key in value
        }
    )
    normalized.update(special_overrides)
    context_presets = special_overrides.get("context_window_presets")
    if context_presets:
        selected = context_presets[0]
        normalized["context_window"] = selected["context_window"]
        normalized["effective_context_window_percent"] = selected[
            "effective_context_window_percent"
        ]
        normalized["auto_compact_token_limit"] = selected["auto_compact_token_limit"]
    return normalized


def model_presets_for_admin() -> list[dict[str, Any]]:
    """Return all bundled models available to exact-slug Admin detection."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(_cached_model_catalog_resource()["models"]):
        preset = _catalog_model_info(value, index=index)
        slug = preset["slug"]
        if slug in seen:
            raise ValueError(f"duplicate bundled Codex model preset: {slug}")
        seen.add(slug)
        result.append(preset)
    resource = load_model_preset_resource()
    shared_overrides = resource["shared_overrides"]
    for index, value in enumerate(resource["models"]):
        preset = normalize_model_preset(
            value,
            field=f"bundled model preset at index {index}",
            shared_overrides=shared_overrides,
        )
        slug = preset["slug"]
        if slug in seen:
            raise ValueError(f"duplicate bundled Codex model preset: {slug}")
        seen.add(slug)
        result.append(preset)
    return result


def detect_model_preset(
    exposed_model: str, upstream_model: str | None = None
) -> dict[str, Any] | None:
    """Return an exact-slug preset, preferring the configured upstream model."""
    candidate = upstream_model.strip() if isinstance(upstream_model, str) else ""
    for slug in (candidate, exposed_model):
        if not slug:
            continue
        for preset in model_presets_for_admin():
            if preset["slug"] == slug:
                return preset
    return None


def _replace_identity(value: Any, source: str, identity: str) -> Any:
    if isinstance(value, str):
        return value.replace(source, identity)
    if isinstance(value, list):
        return [_replace_identity(item, source, identity) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_identity(item, source, identity)
            for key, item in value.items()
        }
    return copy.deepcopy(value)


def _materialize_full_preset(
    terra: dict[str, Any], resource: dict[str, Any], raw: dict[str, Any]
) -> dict[str, Any]:
    shared = resource["shared_overrides"]
    preset = normalize_model_preset(
        raw, field="bundled model preset", shared_overrides=shared
    )
    explicit = (
        MODEL_INFO_FIELDS
        | MODEL_PRESET_EXTRA_OVERRIDE_FIELDS
        | MODEL_PRESET_IGNORED_CATALOG_FIELDS
        | MODEL_PRESET_LEGACY_FIELDS
        | MODEL_PRESET_TEMPLATE_FIELDS
        | frozenset(shared)
    )
    model = {
        key: copy.deepcopy(value) for key, value in terra.items() if key not in explicit
    }
    model["model_messages"] = _replace_identity(
        terra.get("model_messages"), resource["identity_source"], preset["identity"]
    )
    model.update(copy.deepcopy(shared))
    model.update(
        {
            key: copy.deepcopy(value)
            for key, value in preset.items()
            if key not in {"identity", "supported_reasoning_levels"}
        }
    )
    requested = preset["supported_reasoning_levels"]
    levels = terra["supported_reasoning_levels"]
    by_effort = {item.get("effort"): item for item in levels if isinstance(item, dict)}
    missing = [effort for effort in requested if effort not in by_effort]
    if missing:
        raise ValueError(f"model preset references unknown reasoning levels: {missing}")
    model["supported_reasoning_levels"] = [
        copy.deepcopy(by_effort[effort]) for effort in requested
    ]
    model["max_context_window"] = model["context_window"]
    default = terra.get("default_reasoning_level")
    model["default_reasoning_level"] = default if default in requested else requested[0]
    return model


@lru_cache(maxsize=1)
def _cached_full_model_presets() -> dict[str, dict[str, Any]]:
    models = copy.deepcopy(_cached_model_catalog_resource()["models"])
    result = {model["slug"]: model for model in models}
    terra = result.get("gpt-5.6-terra")
    if not isinstance(terra, dict):
        raise ValueError("bundled Codex model catalog has no gpt-5.6-terra preset")
    resource = load_model_preset_resource()
    for raw in resource["models"]:
        model = _materialize_full_preset(terra, resource, raw)
        slug = model["slug"]
        if slug in result:
            raise ValueError(f"duplicate bundled Codex model preset: {slug}")
        result[slug] = model
    return result


def full_model_presets() -> dict[str, dict[str, Any]]:
    """Return isolated complete Codex records keyed by preset slug."""
    return copy.deepcopy(_cached_full_model_presets())


def match_full_model_preset(
    exposed_model: str, upstream_model: str | None = None
) -> dict[str, Any] | None:
    """Match upstream first, then the exposed model name."""
    presets = _cached_full_model_presets()
    upstream = upstream_model.strip() if isinstance(upstream_model, str) else ""
    for slug in (upstream, exposed_model):
        if slug in presets:
            return copy.deepcopy(presets[slug])
    return None


def model_input_modalities(
    exposed_model: str,
    upstream_model: str | None = None,
) -> list[str] | None:
    """Return compact-preset input modalities for one routed model.

    Runtime image filtering deliberately uses only ``codex_model_presets.json``.
    Full Codex catalog metadata and Admin ``model_info`` overrides describe the
    Codex-facing catalog but do not impose gateway-side modality restrictions.
    """
    candidate = upstream_model.strip() if isinstance(upstream_model, str) else ""
    slug = candidate or exposed_model
    resource = load_model_preset_resource()
    shared_overrides = resource["shared_overrides"]
    for index, value in enumerate(resource["models"]):
        preset = normalize_model_preset(
            value,
            field=f"bundled model preset at index {index}",
            shared_overrides=shared_overrides,
        )
        if preset["slug"] != slug:
            continue
        return list(preset["input_modalities"])
    return None
