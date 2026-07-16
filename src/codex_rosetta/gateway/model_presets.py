"""Shared validation and lookup helpers for bundled Codex model presets."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from importlib import resources
from typing import Any

PRESET_RESOURCE = "codex_model_presets.json"
MODEL_CATALOG_RESOURCE = "codex_models_0_144_4.json"
MODEL_INFO_STRING_FIELDS = ("slug", "display_name", "description", "identity")
MODEL_INFO_INTEGER_FIELDS = ("priority", "context_window")
MODEL_INFO_LIST_FIELDS = ("input_modalities", "supported_reasoning_levels")
MODEL_INFO_FIELDS = frozenset(
    (*MODEL_INFO_STRING_FIELDS, *MODEL_INFO_INTEGER_FIELDS, *MODEL_INFO_LIST_FIELDS)
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
    for index, value in enumerate(load_model_preset_resource()["models"]):
        preset = normalize_model_info(
            value, field=f"bundled model preset at index {index}"
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
    slug = candidate or exposed_model
    for preset in model_presets_for_admin():
        if preset["slug"] == slug:
            return preset
    return None


def model_capabilities(
    exposed_model: str,
    value: Any,
) -> list[str]:
    """Derive gateway text/vision capabilities from model info or a preset."""
    mapping = value if isinstance(value, dict) else {}
    model_info = mapping.get("model_info")
    if isinstance(model_info, dict):
        modalities = model_info.get("input_modalities")
    else:
        preset = detect_model_preset(exposed_model, mapping.get("upstream_model"))
        modalities = preset.get("input_modalities") if preset else None
    if isinstance(modalities, list) and modalities:
        capabilities = ["text"]
        if "image" in modalities:
            capabilities.append("vision")
        return capabilities
    legacy = mapping.get("capabilities")
    if isinstance(legacy, list) and legacy:
        return list(dict.fromkeys(str(item) for item in legacy))
    return ["text"]
