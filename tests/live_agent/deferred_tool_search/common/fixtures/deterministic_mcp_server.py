#!/usr/bin/env python3
"""Deterministic read-only stdio MCP server for capability-discovery tests."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    properties: dict[str, dict[str, str]]
    required: tuple[str, ...]


CAPABILITIES = {
    "archive": Capability(
        name="get_archive_proof",
        description=(
            "Rosetta live candidate. Retrieve the immutable proof for a named "
            "archive record. Use this for archive evidence and record-proof requests."
        ),
        properties={
            "record_id": {
                "type": "string",
                "description": "Archive record identifier.",
            }
        },
        required=("record_id",),
    ),
    "arithmetic": Capability(
        name="add_integers",
        description=(
            "Rosetta live candidate. Add two integers and return their deterministic "
            "sum."
        ),
        properties={
            "left": {"type": "integer", "description": "Left integer."},
            "right": {"type": "integer", "description": "Right integer."},
        },
        required=("left", "right"),
    ),
    "palette": Capability(
        name="normalize_color",
        description=(
            "Rosetta live candidate. Normalize a color label to a deterministic "
            "lowercase palette value."
        ),
        properties={
            "color": {"type": "string", "description": "Color label to normalize."}
        },
        required=("color",),
    ),
}


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _tool_definition(capability: Capability) -> dict[str, Any]:
    return {
        "name": capability.name,
        "description": capability.description,
        "inputSchema": {
            "type": "object",
            "properties": capability.properties,
            "required": list(capability.required),
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }


def _call_tool(name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    if name == "get_archive_proof":
        record_id = arguments.get("record_id")
        if record_id != "ARCHIVE-20260716":
            return f"INVALID_ARCHIVE_RECORD:{record_id}", True
        return "ARCHIVE_PROOF_OK:ARCHIVE-20260716", False
    if name == "add_integers":
        left = arguments.get("left")
        right = arguments.get("right")
        if not isinstance(left, int) or not isinstance(right, int):
            return "INVALID_INTEGER_INPUT", True
        return f"ARITHMETIC_SUM:{left + right}", False
    if name == "normalize_color":
        color = arguments.get("color")
        if not isinstance(color, str) or not color.strip():
            return "INVALID_COLOR_INPUT", True
        return f"COLOR_NORMALIZED:{color.strip().lower()}", False
    return f"UNKNOWN_TOOL:{name}", True


def handle_message(
    message: dict[str, Any], *, capabilities: tuple[str, ...], server_name: str
) -> dict[str, Any] | None:
    """Handle one MCP JSON-RPC message for the selected capabilities."""
    request_id = message.get("id")
    method = message.get("method")
    if method == "initialize":
        requested = message.get("params", {}).get("protocolVersion")
        return _result(
            request_id,
            {
                "protocolVersion": requested or "2025-06-18",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": server_name, "version": "1.0.0"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(
            request_id,
            {"tools": [_tool_definition(CAPABILITIES[key]) for key in capabilities]},
        )
    if method == "tools/call":
        params = message.get("params", {})
        tool_name = params.get("name")
        allowed_names = {CAPABILITIES[key].name for key in capabilities}
        if tool_name not in allowed_names:
            return _error(request_id, -32601, "Unknown tool")
        text, is_error = _call_tool(tool_name, params.get("arguments", {}))
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": text}],
                "structuredContent": {"result": text},
                "isError": is_error,
            },
        )
    if method == "prompts/list":
        return _result(request_id, {"prompts": []})
    if method == "resources/list":
        return _result(request_id, {"resources": []})
    if method == "resources/templates/list":
        return _result(request_id, {"resourceTemplates": []})
    if request_id is None:
        return None
    return _error(request_id, -32601, f"Unsupported method: {method}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--capability",
        choices=(*CAPABILITIES, "all"),
        default="all",
    )
    parser.add_argument("--server-name", default="rosetta-capability-fixture")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    capabilities = (
        tuple(CAPABILITIES) if args.capability == "all" else (args.capability,)
    )
    for line in sys.stdin:
        try:
            message = json.loads(line)
            response = handle_message(
                message,
                capabilities=capabilities,
                server_name=args.server_name,
            )
        except Exception as exc:  # pragma: no cover - live fixture safeguard
            response = _error(None, -32603, f"Fixture server error: {exc}")
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
