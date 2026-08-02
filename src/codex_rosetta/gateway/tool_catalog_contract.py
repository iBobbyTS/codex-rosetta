"""Compile and validate the immutable model-visible tool catalog contract."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

CATALOG_SCHEMA_VERSION = 7

TOOL_API_TYPES = frozenset({"chat", "responses", "anthropic", "google"})
TOOL_STATES = frozenset({"disabled", "passthrough", "modified", "expanded", "injected"})
RUNTIME_ADAPTER_IDS = frozenset(
    {
        "localized_file_tool",
        "send_line",
        "deferred_tool_search",
        "deferred_tool_read",
        "deferred_tool_invoke",
        "tool_search_chat_bridge",
        "view_image",
        "web_run",
    }
)
SOURCE_REGISTRATION_KINDS = frozenset(
    {
        "static",
        "generated",
        "hosted",
        "hidden",
        "extension",
        "rosetta_runtime",
        "compatibility",
        "dynamic",
    }
)
SOURCE_TOOL_SPEC_KINDS = frozenset(
    {
        "function",
        "custom",
        "namespace",
        "hosted",
        "generated",
        "dynamic_function",
        "dynamic_namespace",
    }
)
SOURCE_EXPOSURES = frozenset(
    {
        "Direct",
        "Deferred",
        "DirectModelOnly",
        "Hidden",
        "Conditional",
        "Dynamic",
        "Rosetta",
    }
)
SURFACE_STABILITIES = frozenset({"stable", "conditional", "runtime_dynamic"})
SURFACE_DELIVERIES = frozenset({"eager", "deferred", "hidden"})
DEFERRED_ADAPTER_IDS = frozenset(
    {"nested_exec", "direct_function", "namespace_function"}
)
DYNAMIC_EXPOSURE_RULES = frozenset(
    {"source_declared", "search_tool_conditional", "extension_declared"}
)
DELIVERY_FIELDS = frozenset(
    {
        "localized_native_source",
        "eager_only",
        "detail_input",
        "deferred_guidance_marker",
        "modified_requires_deferred_exec_guidance",
        "modified_removes_source",
        "passthrough_chat_projects_live_definition",
        "direct_function_wins",
        "description_projection_adapters",
        "exec_projection",
        "passthrough_projection",
    }
)
PREDICATE_FIELDS = frozenset(
    {
        "source_tool_exists",
        "dependency_effective",
        "target_api",
        "model_modality",
        "runtime_capability",
        "deferred_exec_guidance_exists",
    }
)
ITEM_FIELDS = frozenset(
    {
        "id",
        "name",
        "type",
        "policy_id",
        "aliases",
        "codex_placement",
        "default_expanded",
        "default_namespace",
        "description_i18n",
        "description_visible_when",
        "exec_projection",
        "internal_container_when_disabled",
        "namespace_configurable",
        "namespace_id",
        "note_i18n",
        "note_visible_when",
        "profile_inputs",
        "profile_mutations",
        "stable_name",
        "state_descriptions_i18n",
        "ui_hidden",
        "catalog_definition",
        "runtime_adapters",
        "availability",
        "delivery",
        "description_variants",
        "capability_projection",
        "history_aliases",
        "state_api_types",
        "source_binding",
        "surface_policy",
    }
)


@dataclass(frozen=True)
class CompiledToolCatalog:
    """Immutable indexes and validated declarations compiled from catalog v7."""

    raw: Mapping[str, Any]
    items: Mapping[str, Mapping[str, Any]]
    by_type_name: Mapping[tuple[str, str], str]
    history_aliases: Mapping[str, str]
    dependencies: Mapping[str, tuple[str, ...]]
    source_registrations: Mapping[str, Mapping[str, Any]]
    dynamic_families: Mapping[str, Mapping[str, Any]]


def _freeze(value: Any) -> Any:
    """Recursively freeze JSON-like catalog data."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _require_unique_strings(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError(f"{field} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} contains duplicate values")
    return tuple(value)


