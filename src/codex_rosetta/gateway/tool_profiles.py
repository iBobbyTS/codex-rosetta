"""Tool-profile contracts derived from the bundled Codex tool catalog."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

from .admin.tool_catalog import load_tool_catalog

BUILTIN_TOOL_PROFILE = "builtin"
RESPONSES_PASS_THROUGH_TOOL_PROFILE = "responses_pass_through"
MAX_TOOL_PROFILE_NAME_LENGTH = 128
MAX_TOOL_PROFILE_INPUT_LENGTH = 16_384


def _normalize_visible_when(
    item_id: str,
    value: Any,
    supported_states: tuple[str, ...],
    *,
    field: str,
) -> list[str] | None:
    """Validate an optional state-based card visibility condition."""
    if value is None:
        return None
    if not isinstance(value, list) or any(
        not isinstance(state, str) for state in value
    ):
        raise ValueError(f"catalog item {item_id!r} {field} must be a list of strings")
    if len(value) != len(set(value)):
        raise ValueError(f"catalog item {item_id!r} {field} contains duplicate states")
    unsupported = sorted(set(value) - set(supported_states))
    if unsupported:
        raise ValueError(
            f"catalog item {item_id!r} {field} contains unsupported states: "
            f"{unsupported}"
        )
    return list(cast(list[str], value))


def _normalize_profile_select_options(
    item_id: str,
    input_id: str,
    value: Any,
    default: str,
) -> list[dict[str, str]]:
    """Validate one catalog-declared select option list."""
    if not isinstance(value, list) or not value:
        raise ValueError(
            f"catalog item {item_id!r} profile input {input_id!r} "
            "select options must be a non-empty list"
        )
    normalized: list[dict[str, str]] = []
    option_values: set[str] = set()
    for option in value:
        if not isinstance(option, dict) or set(option) != {"value", "label"}:
            raise ValueError(
                f"catalog item {item_id!r} profile input {input_id!r} "
                "select options must contain exactly 'value' and 'label'"
            )
        option_value = option["value"]
        option_label = option["label"]
        if not isinstance(option_value, str) or not isinstance(option_label, str):
            raise ValueError(
                f"catalog item {item_id!r} profile input {input_id!r} "
                "select option value and label must be strings"
            )
        if not option_label:
            raise ValueError(
                f"catalog item {item_id!r} profile input {input_id!r} "
                "select option label must be non-empty"
            )
        if len(option_value) > MAX_TOOL_PROFILE_INPUT_LENGTH:
            raise ValueError(
                f"catalog item {item_id!r} profile input {input_id!r} "
                f"select option value exceeds {MAX_TOOL_PROFILE_INPUT_LENGTH} characters"
            )
        if option_value in option_values:
            raise ValueError(
                f"catalog item {item_id!r} profile input {input_id!r} "
                f"has duplicate select option value {option_value!r}"
            )
        option_values.add(option_value)
        normalized.append({"value": option_value, "label": option_label})
    if default not in option_values:
        raise ValueError(
            f"catalog item {item_id!r} profile input {input_id!r} "
            "select default must match an option value"
        )
    return normalized


def _normalize_profile_input_definition(
    item_id: str,
    value: Any,
    existing_ids: set[str],
    supported_states: tuple[str, ...],
) -> tuple[str, dict[str, Any]]:
    """Validate one catalog-declared tool-card input definition."""
    if not isinstance(value, dict):
        raise ValueError(f"catalog item {item_id!r} profile input must be an object")
    unsupported = set(value) - {
        "id",
        "label_i18n",
        "default",
        "type",
        "placeholder_i18n",
        "options",
        "visible_when",
    }
    if unsupported:
        raise ValueError(
            f"catalog item {item_id!r} profile input has unsupported fields: "
            f"{sorted(unsupported)}"
        )
    input_id = value.get("id")
    if not isinstance(input_id, str) or not input_id:
        raise ValueError(
            f"catalog item {item_id!r} profile input id must be a non-empty string"
        )
    if input_id in existing_ids:
        raise ValueError(
            f"catalog item {item_id!r} has duplicate profile input {input_id!r}"
        )
    label_i18n = value.get("label_i18n")
    if not isinstance(label_i18n, str) or not label_i18n:
        raise ValueError(
            f"catalog item {item_id!r} profile input {input_id!r} "
            "label_i18n must be a non-empty string"
        )
    default = value.get("default", "")
    if not isinstance(default, str):
        raise ValueError(
            f"catalog item {item_id!r} profile input {input_id!r} "
            "default must be a string"
        )
    if len(default) > MAX_TOOL_PROFILE_INPUT_LENGTH:
        raise ValueError(
            f"catalog item {item_id!r} profile input {input_id!r} "
            f"default exceeds {MAX_TOOL_PROFILE_INPUT_LENGTH} characters"
        )
    input_type = value.get("type", "text")
    if input_type not in {"text", "password", "select"}:
        raise ValueError(
            f"catalog item {item_id!r} profile input {input_id!r} "
            "type must be 'text', 'password', or 'select'"
        )
    options = value.get("options")
    if input_type == "select":
        value = dict(
            value,
            options=_normalize_profile_select_options(
                item_id, input_id, options, default
            ),
        )
    elif options is not None:
        raise ValueError(
            f"catalog item {item_id!r} profile input {input_id!r} "
            "options are only supported for type 'select'"
        )
    placeholder_i18n = value.get("placeholder_i18n")
    if placeholder_i18n is not None and (
        not isinstance(placeholder_i18n, str) or not placeholder_i18n
    ):
        raise ValueError(
            f"catalog item {item_id!r} profile input {input_id!r} "
            "placeholder_i18n must be a non-empty string"
        )
    visible_when = _normalize_visible_when(
        item_id,
        value.get("visible_when"),
        supported_states,
        field=f"profile input {input_id!r} visible_when",
    )
    if visible_when is not None:
        value = dict(value, visible_when=visible_when)
    return input_id, dict(value, default=default, type=input_type)


def _profile_input_contract(
    catalog: dict[str, Any],
    supported: dict[str, tuple[str, ...]],
) -> dict[str, dict[str, Any]]:
    """Return validated tool-card input definitions keyed by tool and input ID."""
    definitions: dict[str, dict[str, Any]] = {}
    for item in catalog["items"]:
        raw_inputs = item.get("profile_inputs", [])
        if not isinstance(raw_inputs, list):
            raise ValueError(
                f"catalog item {item['id']!r} profile_inputs must be a list"
            )
        if raw_inputs and item["type"] not in {"function", "hosted"}:
            raise ValueError(
                f"catalog item {item['id']!r} profile_inputs are only supported "
                "for Function and Hosted tools"
            )
        item_inputs: dict[str, Any] = {}
        for raw_input in raw_inputs:
            input_id, input_definition = _normalize_profile_input_definition(
                item["id"], raw_input, set(item_inputs), supported[item["id"]]
            )
            item_inputs[input_id] = input_definition
        if item_inputs:
            definitions[item["id"]] = item_inputs
    return definitions


def _disable_namespace_children(
    tools: dict[str, str], namespace_children: dict[str, tuple[str, ...]]
) -> dict[str, str]:
    """Force every child of a disabled Namespace to Disabled."""
    normalized = dict(tools)
    for namespace_id, child_ids in namespace_children.items():
        if normalized.get(namespace_id) == "disabled":
            for child_id in child_ids:
                normalized[child_id] = "disabled"
    return normalized


def _namespace_children_contract(
    catalog: dict[str, Any], supported: dict[str, tuple[str, ...]]
) -> dict[str, tuple[str, ...]]:
    """Validate and return the configured Namespace-to-child relationships."""
    namespace_children = {
        placement["namespace_id"]: tuple(placement["child_ids"])
        for placement in catalog.get("placements", {}).get("namespaces", [])
    }
    for namespace_id, child_ids in namespace_children.items():
        if namespace_id not in supported:
            raise ValueError(f"unknown Namespace catalog ID {namespace_id!r}")
        for child_id in child_ids:
            if child_id not in supported:
                raise ValueError(
                    f"Namespace {namespace_id!r} contains unknown child {child_id!r}"
                )
            if "disabled" not in supported[child_id]:
                raise ValueError(
                    f"Namespace child {child_id!r} must support the disabled state"
                )
    return namespace_children


def _apply_bundled_tool_overrides(
    field: str,
    tools: dict[str, str],
    overrides: Any,
    supported: dict[str, tuple[str, ...]],
    namespace_children: dict[str, tuple[str, ...]],
) -> dict[str, str]:
    """Validate bundled overrides and enforce Namespace child states."""
    if not isinstance(overrides, dict):
        raise ValueError(f"{field} must be an object")
    unknown_ids = sorted(set(overrides) - set(supported))
    if unknown_ids:
        raise ValueError(f"{field} contains unknown catalog IDs: {unknown_ids}")
    merged = dict(tools)
    for item_id, state in overrides.items():
        if state not in supported[item_id]:
            raise ValueError(
                f"{field}.{item_id} must be one of {list(supported[item_id])}"
            )
        merged[item_id] = state
    return _disable_namespace_children(merged, namespace_children)


@lru_cache(maxsize=1)
def tool_profile_contract() -> dict[str, Any]:
    """Return supported states and the immutable bundled profiles."""
    catalog = load_tool_catalog()
    policies = {policy["id"]: policy for policy in catalog["policies"]}
    supported: dict[str, tuple[str, ...]] = {}
    builtin: dict[str, str] = {}

    for item in catalog["items"]:
        item_id = item["id"]
        item_type = item["type"]
        if item_type == "custom_injection":
            supported[item_id] = ("disabled", "injected")
            builtin[item_id] = "injected"
            continue

        policy = policies[item["policy_id"]]
        if item_type == "namespace":
            supported[item_id] = tuple(
                policy.get("namespace_supported", ("disabled", "expanded"))
            )
            builtin[item_id] = (
                "disabled" if policy["default"] == "disabled" else "expanded"
            )
            continue

        states = tuple(policy["supported"])
        supported[item_id] = states
        builtin[item_id] = policy["default"]

    namespace_children = _namespace_children_contract(catalog, supported)

    builtin_profile = dict(catalog["builtin_profile"])
    builtin_overrides = builtin_profile.pop("tools", {})
    builtin = _apply_bundled_tool_overrides(
        "builtin_profile.tools",
        builtin,
        builtin_overrides,
        supported,
        namespace_children,
    )

    input_definitions = _profile_input_contract(catalog, supported)
    for item in catalog["items"]:
        description_visible_when = item.get("description_visible_when")
        if description_visible_when is None:
            continue
        if not item.get("description_i18n"):
            raise ValueError(
                f"catalog item {item['id']!r} description_visible_when requires "
                "description_i18n"
            )
        _normalize_visible_when(
            item["id"],
            description_visible_when,
            supported[item["id"]],
            field="description_visible_when",
        )

    profiles = [
        {
            **builtin_profile,
            "tools": dict(builtin),
            "inputs": {
                item_id: {
                    input_id: definition["default"]
                    for input_id, definition in item_inputs.items()
                }
                for item_id, item_inputs in input_definitions.items()
            },
        }
    ]
    for preset in catalog.get("preset_profiles", []):
        defaults = preset.get("defaults", {})
        overrides = preset.get("tools", {})
        tools: dict[str, str] = {}
        for item in catalog["items"]:
            item_id = item["id"]
            state = overrides.get(item_id, defaults.get(item["type"]))
            if state not in supported[item_id]:
                raise ValueError(
                    f"bundled profile {preset.get('id')!r} has unsupported state "
                    f"{state!r} for {item_id}"
                )
            tools[item_id] = state
        tools = _disable_namespace_children(tools, namespace_children)
        profiles.append(
            {
                "id": preset["id"],
                "name": preset["name"],
                "tools": tools,
                "inputs": {
                    item_id: {
                        input_id: definition["default"]
                        for input_id, definition in item_inputs.items()
                    }
                    for item_id, item_inputs in input_definitions.items()
                },
            }
        )

    return {
        "profiles": profiles,
        "supported": supported,
        "builtin": builtin,
        "input_definitions": input_definitions,
        "namespace_children": namespace_children,
        "readonly": {profile["id"]: profile for profile in profiles},
    }


def validate_tool_profile_name(value: Any, *, allow_readonly: bool = False) -> str:
    """Validate and return one persisted profile identifier."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("tool profile name must be a non-empty string")
    name = value.strip()
    if len(name) > MAX_TOOL_PROFILE_NAME_LENGTH:
        raise ValueError(
            f"tool profile name must be at most {MAX_TOOL_PROFILE_NAME_LENGTH} characters"
        )
    if name in tool_profile_contract()["readonly"] and not allow_readonly:
        raise ValueError(f"the bundled tool profile '{name}' is read-only")
    return name


