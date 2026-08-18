#!/usr/bin/env python3
"""Run an isolated app-server steer, interrupt, or fork cache cell."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import http.server
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SUITE = Path(__file__).resolve().parent
MODEL = "deepseek-v4-flash"
AUTH_SOURCE = Path("/Users/ibobby/.codex-multi-2/auth.json")
GATEWAY_CONFIG_SOURCE = Path.home() / ".config/codex-rosetta-gateway/config.jsonc"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SUITE.parent))

from codex_rosetta.gateway.live_gate import require_live_call_approval  # noqa: E402
from codex_rosetta.gateway.config import _strip_jsonc_comments  # noqa: E402

from context_compaction.run_live import (  # noqa: E402
    _AppServerClient,
    _configure_run,
    _free_port,
    _validate_auth,
    _wait_ready,
    _write_json,
)
from interrupt_continuation.evidence import trace_usage  # noqa: E402


def _fork_collaboration_mode(model: str) -> dict[str, Any]:
    return {
        "mode": "default",
        "settings": {
            "model": model,
            "reasoning_effort": "max",
            "developer_instructions": (
                "This fork was created for an isolated cache test. "
                "Follow the next user instruction exactly."
            ),
        },
    }


def _turn_id(result: Any) -> str:
    value = result.get("turn", {}).get("id") if isinstance(result, dict) else None
    if not isinstance(value, str) or not value:
        raise RuntimeError("turn/start did not return a turn id")
    return value


def _thread_id(result: Any) -> str:
    value = result.get("thread", {}).get("id") if isinstance(result, dict) else None
    if not isinstance(value, str) or not value:
        raise RuntimeError("thread/start did not return a thread id")
    return value


def _status(params: dict[str, Any]) -> str | None:
    value = params.get("turn", {}).get("status")
    return value if isinstance(value, str) else None


def _completed_since(
    client: _AppServerClient, thread_id: str, start: int
) -> dict[str, Any]:
    for message in client.messages[start:]:
        if message.get("method") == "turn/completed":
            params = message.get("params")
            if isinstance(params, dict) and params.get("threadId") == thread_id:
                return params
    return client.wait_for_turn(thread_id)


def _wait_for_active_stream(client: _AppServerClient, thread_id: str) -> dict[str, Any]:
    deltas = 0
    started = time.monotonic()
    while time.monotonic() - started < 150:
        message = client.receive()
        if client._handle_server_request(message):
            continue
        params = message.get("params") or {}
        if params.get("threadId") != thread_id:
            continue
        if message.get("method") == "item/agentMessage/delta":
            deltas += 1
        if message.get("method") == "turn/completed":
            return {"active": False, "agent_deltas": deltas}
        if deltas:
            return {"active": True, "agent_deltas": deltas}
    raise TimeoutError("did not observe an active stream")


_TOOL_ITEM_TYPES = {
    "command_execution",
    "function_call",
    "function_call_output",
    "custom_tool_call",
    "custom_tool_call_output",
    "web_search_call",
    "mcp_tool_call",
    "tool_search_call",
    "tool_search_output",
}


def _protocol_surface(client: _AppServerClient) -> dict[str, Any]:
    """Summarize observed tool calls; do not persist their arguments."""

    calls: set[str] = set()
    for message in client.messages:
        params = message.get("params")
        if not isinstance(params, dict):
            continue
        item = params.get("item")
        if isinstance(item, dict) and isinstance(item.get("type"), str):
            if item["type"] in _TOOL_ITEM_TYPES:
                calls.add(item["type"])
    return {"tool_call_types": sorted(calls), "tool_calls_observed": bool(calls)}


def _agent_messages(client: _AppServerClient, thread_id: str) -> list[str]:
    messages: list[str] = []
    for message in client.messages:
        if message.get("method") != "item/completed":
            continue
        params = message.get("params")
        if not isinstance(params, dict) or params.get("threadId") != thread_id:
            continue
        item = params.get("item")
        if (
            isinstance(item, dict)
            and item.get("type") == "agentMessage"
            and isinstance(item.get("text"), str)
        ):
            messages.append(item["text"])
    return messages


def _run_fork_protocol(
    client: _AppServerClient, run_root: Path, model: str
) -> dict[str, Any]:
    thread_response = client.request(
        2,
        "thread/start",
        {
            "cwd": str(run_root / "worktree"),
            "approvalPolicy": "never",
            "sandbox": "danger-full-access",
            "experimentalRawEvents": True,
        },
    )
    parent_thread_data = thread_response.get("thread", {})
    parent_thread = _thread_id(thread_response)
    parent_start = len(client.messages)
    parent_turn = _turn_id(
        client.request(
            3,
            "turn/start",
            {
                "threadId": parent_thread,
                "input": [
                    {
                        "type": "text",
                        "text": "Reply only PARENT_OK. Do not call tools.",
                    }
                ],
            },
        )
    )
    parent_completion = _completed_since(client, parent_thread, parent_start)
    fork_response = client.request(
        4,
        "thread/fork",
        {"threadId": parent_thread, "lastTurnId": parent_turn},
    )
    fork_thread_data = fork_response.get("thread", {})
    fork_thread = _thread_id(fork_response)
    fork_start = len(client.messages)
    fork_turn = _turn_id(
        client.request(
            5,
            "turn/start",
            {
                "threadId": fork_thread,
                "input": [
                    {
                        "type": "text",
                        "text": "Reply only FORK_OK. Do not call tools.",
                    }
                ],
                "collaborationMode": _fork_collaboration_mode(model),
            },
        )
    )
    fork_completion = _completed_since(client, fork_thread, fork_start)
    return {
        "classification": "success",
        "parent_thread_id": parent_thread,
        "parent_session_id": parent_thread_data.get("sessionId"),
        "parent_turn_id": parent_turn,
        "parent_status": _status(parent_completion),
        "parent_agent_messages": _agent_messages(client, parent_thread),
        "fork_thread_id": fork_thread,
        "fork_session_id": fork_thread_data.get("sessionId"),
        "forked_from_id": fork_thread_data.get("forkedFromId"),
        "fork_turn_id": fork_turn,
        "fork_status": _status(fork_completion),
        "fork_agent_messages": _agent_messages(client, fork_thread),
        "protocol_message_count": len(client.messages),
        "protocol_surface": _protocol_surface(client),
    }


def _run_protocol(run_root: Path, mode: str, model: str = MODEL) -> dict[str, Any]:
    client = _AppServerClient(run_root, timeout_seconds=360)
    try:
        client.request(
            1,
            "initialize",
            {
                "clientInfo": {
                    "name": "Codex Desktop",
                    "title": "Codex Desktop",
                    "version": "1.0.0",
                },
                "capabilities": {
                    "experimentalApi": True,
                    "requestAttestation": True,
                },
            },
        )
        client.send({"method": "initialized", "params": {}})
        if mode == "fork":
            return _run_fork_protocol(client, run_root, model)
        thread = _thread_id(
            client.request(
                2,
                "thread/start",
                {
                    "cwd": str(run_root / "worktree"),
                    "approvalPolicy": "never",
                    "sandbox": "danger-full-access",
                    "experimentalRawEvents": True,
                },
            )
        )
        seed = _turn_id(
            client.request(
                3,
                "turn/start",
                {
                    "threadId": thread,
                    "input": [{"type": "text", "text": "Reply only SEED_OK"}],
                },
            )
        )
        seed_completion = _completed_since(client, thread, len(client.messages))
        long_prompt = "输出 1 到 500 的整数，每行一个，不要调用工具，不要提前结束。"
        active_turn = _turn_id(
            client.request(
                4,
                "turn/start",
                {
                    "threadId": thread,
                    "input": [{"type": "text", "text": long_prompt}],
                },
            )
        )
        activity = _wait_for_active_stream(client, thread)
        if not activity["active"]:
            return {
                "classification": "failure",
                "reason": "long turn completed before control request",
                "thread_id": thread,
                "seed_turn_id": seed,
                "seed_status": _status(seed_completion),
                "active_turn_id": active_turn,
                "activity": activity,
            }

        control_start = len(client.messages)
        if mode == "steer":
            control = client.request(
                5,
                "turn/steer",
                {
                    "threadId": thread,
                    "expectedTurnId": active_turn,
                    "input": [{"type": "text", "text": "停止输出，只回复 STEERED_OK"}],
                },
            )
            completion = _completed_since(client, thread, control_start)
            return {
                "classification": "success",
                "thread_id": thread,
                "active_turn_id": active_turn,
                "control_turn_id": control.get("turnId"),
                "same_turn_id": control.get("turnId") == active_turn,
                "final_status": _status(completion),
                "activity": activity,
                "protocol_message_count": len(client.messages),
                "protocol_surface": _protocol_surface(client),
            }

        client.request(
            5,
            "turn/interrupt",
            {"threadId": thread, "turnId": active_turn},
        )
        interrupted = _completed_since(client, thread, control_start)
        resume_start = len(client.messages)
        resume_turn = _turn_id(
            client.request(
                6,
                "turn/start",
                {
                    "threadId": thread,
                    "input": [
                        {
                            "type": "text",
                            "text": "继续刚才的任务，只回复 CONTINUED_OK",
                        }
                    ],
                },
            )
        )
        resumed = _completed_since(client, thread, resume_start)
        return {
            "classification": "success",
            "thread_id": thread,
            "interrupted_turn_id": active_turn,
            "interrupted_status": _status(interrupted),
            "resume_turn_id": resume_turn,
            "resume_status": _status(resumed),
            "activity": activity,
            "protocol_message_count": len(client.messages),
            "protocol_surface": _protocol_surface(client),
        }
    finally:
        client.close()


def _copy_fixture(run_root: Path) -> None:
    shutil.copytree(SUITE / "common", run_root / "worktree", dirs_exist_ok=True)
    shutil.copytree(SUITE / "01", run_root / "worktree", dirs_exist_ok=True)
    forbidden = {
        ".agents",
        ".mcp.json",
        ".mcp.toml",
        "plugins",
        "skills",
    }
    unexpected = sorted(
        str(path.relative_to(run_root / "worktree"))
        for path in (run_root / "worktree").rglob("*")
        if path.name in forbidden
    )
    if unexpected:
        raise RuntimeError(
            "interrupt fixture contains a tool/skill/plugin surface: "
            + ", ".join(unexpected)
        )


def _disable_dynamic_surfaces(run_root: Path) -> None:
    """Make the child Codex context independent of the parent app surface."""

    path = run_root / "codex_home" / "config.toml"
    with path.open("a", encoding="utf-8") as config:
        config.write(
            """