def _validate_condition(value: Any, *, field: str) -> None:
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError(f"{field} must contain exactly one condition operator")
    operator, operand = next(iter(value.items()))
    if operator in {"all_of", "any_of"}:
        if not isinstance(operand, list) or not operand:
            raise ValueError(f"{field}.{operator} must be a non-empty list")
        for index, child in enumerate(operand):
            _validate_condition(child, field=f"{field}.{operator}[{index}]")
        return
    if operator not in PREDICATE_FIELDS:
        raise ValueError(f"{field} contains unsupported predicate {operator!r}")
    if operator == "deferred_exec_guidance_exists":
        if operand is not True:
            raise ValueError(f"{field}.{operator} must be true")
        return
    values = (operand,) if isinstance(operand, str) else operand
    if (
        not isinstance(values, (list, tuple))
        or not values
        or any(not isinstance(item, str) or not item for item in values)
    ):
        raise ValueError(f"{field}.{operator} must be a string or string list")
    if operator == "target_api" and set(values) - TOOL_API_TYPES:
        raise ValueError(f"{field}.{operator} contains unsupported API types")


def _validate_state_api_types(
    item_id: str, value: Any, supported_states: frozenset[str]
) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f"catalog item {item_id!r} state_api_types must be an object")
    unknown_states = set(value) - supported_states
    if unknown_states:
        raise ValueError(
            f"catalog item {item_id!r} state_api_types contains unsupported states: "
            f"{sorted(unknown_states)}"
        )
    missing_states = supported_states - set(value)
    if missing_states:
        raise ValueError(
            f"catalog item {item_id!r} state_api_types is missing states: "
            f"{sorted(missing_states)}"
        )
    for state, api_types in value.items():
        normalized = _require_unique_strings(
            api_types, field=f"catalog item {item_id!r} state_api_types.{state}"
        )
        unknown_api_types = set(normalized) - TOOL_API_TYPES
        if unknown_api_types:
            raise ValueError(
                f"catalog item {item_id!r} state_api_types.{state} contains "
                f"unsupported API types: {sorted(unknown_api_types)}"
            )


def _validate_catalog_definition(item: dict[str, Any]) -> None:
    item_id = item["id"]
    definition = item.get("catalog_definition")
    if definition is not None:
        if not isinstance(definition, dict) or set(definition) - {
            "type",
            "function",
            "strict",
        }:
            raise ValueError(f"catalog item {item_id!r} catalog_definition is invalid")
        function = definition.get("function")
        if definition.get("type") != "function" or not isinstance(function, dict):
            raise ValueError(
                f"catalog item {item_id!r} catalog_definition must be a function"
            )
        if function.get("name") != item["name"]:
            raise ValueError(
                f"catalog item {item_id!r} catalog_definition name mismatch"
            )
        if not isinstance(function.get("description"), str) or not isinstance(
            function.get("parameters"), dict
        ):
            raise ValueError(
                f"catalog item {item_id!r} catalog_definition requires description "
                "and parameters"
            )
    if item["type"] == "custom_injection" and definition is None:
        raise ValueError(
            f"catalog injection item {item_id!r} requires catalog_definition"
        )


def _validate_delivery(item: dict[str, Any]) -> None:
    item_id = item["id"]
    delivery = item.get("delivery")
    if delivery is None:
        return
    if not isinstance(delivery, dict) or set(delivery) - DELIVERY_FIELDS:
        raise ValueError(f"catalog item {item_id!r} delivery is invalid")
    for projection_field in ("exec_projection", "passthrough_projection"):
        _validate_delivery_projection(item_id, delivery, projection_field)
    projection_adapters = delivery.get("description_projection_adapters")
    if projection_adapters is None:
        return
    normalized = _require_unique_strings(
        projection_adapters,
        field=f"catalog item {item_id!r} delivery.description_projection_adapters",
    )
    unknown = set(normalized) - RUNTIME_ADAPTER_IDS
    if unknown:
        raise ValueError(
            f"catalog item {item_id!r} delivery references unknown description "
            f"projection adapters: {sorted(unknown)}"
        )


def _validate_delivery_projection(
    item_id: str, delivery: dict[str, Any], field: str
) -> None:
    projection = delivery.get(field)
    if projection is None:
        return
    allowed = {
        "chat_name",
        "nested_name",
        "input_mode",
        "native_item_type",
        "execution",
    }
    if not isinstance(projection, dict) or set(projection) - allowed:
        raise ValueError(f"catalog item {item_id!r} delivery.{field} is invalid")
    if not isinstance(projection.get("chat_name"), str) or not isinstance(
        projection.get("input_mode"), str
    ):
        raise ValueError(f"catalog item {item_id!r} delivery.{field} is incomplete")


