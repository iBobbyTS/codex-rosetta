"""Immutable provider/profile catalog used by Gateway routing and Admin UI."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from types import MappingProxyType
from typing import Any, cast

from codex_rosetta.auto_detect import ProviderType

API_TYPE_TO_PROVIDER_TYPE: Mapping[str, ProviderType] = MappingProxyType(
    cast(
        dict[str, ProviderType],
        {
            "responses": "openai_responses",
            "chat": "openai_chat",
            "anthropic": "anthropic",
            "google": "google",
        },
    )
)

_MISSING = object()


def _freeze(value: Any) -> Any:
    """Recursively freeze bundled JSON data."""

    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Return an isolated JSON-compatible copy of recursively frozen data."""

    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return copy.deepcopy(value)


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """One provider main identity bound to one standard API protocol."""

    provider_id: str
    api_type: str
    target_provider: ProviderType
    shim_name: str | None

    @property
    def adapted(self) -> bool:
        """Return whether Rosetta applies provider-specific extensions."""

        return self.shim_name is not None


def _validate_runtime_capability_fields(provider_id: str, value: Any) -> list[str]:
    """Validate the Admin-editable runtime fields declared by one provider."""
    valid = (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and len(value) == len(set(value))
        and set(value) <= {"temperature", "top_p"}
    )
    if not valid:
        raise ValueError(
            f"provider {provider_id!r} has invalid runtime capability fields"
        )
    return value


def _validate_runtime_capabilities_by_model(
    provider_id: str, value: Any, allowed_fields: list[str]
) -> dict[str, dict[str, float | None]]:
    """Validate exact model-name presets for Provider sampling limits."""
    if not isinstance(value, dict):
        raise ValueError(
            f"provider {provider_id!r} has invalid model runtime capabilities"
        )
    result: dict[str, dict[str, float | None]] = {}
    for model, capabilities in value.items():
        if (
            not isinstance(model, str)
            or not model
            or not isinstance(capabilities, dict)
        ):
            raise ValueError(
                f"provider {provider_id!r} has invalid model runtime capabilities"
            )
        if not set(capabilities) <= set(allowed_fields):
            raise ValueError(
                f"provider {provider_id!r} model {model!r} has invalid runtime fields"
            )
        normalized: dict[str, float | None] = {}
        for field, item in capabilities.items():
            if item is None:
                normalized[field] = None
                continue
            maximum = 2.0 if field == "temperature" else 1.0
            if (
                not isinstance(item, (int, float))
                or isinstance(item, bool)
                or not 0 <= item <= maximum
            ):
                raise ValueError(
                    f"provider {provider_id!r} model {model!r} has invalid runtime value"
                )
            normalized[field] = float(item)
        result[model] = normalized
    return result


def _soft_interrupt_default(provider_id: str, entry: dict[str, Any]) -> bool:
    value = entry.get("soft_interrupt_default", False)
    if not isinstance(value, bool):
        raise ValueError(f"provider {provider_id!r} has invalid soft interrupt default")
    return value