# This cell is deliberately tool/skill/plugin-neutral. Keep this block in sync
# with the Codex config contract; do not add project or user integrations here.
include_permissions_instructions = false
include_apps_instructions = false
include_collaboration_mode_instructions = false
include_skill_instructions = false
include_environment_context = false

[skills]
include_instructions = false

[skills.bundled]
enabled = false

[orchestrator.skills]
enabled = false

[orchestrator.mcp]
enabled = false

[features]
apps = false
code_mode = false
collab = false
current_time_reminder = false
image_generation = false
multi_agent_v2 = false
plugins = false
remote_plugin = false
shell_tool = false
standalone_web_search = false
tool_suggest = false
unified_exec = false
unified_exec_zsh_fork = false
web_search_request = false
"""
        )


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_SURFACE_MARKERS = (
    "<plugins_instructions>",
    "<recommended_plugins>",
    "<skills_instructions>",
    "<skill>",
    "<apps_instructions>",
    "<tools>",
    "<tool_suggest>",
    ".agents/skills",
    ".agents/plugins",
    "plugin.json",
)

_TURN_ABORTED_MARKER = """<turn_aborted>
The previous turn was interrupted on purpose. Any running unified exec processes may still be running in the background. If any tools/commands were aborted, they may have partially executed.
</turn_aborted>"""
_WRAPPED_TURN_ABORTED_NOTICE = f"<system>\n{_TURN_ABORTED_MARKER}\n</system>"


def _text_from_message(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    return ""


def _tool_names(tools: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(tools, list):
        return names
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.append(function["name"])
        elif isinstance(tool.get("name"), str):
            names.append(tool["name"])
        namespace = tool.get("namespace")
        if isinstance(namespace, dict):
            namespace_name = namespace.get("name")
            for nested in namespace.get("tools", []):
                nested_function = (
                    nested.get("function") if isinstance(nested, dict) else None
                )
                nested_name = (
                    nested_function.get("name")
                    if isinstance(nested_function, dict)
                    else nested.get("name")
                    if isinstance(nested, dict)
                    else None
                )
                if isinstance(nested_name, str):
                    names.append(f"{namespace_name}.{nested_name}")
    return sorted(names)


def _is_wrapped_system_user(message: dict[str, Any]) -> bool:
    text = _text_from_message(message).strip()
    return (
        message.get("role") == "user"
        and text.startswith("<system>\n")
        and text.endswith("\n</system>")
    )


def _request_surface(data: dict[str, Any]) -> dict[str, Any]:
    """Summarize dynamic model context without storing its content."""

    messages = data.get("messages")
    input_items = data.get("input")
    request_messages: list[dict[str, Any]] = []
    if isinstance(messages, list):
        request_messages = [
            {"role": item.get("role"), "text": _text_from_message(item)}
            for item in messages
            if isinstance(item, dict)
        ]
    elif isinstance(input_items, list):
        request_messages = [
            {"role": item.get("role"), "text": _text_from_message(item)}
            for item in input_items
            if isinstance(item, dict) and item.get("type") != "additional_tools"
        ]
    system_messages = [
        item for item in request_messages if item["role"] in {"system", "developer"}
    ]
    marker_hits = sorted(
        marker
        for marker in _SURFACE_MARKERS
        if any(marker in item["text"] for item in system_messages)
    )
    expected_turn_aborted_count = sum(
        item["text"].strip() == _TURN_ABORTED_MARKER for item in system_messages
    )
    wrapped_turn_aborted_count = sum(
        item["role"] == "user" and item["text"].strip() == _WRAPPED_TURN_ABORTED_NOTICE
        for item in request_messages
    )
    wrapped_system_user_count = sum(
        item["role"] == "user"
        and item["text"].strip().startswith("<system>\n")
        and item["text"].strip().endswith("\n</system>")
        for item in request_messages
    )
    normalized_system_messages = [
        item for item in system_messages if item["text"].strip() != _TURN_ABORTED_MARKER
    ]
    tools = data.get("tools")
    if not isinstance(tools, list) and isinstance(input_items, list):
        additional = [
            item.get("tools")
            for item in input_items
            if isinstance(item, dict) and item.get("type") == "additional_tools"
        ]
        tools = additional[0] if additional else []
    tool_names = _tool_names(tools)
    return {
        "context_fingerprint": _canonical_hash(
            [
                {"role": item["role"], "text": item["text"]}
                for item in normalized_system_messages
            ]
        ),
        "system_developer_count": len(system_messages),
        "system_developer_lengths": [len(item["text"]) for item in system_messages],
        "expected_turn_aborted_count": expected_turn_aborted_count,
        "wrapped_turn_aborted_count": wrapped_turn_aborted_count,
        "wrapped_system_user_count": wrapped_system_user_count,
        "dynamic_marker_hits": marker_hits,
        "tool_count": len(tool_names),
        "tool_names": tool_names,
        "tool_fingerprint": _canonical_hash(tools if isinstance(tools, list) else []),
        "additional_tools_present": any(
            isinstance(item, dict) and item.get("type") == "additional_tools"
            for item in (input_items if isinstance(input_items, list) else [])
        ),
    }


def trace_surfaces(path: Path) -> list[dict[str, Any]]:
    """Return credential-free per-request tool/context surface evidence."""

    requests: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return []
    for line in path.open(encoding="utf-8"):
        event = json.loads(line)
        request_id = event.get("request_id")
        if not isinstance(request_id, str):
            continue
        if event.get("stage") not in {"original_request", "target_request"}:
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        entry = requests.setdefault(request_id, {"request_id": request_id})
        entry[event["stage"]] = _request_surface(data)
    return list(requests.values())


def trace_fork_evidence(path: Path) -> dict[str, Any]:
    """Return bounded prefix/cache evidence for exactly two fork requests."""

    requests: list[dict[str, Any]] = []
    if not path.is_file():
        return {"request_count": 0, "requests": []}
    for line in path.open(encoding="utf-8"):
        event = json.loads(line)
        if event.get("stage") != "target_request":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        messages = data.get("messages")
        if not isinstance(messages, list):
            continue
        message_objects = [item for item in messages if isinstance(item, dict)]
        tools = data.get("tools") if isinstance(data.get("tools"), list) else []
        prompt_cache_key = data.get("prompt_cache_key")
        requests.append(
            {
                "request_id": event.get("request_id"),
                "message_count": len(message_objects),
                "roles": [item.get("role") for item in message_objects],
                "message_lengths": [
                    len(_text_from_message(item)) for item in message_objects
                ],
                "message_hashes": [_canonical_hash(item) for item in message_objects],
                "wrapped_system_user_count": sum(
                    _is_wrapped_system_user(item) for item in message_objects
                ),
                "tool_count": len(tools),
                "tool_hash": _canonical_hash(tools),
                "prompt_cache_key_present": isinstance(prompt_cache_key, str),
                "prompt_cache_key_hash": (
                    _canonical_hash(prompt_cache_key)
                    if isinstance(prompt_cache_key, str)
                    else None
                ),
            }
        )
    evidence: dict[str, Any] = {
        "request_count": len(requests),
        "requests": [
            {key: value for key, value in item.items() if key != "message_hashes"}
            for item in requests
        ],
    }
    if len(requests) == 2:
        parent, fork = requests
        parent_hashes = parent["message_hashes"]
        evidence.update(
            {
                "parent_messages_are_fork_prefix": (
                    fork["message_hashes"][: len(parent_hashes)] == parent_hashes
                ),
                "tool_definitions_stable": parent["tool_hash"] == fork["tool_hash"],
                "prompt_cache_key_changed": (
                    parent["prompt_cache_key_hash"] != fork["prompt_cache_key_hash"]
                ),
            }
        )
    return evidence


def _validate_trace_surfaces(surfaces: list[dict[str, Any]]) -> dict[str, Any]:
    if not surfaces:
        return {"status": "invalid", "reason": "no_request_surface"}
    observations = {
        stage: [
            surface[stage]
            for surface in surfaces
            if isinstance(surface.get(stage), dict)
        ]
        for stage in ("original_request", "target_request")
    }
    all_observations = [item for items in observations.values() for item in items]
    marker_hits = sorted(
        {
            marker
            for item in all_observations
            for marker in item.get("dynamic_marker_hits", [])
        }
    )
    if marker_hits:
        return {
            "status": "confounded",
            "reason": "dynamic_context_marker",
            "markers": marker_hits,
        }
    for stage, items in observations.items():
        if not items:
            return {"status": "invalid", "reason": f"missing_{stage}"}
        if len({item.get("tool_fingerprint") for item in items}) != 1:
            return {
                "status": "confounded",
                "reason": "tool_surface_changed",
                "stage": stage,
            }
        if len({item.get("context_fingerprint") for item in items}) != 1:
            return {
                "status": "confounded",
                "reason": "system_developer_context_changed",
                "stage": stage,
            }
    target = observations["target_request"][0]
    return {
        "status": "valid",
        "tool_count": target.get("tool_count", 0),
        "tool_names": target.get("tool_names", []),
        "context_fingerprint": target.get("context_fingerprint"),
    }


def _validate_interrupt_cache_contract(
    *,
    mode: str,
    surfaces: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    usage: list[dict[str, Any]],
    provider_request_count: int,
    upstream_usage: list[dict[str, int] | None] | None = None,
) -> dict[str, Any]:
    target_surfaces = [
        surface["target_request"]
        for surface in surfaces
        if isinstance(surface.get("target_request"), dict)
    ]
    wrapped_count = sum(
        int(item.get("wrapped_turn_aborted_count", 0)) for item in target_surfaces
    )
    system_marker_count = sum(
        int(item.get("expected_turn_aborted_count", 0)) for item in target_surfaces
    )
    rewritten_count = sum(
        int(profile.get("late_developer_rewritten_items", 0)) for profile in profiles
    )
    if provider_request_count != 3:
        return {
            "status": "invalid",
            "reason": "unexpected_provider_request_count",
            "provider_request_count": provider_request_count,
        }
    expected_wrapped = 1 if mode == "interrupt" else 0
    if (
        wrapped_count != expected_wrapped
        or rewritten_count != expected_wrapped
        or system_marker_count != 0
    ):
        return {
            "status": "invalid",
            "reason": "late_developer_shape",
            "wrapped_notice_count": wrapped_count,
            "system_marker_count": system_marker_count,
            "rewritten_profile_count": rewritten_count,
        }
    continuation_usage: dict[str, Any] | None = None
    usage_source: str | None = None
    if upstream_usage and isinstance(upstream_usage[-1], dict):
        continuation_usage = upstream_usage[-1]
        usage_source = "test_proxy_numeric_summary"
    else:
        completed_usage: list[dict[str, Any]] = []
        for item in usage:
            value = item.get("usage")
            if isinstance(value, dict):
                completed_usage.append(value)
        if completed_usage:
            continuation_usage = completed_usage[-1]
            usage_source = "gateway_trace"
    if continuation_usage is None:
        return {"status": "invalid", "reason": "completed_usage_missing"}
    cached_tokens = continuation_usage.get("cached_tokens")
    if not isinstance(cached_tokens, int) or cached_tokens <= 0:
        return {
            "status": "invalid",
            "reason": "continuation_cache_miss",
            "continuation_usage": continuation_usage,
        }
    return {
        "status": "valid",
        "wrapped_notice_count": wrapped_count,
        "system_marker_count": system_marker_count,
        "rewritten_profile_count": rewritten_count,
        "provider_request_count": provider_request_count,
        "continuation_usage": continuation_usage,
        "usage_source": usage_source,
    }


def _completed_usage_pair(
    usage: list[dict[str, Any]],
    upstream_usage: list[dict[str, int] | None] | None,
) -> tuple[list[dict[str, Any]], str]:
    if upstream_usage and len(upstream_usage) >= 2:
        pair = upstream_usage[-2:]
        if all(isinstance(item, dict) for item in pair):
            return [dict(item) for item in pair if isinstance(item, dict)], (
                "test_proxy_numeric_summary"
            )
    completed = [item["usage"] for item in usage if isinstance(item.get("usage"), dict)]
    return completed[-2:], "gateway_trace"


def _validate_fork_cache_contract(
    *,
    protocol: dict[str, Any],
    evidence: dict[str, Any],
    profiles: list[dict[str, Any]],
    usage: list[dict[str, Any]],
    provider_request_count: int,
    upstream_usage: list[dict[str, int] | None] | None = None,
) -> dict[str, Any]:
    parent_thread = protocol.get("parent_thread_id")
    fork_thread = protocol.get("fork_thread_id")
    if (
        not isinstance(parent_thread, str)
        or not isinstance(fork_thread, str)
        or parent_thread == fork_thread
        or protocol.get("forked_from_id") != parent_thread
        or protocol.get("parent_session_id") != parent_thread
        or protocol.get("fork_session_id") != fork_thread
    ):
        return {"status": "invalid", "reason": "fork_identity"}
    if (
        protocol.get("parent_status") != "completed"
        or protocol.get("fork_status") != "completed"
        or protocol.get("parent_agent_messages") != ["PARENT_OK"]
        or protocol.get("fork_agent_messages") != ["FORK_OK"]
    ):
        return {"status": "invalid", "reason": "fork_protocol_result"}
    if provider_request_count != 2 or evidence.get("request_count") != 2:
        return {
            "status": "invalid",
            "reason": "unexpected_provider_request_count",
            "provider_request_count": provider_request_count,
            "evidence_request_count": evidence.get("request_count"),
        }
    requests = evidence.get("requests")
    if not isinstance(requests, list) or len(requests) != 2:
        return {"status": "invalid", "reason": "fork_request_evidence"}
    wrapper_counts = [item.get("wrapped_system_user_count") for item in requests]
    rewritten_count = sum(
        int(profile.get("late_developer_rewritten_items", 0)) for profile in profiles
    )
    if wrapper_counts != [0, 1] or rewritten_count != 1:
        return {
            "status": "invalid",
            "reason": "late_developer_shape",
            "wrapped_system_user_counts": wrapper_counts,
            "rewritten_profile_count": rewritten_count,
        }
    if not evidence.get("parent_messages_are_fork_prefix"):
        return {"status": "invalid", "reason": "fork_prefix_changed"}
    if not evidence.get("tool_definitions_stable"):
        return {"status": "invalid", "reason": "tool_surface_changed"}
    usage_pair, usage_source = _completed_usage_pair(usage, upstream_usage)
    if len(usage_pair) != 2:
        return {"status": "invalid", "reason": "completed_usage_missing"}
    parent_usage, fork_usage = usage_pair
    cached_tokens = fork_usage.get("cached_tokens")
    parent_input = parent_usage.get("input_tokens")
    parent_output = parent_usage.get("output_tokens")
    if not isinstance(cached_tokens, int) or cached_tokens <= 0:
        return {
            "status": "invalid",
            "reason": "fork_cache_miss",
            "fork_usage": fork_usage,
        }
    adjacent_cache_delta = None
    if isinstance(parent_input, int) and isinstance(parent_output, int):
        adjacent_cache_delta = cached_tokens - (parent_input + parent_output)
    return {
        "status": "valid",
        "provider_request_count": provider_request_count,
        "wrapped_system_user_counts": wrapper_counts,
        "rewritten_profile_count": rewritten_count,
        "parent_messages_are_fork_prefix": True,
        "tool_definitions_stable": True,
        "prompt_cache_key_changed": evidence.get("prompt_cache_key_changed"),
        "parent_usage": parent_usage,
        "fork_usage": fork_usage,
        "adjacent_cache_delta": adjacent_cache_delta,
        "usage_source": usage_source,
    }


def _create_conda_env(run_root: Path) -> Path:
    env_path = run_root / "conda_env"
    completed = subprocess.run(
        ["conda", "create", "-p", str(env_path), "python=3.14.6", "pip", "-y"],
        check=False,
        capture_output=True,
        text=True,
    )
    (run_root / "artifacts" / "conda-create.log").write_text(
        completed.stdout + completed.stderr, encoding="utf-8"
    )
    if completed.returncode != 0:
        raise RuntimeError("failed to create isolated Conda environment")
    install = subprocess.run(
        [
            str(env_path / "bin" / "python"),
            "-m",
            "pip",
            "install",
            "-e",
            f"{ROOT}[gateway]",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    with (run_root / "artifacts" / "conda-create.log").open(
        "a", encoding="utf-8"
    ) as log:
        log.write("\n[pip install]\n" + install.stdout + install.stderr)
    if install.returncode != 0:
        raise RuntimeError("failed to install Rosetta into isolated Conda environment")
    gil = subprocess.run(
        [
            str(env_path / "bin" / "python"),
            "-c",
            "import sys; print(sys._is_gil_enabled())",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (run_root / "artifacts" / "python-gil.txt").write_text(gil + "\n", encoding="utf-8")
    if gil != "True":
        raise RuntimeError("isolated environment is not standard-GIL CPython")
    return env_path


def _profiles(run_root: Path) -> list[dict[str, Any]]:
    databases = list((run_root / "gateway").rglob("gateway.db"))
    if len(databases) != 1:
        return []
    with sqlite3.connect(databases[0]) as connection:
        rows = connection.execute("SELECT profile FROM request_log").fetchall()
    profiles: list[dict[str, Any]] = []
    for (raw,) in rows:
        try:
            value = json.loads(raw)
        except TypeError, ValueError:
            continue
        if isinstance(value, dict):
            profiles.append(value)
    return profiles


class _DeepSeekUserIdProxy(http.server.ThreadingHTTPServer):
    """Inject one isolated DeepSeek user id and retain numeric usage only."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], user_id: str):
        super().__init__(server_address, _DeepSeekUserIdHandler)
        self.user_id = user_id
        self.request_count = 0
        self.request_usage: list[dict[str, int] | None] = []
        self._request_count_lock = threading.Lock()

    def begin_request(self) -> int:
        with self._request_count_lock:
            request_index = self.request_count
            self.request_count += 1
            self.request_usage.append(None)
            return request_index

    def record_request_usage(
        self, request_index: int, usage: dict[str, int] | None
    ) -> None:
        with self._request_count_lock:
            self.request_usage[request_index] = usage


