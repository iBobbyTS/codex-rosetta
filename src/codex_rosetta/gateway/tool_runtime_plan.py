"""Pure catalog-driven planning for model-visible tool adaptation."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .tool_profiles import tool_profile_contract


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return copy.deepcopy(value)


@dataclass(frozen=True)
class ToolPlanAction:
    """One non-sensitive catalog decision for request adaptation and tracing."""

    item_id: str
    action: str
    reason: str


@dataclass(frozen=True)
class ToolRuntimePlan:
    """Immutable result of evaluating one request against the tool catalog."""

    catalog_version: str
    bypass: bool
    effective_items: frozenset[str]
    remove_names: frozenset[str]
    definitions: Mapping[str, dict[str, Any]]
    adapter_bindings: Mapping[str, tuple[str, ...]]
    actions: tuple[ToolPlanAction, ...]
    source_names: frozenset[str]
    deferred_exec_guidance: bool

    def trace_summary(self) -> dict[str, Any]:
        """Return a bounded summary without schemas, prompts, or credentials."""
        return {
            "catalog_version": self.catalog_version,
            "bypass": self.bypass,
            "actions": [
                {
                    "item_id": action.item_id,
                    "action": action.action,
                    "reason": action.reason,
                }
                for action in self.actions
            ],
        }


@dataclass(frozen=True)
class _PlanContext:
    catalog: Any
    contract: dict[str, Any]
    target_api: str
    source_names: frozenset[str]
    direct_function_names: frozenset[str]
    deferred_guidance: bool
    modalities: frozenset[str]
    capabilities: frozenset[str]
    states: Mapping[str, str]


def _target_api(route: Any) -> str:
    provider = getattr(route, "target_provider", "")
    return {
        "openai_chat": "chat",
        "open_chat": "chat",
        "openai_responses": "responses",
        "open_responses": "responses",
        "anthropic": "anthropic",
        "google": "google",
        "google_genai": "google",
    }.get(provider, str(provider))


def _tool_identity(tool: Any) -> tuple[str | None, str | None]:
    if not isinstance(tool, dict):
        return None, None
    tool_type = tool.get("type")
    function = tool.get("function")
    if tool_type == "function" and isinstance(function, dict):
        name = function.get("name")
        return tool_type, name if isinstance(name, str) else None
    name = tool.get("name")
    if isinstance(name, str):
        return tool_type if isinstance(tool_type, str) else None, name
    if isinstance(tool_type, str):
        return tool_type, tool_type
    return None, None


def _source_tools(body: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    found: list[tuple[str, str]] = []

    def walk(value: Any, *, parent_key: str | None = None) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, parent_key=key)
            return
        if not isinstance(value, list):
            return
        if parent_key in {"tools", "additional_tools"}:
            for tool in value:
                tool_type, name = _tool_identity(tool)
                if tool_type and name:
                    found.append((tool_type, name))
        for child in value:
            walk(child)

    walk(body)
    return tuple(dict.fromkeys(found))


def _deferred_guidance_exists(body: dict[str, Any], marker: str) -> bool:
    def walk(value: Any) -> bool:
        if isinstance(value, dict):
            if value.get("description") and marker in str(value["description"]):
                return True
            return any(walk(child) for child in value.values())
        if isinstance(value, list):
            return any(walk(child) for child in value)
        return False

    return walk(body)


def _model_modalities(route: Any) -> frozenset[str]:
    modalities = getattr(route, "input_modalities", None)
    if not modalities:
        return frozenset({"unknown"})
    return frozenset(str(modality) for modality in modalities)


def _condition_matches(
    condition: Any,
    *,
    source_names: frozenset[str],
    effective: Mapping[str, bool],
    target_api: str,
    modalities: frozenset[str],
    capabilities: frozenset[str],
    deferred_guidance: bool,
) -> bool:
    operator, operand = next(iter(condition.items()))
    if operator == "all_of":
        return all(
            _condition_matches(
                child,
                source_names=source_names,
                effective=effective,
                target_api=target_api,
                modalities=modalities,
                capabilities=capabilities,
                deferred_guidance=deferred_guidance,
            )
            for child in operand
        )
    if operator == "any_of":
        return any(
            _condition_matches(
                child,
                source_names=source_names,
                effective=effective,
                target_api=target_api,
                modalities=modalities,
                capabilities=capabilities,
                deferred_guidance=deferred_guidance,
            )
            for child in operand
        )
    if operator == "deferred_exec_guidance_exists":
        return deferred_guidance
    values = {operand} if isinstance(operand, str) else set(operand or [])
    if operator == "source_tool_exists":
        return bool(values & source_names)
    if operator == "dependency_effective":
        return all(effective.get(item_id, False) for item_id in values)
    if operator == "target_api":
        return target_api in values
    if operator == "model_modality":
        return bool(values & modalities)
    if operator == "runtime_capability":
        return values <= capabilities
    raise ValueError(f"unsupported compiled catalog predicate {operator!r}")


def _apply_description_variants(
    definition: dict[str, Any],
    variants: Any,
    **context: Any,
) -> dict[str, Any]:
    adapted = copy.deepcopy(definition)
    function = adapted.get("function")
    if not isinstance(function, dict):
        return adapted
    description = function.get("description")
    if not isinstance(description, str):
        return adapted
    for variant in variants or ():
        if not _condition_matches(variant["when"], **context):
            continue
        if isinstance(variant.get("replace"), str):
            description = variant["replace"]
        if isinstance(variant.get("append"), str):
            description = f"{description.rstrip()} {variant['append'].strip()}"
        replacement = variant.get("replace_text")
        if isinstance(replacement, Mapping):
            source = replacement.get("from")
            target = replacement.get("to")
            if not isinstance(source, str) or source not in description:
                raise ValueError("catalog description replacement source is missing")
            if not isinstance(target, str):
                raise ValueError("catalog description replacement target is invalid")
            description = description.replace(source, target)
        drops = variant.get("drop_lines_containing", ())
        if drops:
            description = "\n".join(
                line
                for line in description.splitlines()
                if not any(marker in line for marker in drops)
            )
    function["description"] = description
    return adapted


def render_catalog_definition(
    item_id: str,
    *,
    effective_items: frozenset[str] = frozenset(),
    source_names: frozenset[str] = frozenset(),
    target_api: str = "chat",
    modalities: frozenset[str] = frozenset({"unknown"}),
    capabilities: frozenset[str] = frozenset(),
    deferred_guidance: bool = False,
) -> dict[str, Any]:
    """Render one catalog definition with its declarative description variants."""
    item = tool_profile_contract()["catalog"].items[item_id]
    definition = item.get("catalog_definition")
    if definition is None:
        raise ValueError(f"catalog item {item_id!r} has no catalog_definition")
    return _apply_description_variants(
        _thaw(definition),
        item.get("description_variants"),
        source_names=source_names,
        effective={effective_item: True for effective_item in effective_items},
        target_api=target_api,
        modalities=modalities,
        capabilities=capabilities,
        deferred_guidance=deferred_guidance,
    )


def _catalog_evaluation_order(catalog: Any) -> list[str]:
    order: list[str] = []
    visited: set[str] = set()

    def visit(item_id: str) -> None:
        if item_id in visited:
            return
        for dependency in catalog.dependencies.get(item_id, ()):
            visit(dependency)
        visited.add(item_id)
        order.append(item_id)

    for item_id in catalog.items:
        visit(item_id)
    return order


def _item_state(context: _PlanContext, item_id: str) -> str:
    return context.states.get(
        item_id, context.contract["builtin"].get(item_id, "passthrough")
    )


def _item_is_effective(
    context: _PlanContext, item_id: str, effective: Mapping[str, bool]
) -> bool:
    item = context.catalog.items[item_id]
    state = _item_state(context, item_id)
    is_effective = state != "disabled"
    if item["type"] == "custom_injection":
        is_effective = state == "injected"
    allowed_apis = item.get("state_api_types", {}).get(state)
    if allowed_apis is not None and context.target_api not in allowed_apis:
        return False
    availability = item.get("availability")
    if is_effective and availability is not None:
        is_effective = _condition_matches(
            availability,
            source_names=context.source_names,
            effective=effective,
            target_api=context.target_api,
            modalities=context.modalities,
            capabilities=context.capabilities,
            deferred_guidance=context.deferred_guidance,
        )
    delivery = item.get("delivery", {})
    if (
        is_effective
        and state == "modified"
        and delivery.get("modified_requires_deferred_exec_guidance")
    ):
        return context.deferred_guidance
    return is_effective


def _record_item_effect(
    context: _PlanContext,
    item_id: str,
    is_effective: bool,
    actions: list[ToolPlanAction],
    remove_names: set[str],
    adapter_bindings: dict[str, tuple[str, ...]],
) -> None:
    item = context.catalog.items[item_id]
    state = _item_state(context, item_id)
    delivery = item.get("delivery", {})
    if (
        delivery.get("direct_function_wins")
        and item["name"] in context.direct_function_names
    ):
        actions.append(ToolPlanAction(item_id, "preserve", "direct_function_wins"))
    if not is_effective:
        _record_ineffective_item(context, item_id, state, actions, remove_names)
        return
    adapters = tuple(item.get("runtime_adapters", ()))
    if adapters:
        adapter_bindings[item["name"]] = adapters
    if state == "modified" and delivery.get("modified_removes_source"):
        remove_names.add(item["name"])
        actions.append(ToolPlanAction(item_id, "remove", "modified_projection"))


def _record_ineffective_item(
    context: _PlanContext,
    item_id: str,
    state: str,
    actions: list[ToolPlanAction],
    remove_names: set[str],
) -> None:
    item = context.catalog.items[item_id]
    if item["name"] not in context.source_names:
        return
    if state == "disabled":
        exec_projection = item.get("exec_projection")
        internal = item.get("internal_container_when_disabled") or (
            isinstance(exec_projection, Mapping)
            and exec_projection.get("internal_when_disabled") is True
        )
        if internal:
            actions.append(ToolPlanAction(item_id, "preserve", "internal_container"))
            return
        remove_names.add(item["name"])
        remove_names.update(item.get("aliases", ()))
        actions.append(ToolPlanAction(item_id, "remove", "disabled"))
    elif item.get("availability") is not None:
        remove_names.add(item["name"])
        actions.append(ToolPlanAction(item_id, "remove", "unavailable"))


def _collect_plan_definitions(
    context: _PlanContext,
    order: list[str],
    effective: Mapping[str, bool],
    actions: list[ToolPlanAction],
) -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    for item_id in order:
        if not effective[item_id]:
            continue
        item = context.catalog.items[item_id]
        state = _item_state(context, item_id)
        raw_definition = item.get("catalog_definition")
        if raw_definition is None:
            if item["name"] in context.source_names:
                actions.append(ToolPlanAction(item_id, "preserve", state))
            continue
        definitions[item_id] = _apply_description_variants(
            _thaw(raw_definition),
            item.get("description_variants"),
            source_names=context.source_names,
            effective=effective,
            target_api=context.target_api,
            modalities=context.modalities,
            capabilities=context.capabilities,
            deferred_guidance=context.deferred_guidance,
        )
        actions.append(ToolPlanAction(item_id, "define", state))
    return definitions


def build_tool_runtime_plan(body: dict[str, Any], route: Any) -> ToolRuntimePlan:
    """Evaluate catalog rules for one request without mutating the request."""
    contract = tool_profile_contract()
    catalog = contract["catalog"]
    target_api = _target_api(route)
    profile = getattr(route, "tool_profile", None)
    bypass = target_api == "responses" and not profile
    identities = _source_tools(body)
    source_names = frozenset(name for _tool_type, name in identities)
    direct_function_names = frozenset(
        name for tool_type, name in identities if tool_type == "function"
    )
    exec_item = next(
        (
            item
            for item in catalog.items.values()
            if item.get("delivery", {}).get("deferred_guidance_marker")
        ),
        None,
    )
    marker = (
        str(exec_item["delivery"]["deferred_guidance_marker"])
        if exec_item is not None
        else ""
    )
    deferred_guidance = bool(marker) and _deferred_guidance_exists(body, marker)
    modalities = _model_modalities(route)
    capabilities = frozenset(getattr(route, "tool_runtime_capabilities", ()))
    effective: dict[str, bool] = {}
    actions: list[ToolPlanAction] = []
    adapter_bindings: dict[str, tuple[str, ...]] = {}
    remove_names: set[str] = set()
    states = profile or contract["builtin"]

    if bypass:
        return ToolRuntimePlan(
            catalog_version=str(catalog.raw["metadata"]["catalog_version"]),
            bypass=True,
            effective_items=frozenset(),
            remove_names=frozenset(),
            definitions={},
            adapter_bindings={},
            actions=(),
            source_names=source_names,
            deferred_exec_guidance=deferred_guidance,
        )
    context = _PlanContext(
        catalog=catalog,
        contract=contract,
        target_api=target_api,
        source_names=source_names,
        direct_function_names=direct_function_names,
        deferred_guidance=deferred_guidance,
        modalities=modalities,
        capabilities=capabilities,
        states=states,
    )
    evaluation_order = _catalog_evaluation_order(catalog)
    for item_id in evaluation_order:
        is_effective = _item_is_effective(context, item_id, effective)
        effective[item_id] = is_effective
        _record_item_effect(
            context,
            item_id,
            is_effective,
            actions,
            remove_names,
            adapter_bindings,
        )
    definitions = _collect_plan_definitions(
        context, evaluation_order, effective, actions
    )

    return ToolRuntimePlan(
        catalog_version=str(catalog.raw["metadata"]["catalog_version"]),
        bypass=False,
        effective_items=frozenset(
            item_id for item_id, value in effective.items() if value
        ),
        remove_names=frozenset(remove_names),
        definitions=definitions,
        adapter_bindings=adapter_bindings,
        actions=tuple(actions),
        source_names=source_names,
        deferred_exec_guidance=deferred_guidance,
    )
