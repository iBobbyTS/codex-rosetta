"""Shared model-facing and runtime capabilities for Rosetta ``web.run``."""

from __future__ import annotations

import copy
import re
from typing import Any

from .admin.tool_catalog import load_tool_catalog

WEB_RUN_PROFILE_ITEM_ID = "namespace.web.run"
WEB_RUN_BASIC_SEARCH_CAPABILITY = "web_run_basic_search"
WEB_RUN_SIDECAR_CAPABILITY = "web_run_sidecar"


def _web_run_projection() -> dict[str, Any]:
    matches = [
        item["capability_projection"]
        for item in load_tool_catalog()["items"]
        if "web_run" in item.get("runtime_adapters", [])
    ]
    if len(matches) != 1 or not isinstance(matches[0], dict):
        raise ValueError("web_run adapter must own one capability_projection")
    return matches[0]


def _command_fields(section: str) -> dict[str, frozenset[str] | None]:
    projection = _web_run_projection()[section]
    commands = projection.get("commands", {})
    if not isinstance(commands, dict):
        raise ValueError(f"web_run capability section {section!r} is invalid")
    result: dict[str, frozenset[str] | None] = {}
    for command, fields in commands.items():
        if (
            not isinstance(command, str)
            or not isinstance(fields, list)
            or any(not isinstance(field, str) for field in fields)
        ):
            raise ValueError(f"web_run capability section {section!r} is invalid")
        result[command] = frozenset(field for field in fields if isinstance(field, str))
    top_level_fields = projection.get("top_level_fields", [])
    if not isinstance(top_level_fields, list) or any(
        not isinstance(field, str) for field in top_level_fields
    ):
        raise ValueError(f"web_run capability section {section!r} is invalid")
    result.update({field: None for field in top_level_fields})
    return result


WEB_RUN_BASE_COMMAND_FIELDS = _command_fields("base")
WEB_RUN_SEARCH_COMMAND_FIELDS = _command_fields(WEB_RUN_BASIC_SEARCH_CAPABILITY)
WEB_RUN_SIDECAR_COMMAND_FIELDS = _command_fields(WEB_RUN_SIDECAR_CAPABILITY)
WEB_RUN_SUPPORTED_COMMAND_FIELDS = {
    **WEB_RUN_BASE_COMMAND_FIELDS,
    **WEB_RUN_SEARCH_COMMAND_FIELDS,
}
WEB_RUN_SUPPORTED_COMMANDS = frozenset(WEB_RUN_SUPPORTED_COMMAND_FIELDS)
WEB_RUN_KNOWN_COMMANDS = frozenset(
    set(WEB_RUN_BASE_COMMAND_FIELDS)
    | set(WEB_RUN_SEARCH_COMMAND_FIELDS)
    | set(WEB_RUN_SIDECAR_COMMAND_FIELDS)
    | set(_web_run_projection().get("unsupported_commands", []))
)
WEB_RUN_UNSUPPORTED_COMMANDS = WEB_RUN_KNOWN_COMMANDS - WEB_RUN_SUPPORTED_COMMANDS


def project_modified_web_run_function(
    function: dict[str, Any],
    *,
    search_available: bool = False,
    browser_available: bool = False,
) -> dict[str, Any] | None:
    """Restrict a live Codex ``web.run`` definition to Rosetta capabilities."""
    parameters = function.get("parameters")
    if not isinstance(parameters, dict):
        return None
    projected_parameters = project_modified_web_run_schema(
        parameters,
        search_available=search_available,
        browser_available=browser_available,
    )
    if projected_parameters is None:
        return None

    projected = copy.deepcopy(function)
    projected["parameters"] = projected_parameters
    description = projected.get("description")
    if isinstance(description, str):
        properties = parameters.get("properties")
        live_commands = (
            frozenset(str(name) for name in properties)
            if isinstance(properties, dict)
            else frozenset()
        )
        projected["description"] = project_modified_web_run_description(
            description,
            search_available=search_available,
            browser_available=browser_available,
            live_commands=live_commands,
        )
    return projected