def _inject_deepseek_user_id(body: bytes, user_id: str) -> bytes:
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    payload["user_id"] = user_id
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _deepseek_usage_from_sse_line(line: bytes) -> dict[str, int] | None:
    """Extract a credential-free numeric usage summary from one SSE line."""

    if not line.startswith(b"data:"):
        return None
    raw = line[5:].strip()
    if not raw or raw == b"[DONE]":
        return None
    try:
        event = json.loads(raw)
    except UnicodeDecodeError, json.JSONDecodeError:
        return None
    if not isinstance(event, dict) or not isinstance(event.get("usage"), dict):
        return None
    usage = event["usage"]
    field_map = {
        "prompt_tokens": "input_tokens",
        "completion_tokens": "output_tokens",
        "total_tokens": "total_tokens",
        "prompt_cache_hit_tokens": "cached_tokens",
        "prompt_cache_miss_tokens": "cache_miss_tokens",
    }
    summary = {
        target: value
        for source, target in field_map.items()
        if isinstance((value := usage.get(source)), int) and not isinstance(value, bool)
    }
    return summary or None


class _DeepSeekUserIdHandler(http.server.BaseHTTPRequestHandler):
    """Forward Chat Completions requests while adding the run's user_id."""

    server: _DeepSeekUserIdProxy

    def do_POST(self) -> None:  # noqa: N802
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            self.send_error(http.HTTPStatus.LENGTH_REQUIRED)
            return
        try:
            body = _inject_deepseek_user_id(
                self.rfile.read(int(length_header)), self.server.user_id
            )
        except TypeError, ValueError:
            self.send_error(http.HTTPStatus.BAD_REQUEST, "invalid JSON")
            return
        headers = {
            name: value
            for name, value in self.headers.items()
            if name.lower() in {"authorization", "content-type", "accept"}
        }
        headers["Content-Length"] = str(len(body))
        request_index = self.server.begin_request()
        final_usage: dict[str, int] | None = None
        connection = http.client.HTTPSConnection("api.deepseek.com", timeout=600)
        try:
            connection.request("POST", self.path, body=body, headers=headers)
            response = connection.getresponse()
            self.send_response(response.status)
            for name, value in response.getheaders():
                if name.lower() not in {"connection", "transfer-encoding"}:
                    self.send_header(name, value)
            self.end_headers()
            line_buffer = b""
            while chunk := response.read(64 * 1024):
                line_buffer += chunk
                while b"\n" in line_buffer:
                    line, line_buffer = line_buffer.split(b"\n", 1)
                    if usage := _deepseek_usage_from_sse_line(line.rstrip(b"\r")):
                        final_usage = usage
                if len(line_buffer) > 1024 * 1024:
                    line_buffer = b""
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except BrokenPipeError, ConnectionResetError:
                    break
        finally:
            self.server.record_request_usage(request_index, final_usage)
            connection.close()

    def log_message(self, format: str, *args: Any) -> None:
        del format, args