def _validate_description_variants(item: dict[str, Any]) -> None:
    item_id = item["id"]
    allowed = {
        "when",
        "append",
        "replace",
        "drop_lines_containing",
        "replace_text",
        "target_parameter",
    }
    for index, variant in enumerate(item.get("description_variants", [])):
        if not isinstance(variant, dict) or set(variant) - allowed:
            raise ValueError(
                f"catalog item {item_id!r} description_variants[{index}] is invalid"
            )
        if "when" not in variant:
            raise ValueError(
                f"catalog item {item_id!r} description_variants[{index}] needs when"
            )
        _validate_condition(
            variant["when"],
            field=f"catalog item {item_id!r} description_variants[{index}].when",
        )
        _validate_description_variant_values(item_id, index, variant)


def _validate_description_variant_values(
    item_id: str, index: int, variant: dict[str, Any]
) -> None:
    target_parameter = variant.get("target_parameter")
    if target_parameter is not None and (
        not isinstance(target_parameter, str) or not target_parameter
    ):
        raise ValueError(
            f"catalog item {item_id!r} description variant target is invalid"
        )
    replacement = variant.get("replace_text")
    if replacement is not None and (
        not isinstance(replacement, dict)
        or set(replacement) != {"from", "to"}
        or not all(isinstance(value, str) for value in replacement.values())
    ):
        raise ValueError(
            f"catalog item {item_id!r} description_variants[{index}] replacement is invalid"
        )


def _validate_runtime_fields(item: dict[str, Any]) -> tuple[str, ...]:
    item_id = item["id"]
    adapters = _require_unique_strings(
        item.get("runtime_adapters", []),
        field=f"catalog item {item_id!r} runtime_adapters",
    )
    unknown_adapters = set(adapters) - RUNTIME_ADAPTER_IDS
    if unknown_adapters:
        raise ValueError(
            f"catalog item {item_id!r} references unknown runtime adapters: "
            f"{sorted(unknown_adapters)}"
        )
    if "availability" in item:
        _validate_condition(
            item["availability"], field=f"catalog item {item_id!r} availability"
        )
    _validate_catalog_definition(item)
    _validate_delivery(item)
    capability_projection = item.get("capability_projection")
    if capability_projection is not None and not isinstance(
        capability_projection, dict
    ):
        raise ValueError(
            f"catalog item {item_id!r} capability_projection must be an object"
        )
    _validate_description_variants(item)
    return adapters


def _validate_source_binding(item: dict[str, Any]) -> tuple[str, ...]:
    item_id = item["id"]
    binding = item.get("source_binding")
    if not isinstance(binding, dict) or set(binding) != {
        "origin",
        "registration_ids",
    }:
        raise ValueError(
            f"catalog item {item_id!r} source_binding must contain origin and registration_ids"
        )
    if binding.get("origin") not in {
        "codex_source",
        "rosetta_runtime",
        "compatibility_contract",
    }:
        raise ValueError(f"catalog item {item_id!r} source_binding origin is invalid")
    return _require_unique_strings(
        binding.get("registration_ids"),
        field=f"catalog item {item_id!r} source_binding.registration_ids",
    )


def _validate_surface_policy(item: dict[str, Any]) -> None:
    item_id = item["id"]
    policy = item.get("surface_policy")
    if not isinstance(policy, dict) or set(policy) - {
        "stability",
        "initial_delivery",
        "deferred_adapter",
    }:
        raise ValueError(f"catalog item {item_id!r} surface_policy is invalid")
    if policy.get("stability") not in SURFACE_STABILITIES:
        raise ValueError(f"catalog item {item_id!r} surface stability is invalid")
    if policy.get("initial_delivery") not in SURFACE_DELIVERIES:
        raise ValueError(f"catalog item {item_id!r} initial delivery is invalid")
    adapter = policy.get("deferred_adapter")
    if adapter is not None and adapter not in DEFERRED_ADAPTER_IDS:
        raise ValueError(f"catalog item {item_id!r} deferred adapter is invalid")


