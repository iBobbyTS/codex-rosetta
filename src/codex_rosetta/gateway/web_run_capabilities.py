"""Shared model-facing and runtime capabilities for Rosetta ``web.run``."""

from __future__ import annotations

import copy
import re
from typing import Any

WEB_RUN_PROFILE_ITEM_ID = "namespace.web.run"
WEB_RUN_SIDECAR_CAPABILITY = "web_run_sidecar"

# ``None`` means the command has no nested object fields to prune. A field set
# describes the only model-visible fields Rosetta accepts for each array item.
WEB_RUN_SUPPORTED_COMMAND_FIELDS: dict[str, frozenset[str] | None] = {
    "search_query": frozenset({"q", "domains"}),
    "open": frozenset({"ref_id", "lineno"}),
    "time": frozenset({"utc_offset"}),
    "response_length": None,
}
WEB_RUN_SIDECAR_COMMAND_FIELDS: dict[str, frozenset[str]] = {
    "click": frozenset({"ref_id", "id"}),
    "find": frozenset({"ref_id", "pattern"}),
    "screenshot": frozenset({"ref_id", "pageno"}),
}
WEB_RUN_SUPPORTED_COMMANDS = frozenset(WEB_RUN_SUPPORTED_COMMAND_FIELDS)
WEB_RUN_KNOWN_COMMANDS = frozenset(
    {
        "search_query",
        "image_query",
        "open",
        "click",
        "find",
        "screenshot",
        "finance",
        "weather",
        "sports",
        "time",
        "response_length",
    }
)
WEB_RUN_UNSUPPORTED_COMMANDS = WEB_RUN_KNOWN_COMMANDS - WEB_RUN_SUPPORTED_COMMANDS

_SEARCH_RECENCY_CLAIM_RE = re.compile(
    r"\s*\(and optionally with a domain or recency filter\)",
    flags=re.IGNORECASE,
)


def project_modified_web_run_function(
    function: dict[str, Any],
    *,
    browser_available: bool = False,
) -> dict[str, Any] | None:
    """Restrict a live Codex ``web.run`` definition to Rosetta capabilities."""
    parameters = function.get("parameters")
    if not isinstance(parameters, dict):
        return None
    projected_parameters = project_modified_web_run_schema(
        parameters, browser_available=browser_available
    )
    if projected_parameters is None:
        return None

    projected = copy.deepcopy(function)
    projected["parameters"] = projected_parameters
    description = projected.get("description")
    if isinstance(description, str):
        projected["description"] = project_modified_web_run_description(
            description, browser_available=browser_available
        )
    return projected


def project_modified_web_run_schema(
    schema: dict[str, Any],
    *,
    browser_available: bool = False,
) -> dict[str, Any] | None:
    """Keep only live schema branches implemented by Rosetta's local bridge."""
    properties = schema.get("properties")
    if schema.get("type") != "object" or not isinstance(properties, dict):
        return None

    projected = copy.deepcopy(schema)
    projected_properties: dict[str, Any] = {}
    for command, allowed_fields in web_run_supported_command_fields(
        browser_available=browser_available
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
    browser_available: bool = False,
) -> str:
    """Remove unsupported command guidance from the live Codex description."""
    retained: list[str] = []
    unsupported_commands = WEB_RUN_KNOWN_COMMANDS - frozenset(
        web_run_supported_command_fields(browser_available=browser_available)
    )
    unsupported_markers = tuple(
        marker
        for command in sorted(unsupported_commands)
        for marker in (f"`{command}`", f'"{command}"')
    )
    for line in description.splitlines():
        if any(marker in line for marker in unsupported_markers):
            continue
        if "empty query" in line.lower():
            continue
        retained.append(_SEARCH_RECENCY_CLAIM_RE.sub(" (optionally by domain)", line))
    return "\n".join(retained).strip()


def web_run_supported_command_fields(
    *, browser_available: bool
) -> dict[str, frozenset[str] | None]:
    """Return the command schema implemented by the active local executors."""
    supported = dict(WEB_RUN_SUPPORTED_COMMAND_FIELDS)
    if browser_available:
        supported.update(WEB_RUN_SIDECAR_COMMAND_FIELDS)
    return supported


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
    "WEB_RUN_KNOWN_COMMANDS",
    "WEB_RUN_PROFILE_ITEM_ID",
    "WEB_RUN_SIDECAR_COMMAND_FIELDS",
    "WEB_RUN_SIDECAR_CAPABILITY",
    "WEB_RUN_SUPPORTED_COMMANDS",
    "WEB_RUN_SUPPORTED_COMMAND_FIELDS",
    "WEB_RUN_UNSUPPORTED_COMMANDS",
    "project_modified_web_run_description",
    "project_modified_web_run_function",
    "project_modified_web_run_schema",
    "web_run_supported_command_fields",
]