def normalize_tool_profile_tools(value: Any, *, field: str) -> dict[str, str]:
    """Validate a complete tool-state mapping against the bundled catalog."""
    if not isinstance(value, dict):
        raise ValueError(f"{field}.tools must be an object")

    contract = tool_profile_contract()
    supported: dict[str, tuple[str, ...]] = contract["supported"]
    actual_ids = set(value)
    expected_ids = set(supported)
    missing = sorted(expected_ids - actual_ids)
    unknown = sorted(actual_ids - expected_ids)
    if missing:
        raise ValueError(f"{field}.tools is missing catalog IDs: {missing}")
    if unknown:
        raise ValueError(f"{field}.tools contains unknown catalog IDs: {unknown}")

    normalized: dict[str, str] = {}
    for item_id, state in value.items():
        if not isinstance(state, str) or state not in supported[item_id]:
            raise ValueError(
                f"{field}.tools.{item_id} must be one of {list(supported[item_id])}"
            )
        normalized[item_id] = state
    return _disable_namespace_children(normalized, contract["namespace_children"])


def normalize_tool_profile_inputs(
    value: Any, *, field: str
) -> dict[str, dict[str, str]]:
    """Validate and fill tool-card input values from the bundled defaults."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError(f"{field}.inputs must be an object")

    definitions: dict[str, dict[str, Any]] = tool_profile_contract()[
        "input_definitions"
    ]
    unknown_items = sorted(set(value) - set(definitions))
    if unknown_items:
        raise ValueError(
            f"{field}.inputs contains unknown catalog IDs: {unknown_items}"
        )

    normalized: dict[str, dict[str, str]] = {}
    for item_id, item_definitions in definitions.items():
        raw_item_values = value.get(item_id, {})
        if not isinstance(raw_item_values, dict):
            raise ValueError(f"{field}.inputs.{item_id} must be an object")
        unknown_inputs = sorted(set(raw_item_values) - set(item_definitions))
        if unknown_inputs:
            raise ValueError(
                f"{field}.inputs.{item_id} contains unknown input IDs: {unknown_inputs}"
            )
        normalized[item_id] = {}
        for input_id, definition in item_definitions.items():
            input_value = raw_item_values.get(input_id, definition["default"])
            if not isinstance(input_value, str):
                raise ValueError(
                    f"{field}.inputs.{item_id}.{input_id} must be a string"
                )
            if len(input_value) > MAX_TOOL_PROFILE_INPUT_LENGTH:
                raise ValueError(
                    f"{field}.inputs.{item_id}.{input_id} must be at most "
                    f"{MAX_TOOL_PROFILE_INPUT_LENGTH} characters"
                )
            if definition["type"] == "select" and input_value not in {
                option["value"] for option in definition["options"]
            }:
                raise ValueError(
                    f"{field}.inputs.{item_id}.{input_id} must be one of "
                    f"{[option['value'] for option in definition['options']]}"
                )
            normalized[item_id][input_id] = input_value
    return normalized


def normalize_tool_profile_documents(
    value: Any,
) -> dict[str, dict[str, Any]]:
    """Validate complete persisted Profile documents for Admin editing."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("config: 'tool_profiles' must be an object")

    profiles: dict[str, dict[str, Any]] = {}
    for raw_name, raw_profile in value.items():
        name = validate_tool_profile_name(raw_name)
        if not isinstance(raw_profile, dict):
            raise ValueError(f"config: tool_profiles.{name} must be an object")
        unsupported_fields = set(raw_profile) - {"tools", "inputs"}
        if unsupported_fields:
            raise ValueError(
                f"config: tool_profiles.{name} has unsupported fields: "
                f"{sorted(unsupported_fields)}"
            )
        field = f"config: tool_profiles.{name}"
        profiles[name] = {
            "tools": normalize_tool_profile_tools(
                raw_profile.get("tools"), field=field
            ),
            "inputs": normalize_tool_profile_inputs(
                raw_profile.get("inputs"), field=field
            ),
        }
    return profiles