def _validate_dynamic_family(raw: Any, existing_ids: set[str]) -> dict[str, Any]:
    fields = {
        "id",
        "source_path",
        "source_symbol",
        "tool_spec_kinds",
        "exposure_rule",
        "deferred_adapters",
        "name_pattern",
    }
    if not isinstance(raw, dict) or set(raw) - fields:
        raise ValueError("dynamic family contains unsupported fields")
    family_id = raw.get("id")
    if not isinstance(family_id, str) or not family_id:
        raise ValueError("dynamic family id must be a non-empty string")
    if family_id in existing_ids:
        raise ValueError(f"duplicate dynamic family id {family_id!r}")
    for field in ("source_path", "source_symbol"):
        if not isinstance(raw.get(field), str) or not raw[field]:
            raise ValueError(f"dynamic family {family_id!r} {field} is invalid")
    spec_kinds = _require_unique_strings(
        raw.get("tool_spec_kinds"),
        field=f"dynamic family {family_id!r} tool_spec_kinds",
    )
    if set(spec_kinds) - SOURCE_TOOL_SPEC_KINDS:
        raise ValueError(f"dynamic family {family_id!r} tool spec kinds are invalid")
    if raw.get("exposure_rule") not in DYNAMIC_EXPOSURE_RULES:
        raise ValueError(f"dynamic family {family_id!r} exposure rule is invalid")
    adapters = _require_unique_strings(
        raw.get("deferred_adapters"),
        field=f"dynamic family {family_id!r} deferred_adapters",
    )
    if set(adapters) - DEFERRED_ADAPTER_IDS:
        raise ValueError(f"dynamic family {family_id!r} deferred adapters are invalid")
    pattern = raw.get("name_pattern")
    if pattern is not None:
        if not isinstance(pattern, str) or not pattern:
            raise ValueError(f"dynamic family {family_id!r} name_pattern is invalid")
        try:
            re.compile(pattern)
        except Exception as exc:
            raise ValueError(
                f"dynamic family {family_id!r} name_pattern is invalid"
            ) from exc
    return raw


def _validate_source_registration(
    raw: Any,
    *,
    existing_ids: set[str],
    item_ids: set[str],
    family_ids: set[str],
) -> dict[str, Any]:
    fields = {
        "id",
        "source_path",
        "source_symbol",
        "registration_kind",
        "tool_spec_kind",
        "exposure",
        "conditions",
        "item_id",
        "family_id",
    }
    if not isinstance(raw, dict) or set(raw) - fields:
        raise ValueError("source registration contains unsupported fields")
    registration_id = raw.get("id")
    if not isinstance(registration_id, str) or not registration_id:
        raise ValueError("source registration id must be a non-empty string")
    if registration_id in existing_ids:
        raise ValueError(f"duplicate source registration id {registration_id!r}")
    for field in ("source_path", "source_symbol"):
        if not isinstance(raw.get(field), str) or not raw[field]:
            raise ValueError(
                f"source registration {registration_id!r} {field} is invalid"
            )
    if raw.get("registration_kind") not in SOURCE_REGISTRATION_KINDS:
        raise ValueError(
            f"source registration {registration_id!r} registration kind is invalid"
        )
    if raw.get("tool_spec_kind") not in SOURCE_TOOL_SPEC_KINDS:
        raise ValueError(
            f"source registration {registration_id!r} tool spec kind is invalid"
        )
    if raw.get("exposure") not in SOURCE_EXPOSURES:
        raise ValueError(f"source registration {registration_id!r} exposure is invalid")
    _require_unique_strings(
        raw.get("conditions", []),
        field=f"source registration {registration_id!r} conditions",
    )
    item_id = raw.get("item_id")
    family_id = raw.get("family_id")
    if (item_id is None) == (family_id is None):
        raise ValueError(
            f"source registration {registration_id!r} must reference exactly one item or family"
        )
    if item_id is not None and item_id not in item_ids:
        raise ValueError(
            f"source registration {registration_id!r} references unknown item {item_id!r}"
        )
    if family_id is not None and family_id not in family_ids:
        raise ValueError(
            f"source registration {registration_id!r} references unknown family {family_id!r}"
        )
    return raw