def project_modified_web_run_schema(
    schema: dict[str, Any],
    *,
    search_available: bool = False,
    browser_available: bool = False,
) -> dict[str, Any] | None:
    """Keep only live schema branches implemented by Rosetta's local bridge."""
    properties = schema.get("properties")
    if schema.get("type") != "object" or not isinstance(properties, dict):
        return None

    projected = copy.deepcopy(schema)
    projected_properties: dict[str, Any] = {}
    for command, allowed_fields in web_run_supported_command_fields(
        search_available=search_available,
        browser_available=browser_available,
    ).items():
        command_schema = properties.get(command)
        if not isinstance(command_schema, dict):
            continue
        if allowed_fields is None:
            projected_properties[command] = copy.deepcopy(command_schema)
            continue
        projected_command = _project_array_command(command_schema, allowed_fields)
        if projected_command is not None:
            projected_properties[command] = projected_command

    if not projected_properties:
        return None
    projected["properties"] = projected_properties
    projected["required"] = [
        name for name in projected.get("required", []) if name in projected_properties
    ]
    projected["additionalProperties"] = False
    return projected


def project_modified_web_run_description(
    description: str,
    *,
    search_available: bool = False,
    browser_available: bool = False,
    live_commands: frozenset[str] = frozenset(),
) -> str:
    """Remove unsupported command guidance from the live Codex description."""
    retained: list[str] = []
    supported_commands = frozenset(
        web_run_supported_command_fields(
            search_available=search_available,
            browser_available=browser_available,
        )
    )
    unsupported_commands = (WEB_RUN_KNOWN_COMMANDS | live_commands) - supported_commands
    unsupported_markers = tuple(
        marker
        for command in sorted(unsupported_commands)
        for marker in (f"`{command}`", f'"{command}"')
    )
    rules = _web_run_projection().get("description_rules", {})
    drop_markers = tuple(
        str(marker).lower() for marker in rules.get("drop_lines_containing", [])
    )
    replacements = rules.get("replace_text", [])
    for line in description.splitlines():
        if any(marker in line for marker in unsupported_markers):
            continue
        if any(marker in line.lower() for marker in drop_markers):
            continue
        for replacement in replacements:
            flags = re.IGNORECASE if replacement.get("case_insensitive") else 0
            line = re.sub(
                re.escape(replacement["from"]),
                replacement["to"],
                line,
                flags=flags,
            )
        retained.append(line)
    return "\n".join(retained).strip()


def web_run_supported_command_fields(
    *, search_available: bool = False, browser_available: bool
) -> dict[str, frozenset[str] | None]:
    """Return the command schema implemented by the active local executors."""
    supported = dict(WEB_RUN_BASE_COMMAND_FIELDS)
    if search_available:
        supported.update(WEB_RUN_SEARCH_COMMAND_FIELDS)
    if browser_available:
        supported.update(WEB_RUN_SIDECAR_COMMAND_FIELDS)
    return supported


def web_run_model_availability(route: Any) -> tuple[bool, bool]:
    """Return configured search and ready browser capabilities for one route."""
    capabilities = getattr(route, "tool_runtime_capabilities", frozenset())
    return (
        WEB_RUN_BASIC_SEARCH_CAPABILITY in capabilities,
        WEB_RUN_SIDECAR_CAPABILITY in capabilities,
    )


def _project_array_command(
    schema: dict[str, Any],
    allowed_fields: frozenset[str],
) -> dict[str, Any] | None:
    if schema.get("type") != "array":
        return None
    items = schema.get("items")
    if not isinstance(items, dict) or items.get("type") != "object":
        return None
    properties = items.get("properties")
    if not isinstance(properties, dict):
        return None

    projected_properties = {
        name: copy.deepcopy(value)
        for name, value in properties.items()
        if name in allowed_fields
    }
    if not projected_properties:
        return None

    projected = copy.deepcopy(schema)
    projected_items = copy.deepcopy(items)
    projected_items["properties"] = projected_properties
    projected_items["required"] = [
        name
        for name in projected_items.get("required", [])
        if name in projected_properties
    ]
    projected_items["additionalProperties"] = False
    projected["items"] = projected_items
    return projected


__all__ = [
    "WEB_RUN_BASE_COMMAND_FIELDS",
    "WEB_RUN_BASIC_SEARCH_CAPABILITY",
    "WEB_RUN_KNOWN_COMMANDS",
    "WEB_RUN_PROFILE_ITEM_ID",
    "WEB_RUN_SEARCH_COMMAND_FIELDS",
    "WEB_RUN_SIDECAR_COMMAND_FIELDS",
    "WEB_RUN_SIDECAR_CAPABILITY",
    "WEB_RUN_SUPPORTED_COMMANDS",
    "WEB_RUN_SUPPORTED_COMMAND_FIELDS",
    "WEB_RUN_UNSUPPORTED_COMMANDS",
    "project_modified_web_run_description",
    "project_modified_web_run_function",
    "project_modified_web_run_schema",
    "web_run_model_availability",
    "web_run_supported_command_fields",
]
