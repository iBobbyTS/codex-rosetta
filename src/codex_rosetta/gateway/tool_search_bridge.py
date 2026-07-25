"""Catalog-selected bridge for Responses client tool search over Chat APIs."""

from __future__ import annotations

import json
from typing import Any

from .tool_profiles import (
    catalog_runtime_adapters,
    route_tool_state,
    tool_catalog_lookups,
)
from .tool_runtime_plan import ToolRuntimePlan


def _bridge_item() -> tuple[str, dict[str, Any]]:
    matches = [
        (item_id, item)
        for item_id, item in tool_catalog_lookups()["items"].items()
        if "tool_search_chat_bridge" in catalog_runtime_adapters(item_id)
    ]
    if len(matches) != 1:
        raise ValueError("tool_search_chat_bridge must own exactly one catalog item")
    return matches[0]


def tool_search_bridge_active(plan: ToolRuntimePlan, route: Any) -> bool:
    """Return whether a live native definition must cross into Chat."""
    item_id, item = _bridge_item()
    return (
        item_id in plan.effective_items
        and route_tool_state(route, item_id) == "passthrough"
        and getattr(route, "target_provider", None) == "openai_chat"
        and item["name"] in plan.source_names
    )


def tool_search_bridge_projection() -> Any:
    """Return the catalog-declared response adapter for the projected function."""
    from .code_mode_projection import ExecToolProjection

    item_id, item = _bridge_item()
    declaration = item.get("delivery", {}).get("passthrough_projection")
    if not isinstance(declaration, dict):
        raise ValueError("tool_search Chat bridge needs passthrough_projection")
    return ExecToolProjection(item_id=item_id, **declaration)


def _project_definition(tool: dict[str, Any], name: str) -> dict[str, Any]:
    if tool.get("execution") != "client":
        raise ValueError("native client tool definition requires execution='client'")
    parameters = tool.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("native client tool definition requires parameters object")
    description = tool.get("description", "")
    if not isinstance(description, str):
        raise ValueError("native client tool description must be a string")
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": parameters,
        "strict": False,
    }


def _project_tool_list(tools: list[Any], item: dict[str, Any]) -> list[Any]:
    name = item["name"]
    direct_exists = any(
        isinstance(tool, dict)
        and tool.get("type") == "function"
        and (
            tool.get("name") == name
            or (
                isinstance(tool.get("function"), dict)
                and tool["function"].get("name") == name
            )
        )
        for tool in tools
    )
    projected: list[Any] = []
    native_count = 0
    for tool in tools:
        if isinstance(tool, dict) and tool.get("type") == name:
            native_count += 1
            if not direct_exists:
                projected.append(_project_definition(tool, name))
            continue
        projected.append(tool)
    if native_count > 1:
        raise ValueError("multiple native client tool definitions are ambiguous")
    return projected


def _project_history(input_items: list[Any], item: dict[str, Any]) -> list[Any]:
    name = item["name"]
    call_type = f"{name}_call"
    output_type = f"{name}_output"
    calls: set[str] = set()
    outputs: set[str] = set()
    projected: list[Any] = []
    for raw_item in input_items:
        if not isinstance(raw_item, dict):
            projected.append(raw_item)
            continue
        item_type = raw_item.get("type")
        if item_type == "additional_tools":
            tools = raw_item.get("tools")
            if not isinstance(tools, list):
                raise ValueError("additional_tools requires a tools list")
            next_item = dict(raw_item)
            next_item["tools"] = _project_tool_list(tools, item)
            projected.append(next_item)
            continue
        if item_type == call_type:
            call_id, projected_call = _project_history_call(raw_item, name)
            if call_id in calls:
                raise ValueError("duplicate native client tool call id")
            calls.add(call_id)
            projected.append(projected_call)
            continue
        if item_type == output_type:
            call_id, projected_output = _project_history_output(raw_item)
            if call_id in outputs:
                raise ValueError("duplicate native client tool output id")
            outputs.add(call_id)
            projected.append(projected_output)
            continue
        projected.append(raw_item)
    if calls != outputs:
        raise ValueError("orphan native client tool call/output history")
    return projected


def _project_history_call(
    raw_item: dict[str, Any], name: str
) -> tuple[str, dict[str, Any]]:
    call_id = raw_item.get("call_id")
    arguments = raw_item.get("arguments")
    if (
        not isinstance(call_id, str)
        or not call_id
        or raw_item.get("execution") != "client"
        or not isinstance(arguments, dict)
    ):
        raise ValueError("malformed native client tool call")
    return call_id, {
        "type": "function_call",
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(arguments, ensure_ascii=False),
    }


def _project_history_output(
    raw_item: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    call_id = raw_item.get("call_id")
    tools = raw_item.get("tools")
    if (
        not isinstance(call_id, str)
        or not call_id
        or raw_item.get("execution") != "client"
        or not isinstance(tools, list)
    ):
        raise ValueError("malformed native client tool output")
    output = {
        "status": raw_item.get("status", "completed"),
        "execution": "client",
        "tools": tools,
    }
    return call_id, {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(output, ensure_ascii=False),
    }


def project_tool_search_request(
    body: dict[str, Any], plan: ToolRuntimePlan, route: Any
) -> dict[str, Any]:
    """Project a validated live native client tool surface into Responses functions."""
    if not tool_search_bridge_active(plan, route):
        return body
    _item_id, item = _bridge_item()
    adapted = dict(body)
    tools = body.get("tools")
    if isinstance(tools, list):
        adapted["tools"] = _project_tool_list(tools, item)
    input_items = body.get("input")
    if isinstance(input_items, list):
        adapted["input"] = _project_history(input_items, item)
    tool_choice = body.get("tool_choice")
    if isinstance(tool_choice, dict) and tool_choice.get("type") == item["name"]:
        adapted["tool_choice"] = {"type": "function", "name": item["name"]}
    return adapted
