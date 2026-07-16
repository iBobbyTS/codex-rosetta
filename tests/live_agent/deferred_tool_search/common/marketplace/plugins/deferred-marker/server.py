#!/usr/bin/env python3
"""Minimal deterministic stdio MCP server for live-agent testing."""

from __future__ import annotations

import json
import sys
from typing import Any


MARKER_INPUT = "ROSETTA_DEFERRED_20260716"


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    if method == "initialize":
        requested = message.get("params", {}).get("protocolVersion")
        return _result(
            request_id,
            {
                "protocolVersion": requested or "2025-06-18",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "deferred-marker", "version": "1.0.0"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(
            request_id,
            {
                "tools": [
                    {
                        "name": "return_marker",
                        "description": (
                            "Return the deterministic Rosetta deferred-tool-search "
                            "test marker for a supplied value."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "value": {
                                    "type": "string",
                                    "description": "Exact marker value to echo.",
                                }
                            },
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                        "annotations": {
                            "readOnlyHint": True,
                            "destructiveHint": False,
                            "idempotentHint": True,
                            "openWorldHint": False,
                        },
                    }
                ]
            },
        )
    if method == "tools/call":
        params = message.get("params", {})
        if params.get("name") != "return_marker":
            return _error(request_id, -32601, "Unknown tool")
        value = params.get("arguments", {}).get("value")
        if value != MARKER_INPUT:
            return _result(
                request_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": f"INVALID_MARKER_INPUT:{value}",
                        }
                    ],
                    "isError": True,
                },
            )
        marker = f"PLUGIN_TOOL_OK:{value}"
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": marker}],
                "structuredContent": {"marker": marker},
                "isError": False,
            },
        )
    if method in {"prompts/list", "resources/list", "resources/templates/list"}:
        key = "prompts" if method == "prompts/list" else "resources"
        return _result(request_id, {key: []})
    if request_id is None:
        return None
    return _error(request_id, -32601, f"Unsupported method: {method}")


def main() -> None:
    for line in sys.stdin:
        try:
            message = json.loads(line)
            response = _handle(message)
        except Exception as exc:  # pragma: no cover - live fixture safeguard
            response = _error(None, -32603, f"Fixture server error: {exc}")
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