def _validate_dependencies(
    items: dict[str, dict[str, Any]], dependencies: dict[str, tuple[str, ...]]
) -> None:
    known = set(items)
    for item_id, item_dependencies in dependencies.items():
        unknown = set(item_dependencies) - known
        if unknown:
            raise ValueError(
                f"catalog item {item_id!r} references unknown dependencies: "
                f"{sorted(unknown)}"
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(item_id: str) -> None:
        if item_id in visiting:
            raise ValueError(f"catalog dependency cycle contains {item_id!r}")
        if item_id in visited:
            return
        visiting.add(item_id)
        for dependency in dependencies.get(item_id, ()):
            visit(dependency)
        visiting.remove(item_id)
        visited.add(item_id)

    for item_id in items:
        visit(item_id)


def _condition_dependencies(value: Any) -> tuple[str, ...]:
    if not isinstance(value, dict) or len(value) != 1:
        return ()
    operator, operand = next(iter(value.items()))
    if operator in {"all_of", "any_of"}:
        if not isinstance(operand, list):
            return ()
        return tuple(
            dependency
            for child in operand
            for dependency in _condition_dependencies(child)
        )
    if operator != "dependency_effective":
        return ()
    if isinstance(operand, str):
        return (operand,)
    if not isinstance(operand, list):
        return ()
    return tuple(item for item in operand if isinstance(item, str))


def _catalog_items_and_policies(
    catalog: dict[str, Any],
) -> tuple[list[Any], dict[Any, Any]]:
    metadata = catalog.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("schema_version") != CATALOG_SCHEMA_VERSION
    ):
        raise ValueError(
            f"tool catalog schema_version must be {CATALOG_SCHEMA_VERSION}"
        )
    raw_items = catalog.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("tool catalog items must be a list")
    policies = {
        policy.get("id"): policy
        for policy in catalog.get("policies", [])
        if isinstance(policy, dict) and isinstance(policy.get("id"), str)
    }
    return raw_items, policies


def _catalog_item_supported_states(
    raw_item: dict[str, Any], policies: dict[Any, Any]
) -> frozenset[str]:
    item_id = raw_item["id"]
    item_type = raw_item["type"]
    policy = policies.get(raw_item.get("policy_id"))
    if item_type == "custom_injection":
        supported = frozenset({"disabled", "injected"})
    elif not isinstance(policy, dict):
        raise ValueError(f"catalog item {item_id!r} references unknown policy")
    else:
        supported = frozenset(
            policy.get("namespace_supported", policy.get("supported", []))
            if item_type == "namespace"
            else policy.get("supported", [])
        )
    if not supported or supported - TOOL_STATES:
        raise ValueError(f"catalog item {item_id!r} has invalid supported states")
    return supported


def _validated_catalog_item(
    raw_item: Any,
    policies: dict[Any, Any],
    existing_ids: set[str],
) -> tuple[dict[str, Any], tuple[str, str], tuple[str, str, str | None]]:
    if not isinstance(raw_item, dict):
        raise ValueError("tool catalog items must be objects")
    unknown_fields = set(raw_item) - ITEM_FIELDS
    if unknown_fields:
        raise ValueError(
            f"catalog item has unsupported fields: {sorted(unknown_fields)}"
        )
    item_id, name, item_type = (
        raw_item.get("id"),
        raw_item.get("name"),
        raw_item.get("type"),
    )
    if not all(
        isinstance(value, str) and value for value in (item_id, name, item_type)
    ):
        raise ValueError("catalog item id, name, and type must be non-empty strings")
    if item_id in existing_ids:
        raise ValueError(f"duplicate catalog item id {item_id!r}")
    supported_states = _catalog_item_supported_states(raw_item, policies)
    _validate_state_api_types(
        item_id, raw_item.get("state_api_types"), supported_states
    )
    _validate_runtime_fields(raw_item)
    _validate_source_binding(raw_item)
    _validate_surface_policy(raw_item)
    return raw_item, (item_type, name), (item_type, name, raw_item.get("namespace_id"))


def _register_history_aliases(
    raw_item: dict[str, Any], aliases: dict[str, str]
) -> None:
    item_id = raw_item["id"]
    name = raw_item["name"]
    history_aliases = _require_unique_strings(
        raw_item.get("history_aliases", []),
        field=f"catalog item {item_id!r} history_aliases",
    )
    for alias in history_aliases:
        if alias in aliases or alias == name:
            raise ValueError(f"duplicate catalog history alias {alias!r}")
        aliases[alias] = item_id