def _start_deepseek_user_id_proxy(
    user_id: str,
) -> tuple[_DeepSeekUserIdProxy, threading.Thread]:
    proxy = _DeepSeekUserIdProxy(("127.0.0.1", 0), user_id)
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    return proxy, thread


def _set_provider_base_url(path: Path, provider_name: str, base_url: str) -> None:
    config = json.loads(_strip_jsonc_comments(path.read_text(encoding="utf-8")))
    providers = config.get("providers")
    provider = providers.get(provider_name) if isinstance(providers, dict) else None
    if not isinstance(provider, dict):
        raise RuntimeError(f"provider {provider_name!r} is missing from test config")
    provider["base_url"] = base_url.rstrip("/")
    _write_json(path, config)


def main() -> int:
    require_live_call_approval()
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("steer", "interrupt", "fork"), required=True)
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args()
    run_id = datetime.now().astimezone().strftime("%Y%m%d%H%M")
    run_root = ROOT / "tmp" / "agent_testing_workspace" / run_id
    gateway_log_root = Path("/Volumes/RAMDisk") / run_id
    if run_root.exists() or gateway_log_root.exists():
        raise RuntimeError(f"timestamped run root already exists: {run_id}")
    for directory in (
        run_root / "codex_home",
        run_root / "gateway",
        run_root / "artifacts",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    _copy_fixture(run_root)
    gateway_path = run_root / "gateway" / "config.jsonc"
    auth_path = run_root / "codex_home" / "auth.json"
    for secret_path in (gateway_path, auth_path):
        if (
            subprocess.run(
                ["git", "-C", str(ROOT), "check-ignore", "-q", str(secret_path)]
            ).returncode
            != 0
        ):
            raise RuntimeError(f"secret destination is not ignored: {secret_path}")
    shutil.copy2(GATEWAY_CONFIG_SOURCE, gateway_path)
    gateway_log_root.mkdir(parents=True)
    env_path = _create_conda_env(run_root)
    port = _free_port()
    client_key, providers = _configure_run(
        run_root,
        gateway_log_root,
        model=args.model,
        port=port,
        auto_compact_token_limit=100_000,
        expected_gateway_provider="Deepseek (Official)",
    )
    deepseek_user_id = "rosetta-test-" + secrets.token_hex(16)
    deepseek_proxy, deepseek_proxy_thread = _start_deepseek_user_id_proxy(
        deepseek_user_id
    )
    _set_provider_base_url(
        gateway_path,
        "Deepseek (Official)",
        f"http://127.0.0.1:{deepseek_proxy.server_address[1]}",
    )
    _disable_dynamic_surfaces(run_root)
    _validate_auth(run_root, port=port, client_key=client_key)
    _write_json(
        run_root / "artifacts" / "runtime-test.json",
        {
            "test_kind": f"automated_app_server_{args.mode}_interrupt_continuation",
            "model": args.model,
            "provider_identity": "codex_rosetta",
            "provider_display_name": "OpenAI",
            "gateway_providers": providers,
            "deepseek_user_id": deepseek_user_id,
            "deepseek_user_id_scope": "one fresh value per test invocation; reused within the invocation",
            "deepseek_proxy_port": deepseek_proxy.server_address[1],
            "trace_path": str(gateway_log_root / "rosetta-trace.jsonl"),
        },
    )
    stdout = (run_root / "gateway" / "stdout.log").open("wb")
    stderr = (run_root / "gateway" / "stderr.log").open("wb")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    gateway = subprocess.Popen(
        [
            str(env_path / "bin" / "python"),
            "-m",
            "codex_rosetta.gateway",
            "--config",
            str(run_root / "gateway"),
            "--codex-home",
            str(run_root / "codex_home"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--local-mode",
            "--confirm-clear-existing-catalog",
        ],
        stdout=stdout,
        stderr=stderr,
        env=env,
    )
    result: dict[str, Any]
    try:
        _wait_ready(port, client_key, gateway)
        result = _run_protocol(run_root, args.mode, args.model)
    except Exception as exc:
        result = {
            "classification": "failure",
            "runner_error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        gateway.terminate()
        try:
            gateway.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gateway.kill()
            gateway.wait(timeout=5)
        stdout.close()
        stderr.close()
        deepseek_proxy.shutdown()
        deepseek_proxy.server_close()
        deepseek_proxy_thread.join(timeout=5)
    result.update(
        {
            "mode": args.mode,
            "model": args.model,
            "profiles": _profiles(run_root),
            "trace_path": str(gateway_log_root / "rosetta-trace.jsonl"),
            "request_usage": trace_usage(gateway_log_root / "rosetta-trace.jsonl"),
            "request_surfaces": trace_surfaces(
                gateway_log_root / "rosetta-trace.jsonl"
            ),
            "deepseek_user_id_requests": deepseek_proxy.request_count,
            "deepseek_upstream_usage": deepseek_proxy.request_usage,
        }
    )
    trace_path = gateway_log_root / "rosetta-trace.jsonl"
    surface_check = _validate_trace_surfaces(result["request_surfaces"])
    if args.mode == "fork":
        result["fork_evidence"] = trace_fork_evidence(trace_path)
        contract_name = "fork_contract"
        contract_check = _validate_fork_cache_contract(
            protocol=result,
            evidence=result["fork_evidence"],
            profiles=result["profiles"],
            usage=result["request_usage"],
            provider_request_count=deepseek_proxy.request_count,
            upstream_usage=deepseek_proxy.request_usage,
        )
    else:
        contract_name = "interrupt_contract"
        contract_check = _validate_interrupt_cache_contract(
            mode=args.mode,
            surfaces=result["request_surfaces"],
            profiles=result["profiles"],
            usage=result["request_usage"],
            provider_request_count=deepseek_proxy.request_count,
            upstream_usage=deepseek_proxy.request_usage,
        )
    result["cache_comparison"] = {
        "surface": surface_check,
        contract_name: contract_check,
    }
    if result.get("classification") == "success" and surface_check["status"] != "valid":
        result["classification"] = "confounded"
        result["reason"] = surface_check["reason"]
    if (
        result.get("classification") == "success"
        and contract_check["status"] != "valid"
    ):
        result["classification"] = "failure"
        result["reason"] = contract_check["reason"]
    protocol_surface = result.get("protocol_surface")
    if (
        result.get("classification") == "success"
        and isinstance(protocol_surface, dict)
        and protocol_surface.get("tool_calls_observed")
    ):
        result["classification"] = "confounded"
        result["reason"] = "tool_call_observed"
    _write_json(run_root / "artifacts" / "automation-result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("classification") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