@lru_cache(maxsize=1)
def _catalog() -> tuple[tuple[str, ...], Mapping[str, Mapping[str, Any]]]:
    raw = (
        resources.files("codex_rosetta.gateway")
        .joinpath("provider_catalog.json")
        .read_text("utf-8")
    )
    value = json.loads(raw)
    api_types = value.get("api_types") if isinstance(value, dict) else None
    providers = value.get("providers") if isinstance(value, dict) else None
    if not isinstance(api_types, list) or not isinstance(providers, dict):
        raise ValueError("bundled provider catalog has an invalid protocol list")
    if api_types != list(API_TYPE_TO_PROVIDER_TYPE):
        raise ValueError("bundled provider catalog has an invalid protocol list")
    normalized: dict[str, Mapping[str, Any]] = {}
    for provider_id, entry in providers.items():
        if not isinstance(provider_id, str) or not isinstance(entry, dict):
            raise ValueError("bundled provider catalog has an invalid provider entry")
        recommended = entry.get("recommended_api_type")
        adapted = entry.get("adapted_api_types")
        known = entry.get("known_supported_api_types")
        variants = entry.get("variants")
        runtime_capabilities = entry.get("runtime_capabilities", {})
        soft_interrupt_default = _soft_interrupt_default(provider_id, entry)
        runtime_capability_fields = _validate_runtime_capability_fields(
            provider_id, entry.get("runtime_capability_fields", [])
        )
        runtime_capabilities_by_model = _validate_runtime_capabilities_by_model(
            provider_id,
            entry.get("runtime_capabilities_by_model", {}),
            runtime_capability_fields,
        )
        if recommended not in API_TYPE_TO_PROVIDER_TYPE:
            raise ValueError(f"provider {provider_id!r} has invalid recommendation")
        if not isinstance(adapted, dict) or not set(adapted) <= set(api_types):
            raise ValueError(f"provider {provider_id!r} has invalid adapted protocols")
        if not isinstance(known, list) or not set(known) <= set(api_types):
            raise ValueError(
                f"provider {provider_id!r} has invalid supported protocols"
            )
        if not set(adapted) <= set(known):
            raise ValueError(f"provider {provider_id!r} adapts an unsupported protocol")
        if not isinstance(variants, dict) or not variants:
            raise ValueError(f"provider {provider_id!r} has no endpoint variants")
        if not isinstance(runtime_capabilities, dict):
            raise ValueError(
                f"provider {provider_id!r} has invalid runtime capabilities"
            )
        entry["runtime_capabilities"] = runtime_capabilities
        entry["soft_interrupt_default"] = soft_interrupt_default
        entry["runtime_capability_fields"] = runtime_capability_fields
        entry["runtime_capabilities_by_model"] = runtime_capabilities_by_model
        normalized[provider_id] = _freeze(entry)
    return tuple(api_types), MappingProxyType(normalized)


def api_type_order() -> tuple[str, ...]:
    """Return the canonical Admin protocol order."""

    return _catalog()[0]


def provider_catalog_for_admin() -> dict[str, Any]:
    """Return an isolated JSON-compatible copy of the provider catalog."""

    api_types, providers = _catalog()
    return {
        "api_types": list(api_types),
        "providers": _thaw(providers),
    }


def get_provider_catalog_entry(provider_id: str) -> Mapping[str, Any] | None:
    """Return immutable metadata for a provider main identity."""

    return _catalog()[1].get(provider_id)


def resolve_soft_interrupt(
    provider_id: str,
    api_type: str,
    value: Any = _MISSING,
) -> bool:
    """Resolve the legacy-named hard-interrupt cache compatibility setting."""

    entry = get_provider_catalog_entry(provider_id)
    if entry is None:
        raise ValueError(
            f"config: unknown provider main identity {provider_id!r}; "
            "use provider: 'custom' for an unadapted endpoint"
        )
    if value is _MISSING and api_type != "chat":
        return False
    resolved = entry["soft_interrupt_default"] if value is _MISSING else value
    if not isinstance(resolved, bool):
        raise ValueError("config: provider soft_interrupt must be a boolean")
    if resolved and api_type != "chat":
        raise ValueError(
            "config: provider soft_interrupt is supported only for api_type 'chat'"
        )
    return resolved if api_type == "chat" else False


def resolve_provider_profile(provider_id: str, api_type: str) -> ProviderProfile:
    """Resolve an explicit provider/protocol pair without URL inference."""

    entry = get_provider_catalog_entry(provider_id)
    if entry is None:
        raise ValueError(
            f"config: unknown provider main identity {provider_id!r}; use provider: 'custom' for an unadapted endpoint"
        )
    target_provider = API_TYPE_TO_PROVIDER_TYPE.get(api_type)
    if target_provider is None:
        raise ValueError(
            f"config: provider {provider_id!r} has unsupported api_type {api_type!r}"
        )
    adapted = entry["adapted_api_types"]
    shim_name = adapted.get(api_type) if isinstance(adapted, Mapping) else None
    return ProviderProfile(
        provider_id,
        api_type,
        target_provider,
        shim_name if isinstance(shim_name, str) else None,
    )