def _compile_source_registrations(
    catalog: dict[str, Any],
    *,
    items: dict[str, dict[str, Any]],
    families: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    raw_registrations = catalog.get("source_registrations")
    if not isinstance(raw_registrations, list):
        raise ValueError("tool catalog source_registrations must be a list")
    registrations: dict[str, dict[str, Any]] = {}
    for raw_registration in raw_registrations:
        registration = _validate_source_registration(
            raw_registration,
            existing_ids=set(registrations),
            item_ids=set(items),
            family_ids=set(families),
        )
        registrations[registration["id"]] = copy.deepcopy(registration)

    referenced_registrations: set[str] = set()
    for item_id, item in items.items():
        registration_ids = _validate_source_binding(item)
        for registration_id in registration_ids:
            registration = registrations.get(registration_id)
            if registration is None:
                raise ValueError(
                    f"catalog item {item_id!r} references unknown source registration {registration_id!r}"
                )
            if registration.get("item_id") != item_id:
                raise ValueError(
                    f"catalog item {item_id!r} source registration {registration_id!r} points elsewhere"
                )
            if registration_id in referenced_registrations:
                raise ValueError(
                    f"source registration {registration_id!r} is bound more than once"
                )
            referenced_registrations.add(registration_id)

    item_registration_ids = {
        registration_id
        for registration_id, registration in registrations.items()
        if registration.get("item_id") is not None
    }
    if referenced_registrations != item_registration_ids:
        missing = sorted(item_registration_ids - referenced_registrations)
        raise ValueError(f"unbound item source registrations: {missing}")

    family_registration_ids = {
        str(registration["family_id"])
        for registration in registrations.values()
        if registration.get("family_id") is not None
    }
    missing_families = set(families) - family_registration_ids
    if missing_families:
        raise ValueError(
            f"dynamic families without source registrations: {sorted(missing_families)}"
        )
    return registrations


def compile_tool_catalog(catalog: dict[str, Any]) -> CompiledToolCatalog:
    """Validate catalog schema v7 and return immutable runtime indexes."""
    if not isinstance(catalog, dict):
        raise ValueError("tool catalog must be an object")
    raw_items, policies = _catalog_items_and_policies(catalog)

    items: dict[str, dict[str, Any]] = {}
    by_type_name: dict[tuple[str, str], str] = {}
    ambiguous_type_names: set[tuple[str, str]] = set()
    qualified_identities: set[tuple[str, str, str | None]] = set()
    aliases: dict[str, str] = {}
    dependencies: dict[str, tuple[str, ...]] = {}
    for raw_item in raw_items:
        raw_item, identity, qualified_identity = _validated_catalog_item(
            raw_item, policies, set(items)
        )
        item_id = raw_item["id"]
        if qualified_identity in qualified_identities:
            raise ValueError(f"duplicate catalog tool identity {qualified_identity!r}")
        _register_history_aliases(raw_item, aliases)
        item_dependencies = tuple(
            dict.fromkeys(_condition_dependencies(raw_item.get("availability")))
        )
        dependencies[item_id] = item_dependencies
        items[item_id] = copy.deepcopy(raw_item)
        qualified_identities.add(qualified_identity)
        if identity in by_type_name:
            ambiguous_type_names.add(identity)
            by_type_name.pop(identity, None)
        elif identity not in ambiguous_type_names:
            by_type_name[identity] = item_id

    _validate_dependencies(items, dependencies)

    raw_families = catalog.get("dynamic_families")
    if not isinstance(raw_families, list):
        raise ValueError("tool catalog dynamic_families must be a list")
    families: dict[str, dict[str, Any]] = {}
    for raw_family in raw_families:
        family = _validate_dynamic_family(raw_family, set(families))
        families[family["id"]] = copy.deepcopy(family)

    registrations = _compile_source_registrations(
        catalog,
        items=items,
        families=families,
    )

    return CompiledToolCatalog(
        raw=_freeze(copy.deepcopy(catalog)),
        items=MappingProxyType(
            {item_id: _freeze(item) for item_id, item in items.items()}
        ),
        by_type_name=MappingProxyType(dict(by_type_name)),
        history_aliases=MappingProxyType(dict(aliases)),
        dependencies=MappingProxyType(dict(dependencies)),
        source_registrations=MappingProxyType(
            {
                registration_id: _freeze(registration)
                for registration_id, registration in registrations.items()
            }
        ),
        dynamic_families=MappingProxyType(
            {family_id: _freeze(family) for family_id, family in families.items()}
        ),
    )