def normalize_tool_profiles(value: Any) -> dict[str, dict[str, str]]:
    """Validate user-defined profiles from the top-level config object."""
    return {
        name: profile["tools"]
        for name, profile in normalize_tool_profile_documents(value).items()
    }


def normalize_tool_profile_input_overrides(
    value: Any,
) -> dict[str, dict[str, dict[str, str]]]:
    """Validate input-only overrides for immutable bundled Profiles."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("config: 'tool_profile_input_overrides' must be an object")

    readonly = tool_profile_contract()["readonly"]
    overrides: dict[str, dict[str, dict[str, str]]] = {}
    for raw_name, raw_inputs in value.items():
        name = validate_tool_profile_name(raw_name, allow_readonly=True)
        if name not in readonly:
            raise ValueError(
                "config: tool_profile_input_overrides may only contain bundled "
                f"Profiles; got '{name}'"
            )
        overrides[name] = normalize_tool_profile_inputs(
            raw_inputs,
            field=f"config: tool_profile_input_overrides.{name}",
        )
    return overrides


def resolve_tool_profile(
    name: str,
    profiles: dict[str, dict[str, str]],
) -> dict[str, str]:
    """Resolve a built-in or user profile to an independent state mapping."""
    readonly = tool_profile_contract()["readonly"]
    if name in readonly:
        return dict(readonly[name]["tools"])
    try:
        return dict(profiles[name])
    except KeyError as exc:
        raise ValueError(f"unknown tool profile '{name}'") from exc


def resolve_tool_profile_inputs(
    name: str,
    profiles: dict[str, dict[str, Any]],
    input_overrides: dict[str, dict[str, dict[str, str]]] | None = None,
) -> dict[str, dict[str, str]]:
    """Resolve persisted tool-card input values for one Profile."""
    readonly = tool_profile_contract()["readonly"]
    profile = readonly.get(name, profiles.get(name))
    if profile is None:
        raise ValueError(f"unknown tool profile '{name}'")
    if name in readonly and input_overrides and name in input_overrides:
        return {
            item_id: dict(values) for item_id, values in input_overrides[name].items()
        }
    return {
        item_id: dict(values) for item_id, values in profile.get("inputs", {}).items()
    }


def validate_tool_profile_reference(
    value: Any,
    profiles: dict[str, dict[str, str]],
    *,
    field: str,
) -> str:
    """Validate a model-group profile reference."""
    name = validate_tool_profile_name(value, allow_readonly=True)
    if name not in tool_profile_contract()["readonly"] and name not in profiles:
        raise ValueError(f"{field} references unknown tool profile '{name}'")
    return name


def tool_profiles_for_admin(
    profiles: dict[str, dict[str, Any]],
    input_overrides: dict[str, dict[str, dict[str, str]]] | None = None,
) -> list[dict[str, Any]]:
    """Build the ordered public representation consumed by the Admin UI."""
    contract = tool_profile_contract()
    result = [
        {
            "id": profile["id"],
            "name": profile["name"],
            "tools": dict(profile["tools"]),
            "inputs": resolve_tool_profile_inputs(
                profile["id"], profiles, input_overrides
            ),
            "readonly": True,
        }
        for profile in contract["profiles"]
    ]
    result.extend(
        {
            "id": name,
            "name": name,
            "tools": dict(profile["tools"]),
            "inputs": {
                item_id: dict(values) for item_id, values in profile["inputs"].items()
            },
            "readonly": False,
        }
        for name, profile in sorted(profiles.items())
    )
    return result


@lru_cache(maxsize=1)
def tool_catalog_lookups() -> dict[str, Any]:
    """Return catalog indexes used by request-time policy application."""
    catalog = load_tool_catalog()
    items = {item["id"]: item for item in catalog["items"]}
    by_type_name = {
        (item["type"], item["name"]): item["id"] for item in catalog["items"]
    }
    namespace_children: dict[tuple[str, str], str] = {}
    for placement in catalog["placements"]["namespaces"]:
        namespace = items[placement["namespace_id"]]["name"]
        for child_id in placement["child_ids"]:
            namespace_children[(namespace, items[child_id]["name"])] = child_id
    return {
        "items": items,
        "by_type_name": by_type_name,
        "namespace_children": namespace_children,
    }


def route_tool_state(route: Any, item_id: str, default: str = "passthrough") -> str:
    """Return one effective state, retaining fixed behavior for bare test routes."""
    profile = getattr(route, "tool_profile", None)
    if not profile:
        return default
    return profile.get(item_id, default)


def modified_tool_names(route: Any) -> set[str] | None:
    """Return catalog names whose Chat definitions may be modified."""
    if not getattr(route, "tool_profile", None):
        return None
    return {
        item["name"]
        for item_id, item in tool_catalog_lookups()["items"].items()
        if item["type"] not in {"namespace", "custom_injection"}
        and route_tool_state(route, item_id) == "modified"
    }
