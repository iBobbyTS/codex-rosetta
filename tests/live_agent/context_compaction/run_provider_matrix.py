#!/usr/bin/env python3
"""Run the isolated Pixel/Cockpit Provider compaction acceptance matrix."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SUITE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "live_agent"))

from codex_rosetta.gateway.config import _strip_jsonc_comments  # noqa: E402
from codex_rosetta.gateway.live_gate import require_live_call_approval  # noqa: E402
from context_compaction.provider_matrix import (  # noqa: E402
    run_matrix,
)
from context_compaction.run_live import (  # noqa: E402
    _AppServerClient,
)
from gateway_runtime import (  # noqa: E402
    GATEWAY_CONFIG_SOURCE,
    check_ignored,
    configure_gateway_and_codex,
    free_port,
    validate_auth,
    wait_ready,
    write_json,
)

MODEL = "gpt-5.6-terra"
PIXEL = "Pixel (Plus)"
COCKPIT = "Cockpit Tools"
CELL_INITIAL_PROVIDER = {
    "cell_1_pixel_native": PIXEL,
    "cell_2_cockpit_native_failure": COCKPIT,
    "cell_3_cockpit_rosetta_to_pixel": COCKPIT,
    "cell_4_pixel_to_cockpit_rosetta": PIXEL,
}


def _json_request(
    url: str,
    *,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if url.endswith("/login") else "PUT",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise RuntimeError("Admin API returned a non-object response")
    return payload


def _prepare_cell_config(
    run_root: Path, *, port: int, initial_provider: str, force_cockpit: bool
) -> tuple[str, dict[str, Any], str, str]:
    gateway_path = run_root / "gateway" / "config.jsonc"
    raw = json.loads(_strip_jsonc_comments(gateway_path.read_text(encoding="utf-8")))
    providers = raw.get("providers")
    groups = raw.get("model_groups")
    if not isinstance(providers, dict) or not isinstance(groups, dict):
        raise RuntimeError("copied Gateway config has no providers/model_groups")
    for required in (PIXEL, COCKPIT):
        provider = providers.get(required)
        if not isinstance(provider, dict):
            raise RuntimeError(f"copied Gateway config has no Provider {required!r}")
        if provider.get("api_type") != "responses":
            raise RuntimeError(f"Provider {required!r} is not Responses")
    providers[PIXEL].pop("force_rosetta_compaction", None)
    providers[COCKPIT]["force_rosetta_compaction"] = force_cockpit
    if providers[COCKPIT]["force_rosetta_compaction"] is False:
        providers[COCKPIT].pop("force_rosetta_compaction")

    matches = [
        (name, group)
        for name, group in groups.items()
        if isinstance(group, dict) and MODEL in group.get("models", {})
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one model group for {MODEL}, got {len(matches)}"
        )
    group_name, group = matches[0]
    group["provider"] = initial_provider
    server = raw.get("server")
    if not isinstance(server, dict) or not isinstance(
        server.get("admin_password"), str
    ):
        raise RuntimeError("copied Gateway config has no Admin password")
    admin_password = server["admin_password"]
    write_json(gateway_path, raw)
    client_key, _ = configure_gateway_and_codex(
        ROOT,
        run_root,
        Path("/Volumes/RAMDisk") / run_root.name,
        model=MODEL,
        port=port,
        auto_compact_token_limit=1_000_000,
        expected_gateway_provider=initial_provider,
    )
    return client_key, dict(group), group_name, admin_password


def _admin_switch(
    port: int,
    password: str,
    group_name: str,
    group: dict[str, Any],
    provider: str,
) -> None:
    base = f"http://127.0.0.1:{port}"
    token = _json_request(f"{base}/admin/api/login", body={"password": password}).get(
        "token"
    )
    if not isinstance(token, str) or not token:
        raise RuntimeError("Admin login did not return a token")
    body = {**group, "provider": provider}
    _json_request(
        f"{base}/admin/api/config/model-groups/{urllib.parse.quote(group_name, safe='')}",
        body=body,
        headers={"X-Admin-Token": token},
    )


def _thread_id(result: Any) -> str:
    value = result.get("thread", {}).get("id") if isinstance(result, dict) else None
    if not isinstance(value, str) or not value:
        raise RuntimeError("thread/start did not return a thread id")
    return value


def _turn_status(params: dict[str, Any]) -> str | None:
    turn = params.get("turn")
    return turn.get("status") if isinstance(turn, dict) else None


def _messages_contain(messages: list[dict[str, Any]], text: str) -> bool:
    return text in json.dumps(messages, ensure_ascii=False)


def _contains_type(value: Any, item_type: str) -> bool:
    if isinstance(value, dict):
        return value.get("type") == item_type or any(
            _contains_type(child, item_type) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_type(child, item_type) for child in value)
    return False


def _protocol(run_root: Path, cell: str, switch: Any) -> dict[str, Any]:
    client = _AppServerClient(run_root, timeout_seconds=420, record_protocol=False)
    step_results: list[dict[str, Any]] = []
    thread = ""

    def turn(request_id: int, marker: str) -> bool:
        start = len(client.messages)
        client.request(
            request_id,
            "turn/start",
            {
                "threadId": thread,
                "input": [{"type": "text", "text": f"Reply only {marker}"}],
            },
        )
        completed = client.wait_for_turn(thread)
        observed = _messages_contain(client.messages[start:], marker)
        step_results.append(
            {
                "operation": "turn",
                "marker": marker,
                "status": _turn_status(completed),
                "marker_observed": observed,
            }
        )
        return _turn_status(completed) == "completed" and observed

    def compact(request_id: int, *, expect_error: bool = False) -> bool:
        start = len(client.messages)
        request_error: str | None = None
        try:
            client.request(request_id, "thread/compact/start", {"threadId": thread})
            completed = client.wait_for_turn(thread)
            status = _turn_status(completed)
        except RuntimeError as exc:
            request_error = str(exc)
            status = "failed"
        messages = client.messages[start:]
        visible_error = _messages_contain(messages, "Upstream: model is required") or (
            request_error is not None and "Upstream: model is required" in request_error
        )
        installed = _contains_type(messages, "compaction")
        step_results.append(
            {
                "operation": "compact",
                "status": status,
                "expected_error": expect_error,
                "expected_error_observed": visible_error,
                "compaction_item_observed": installed,
            }
        )
        return visible_error if expect_error else status == "completed"

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
                "capabilities": {"experimentalApi": True, "requestAttestation": True},
            },
        )
        client.send({"method": "initialized", "params": {}})
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
        checks: list[bool] = [turn(3, f"{cell.upper()}:SEED_OK")]
        if cell == "cell_1_pixel_native":
            checks.extend([compact(4), turn(5, "CELL1:FOLLOWUP_OK")])
        elif cell == "cell_2_cockpit_native_failure":
            checks.append(compact(4, expect_error=True))
        elif cell == "cell_3_cockpit_rosetta_to_pixel":
            checks.append(compact(4))
            switch(PIXEL)
            checks.extend(
                [
                    turn(5, "CELL3:PIXEL_REPLAY_OK"),
                    compact(6),
                    turn(7, "CELL3:FINAL_OK"),
                ]
            )
        else:
            checks.append(compact(4))
            switch(COCKPIT)
            checks.extend(
                [
                    turn(5, "CELL4:COCKPIT_NATIVE_HISTORY_OK"),
                    compact(6),
                    turn(7, "CELL4:FINAL_OK"),
                ]
            )
        return {
            "success": all(checks),
            "thread_id": thread,
            "window_id": f"{thread}:0",
            "steps": step_results,
        }
    finally:
        client.close()


def _database_evidence(run_root: Path) -> dict[str, Any]:
    databases = list((run_root / "gateway").rglob("gateway.db"))
    if len(databases) != 1:
        return {"request_count": 0, "mapping_count": 0, "requests": []}
    with sqlite3.connect(databases[0]) as connection:
        rows = connection.execute(
            "SELECT id, model, status_code, target_provider_name, profile FROM request_log ORDER BY timestamp"
        ).fetchall()
        mapping_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM codex_compaction_mappings"
            ).fetchone()[0]
        )
    requests = []
    for request_id, model, status, provider, raw_profile in rows:
        profile = json.loads(raw_profile) if raw_profile else {}
        usage = profile.get("usage") if isinstance(profile.get("usage"), dict) else {}
        requests.append(
            {
                "request_id": request_id,
                "model": model,
                "status_code": status,
                "provider": provider,
                "compaction_mode": profile.get("compaction_mode"),
                "compaction_reason": profile.get("compaction_reason"),
                "compaction_forced_rosetta": profile.get("compaction_forced_rosetta")
                is True,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "cached_input_tokens": usage.get("cached_input_tokens"),
            }
        )
    previous: dict[str, Any] | None = None
    for request in requests:
        cached = request.get("cached_input_tokens")
        if isinstance(cached, int) and previous is not None:
            prior_input = previous.get("input_tokens")
            prior_output = previous.get("output_tokens")
            if isinstance(prior_input, int) and isinstance(prior_output, int):
                request["cache_delta"] = cached - (prior_input + prior_output)
        previous = request
    return {
        "request_count": len(requests),
        "mapping_count": mapping_count,
        "requests": requests,
    }


def _contains_string_prefix(value: Any, prefix: str) -> bool:
    if isinstance(value, str):
        return value.startswith(prefix)
    if isinstance(value, dict):
        return any(_contains_string_prefix(child, prefix) for child in value.values())
    if isinstance(value, list):
        return any(_contains_string_prefix(child, prefix) for child in value)
    return False


def _usage(value: Any) -> dict[str, int] | None:
    if isinstance(value, dict):
        if isinstance(value.get("input_tokens"), int) and isinstance(
            value.get("output_tokens"), int
        ):
            result = {
                "input_tokens": value["input_tokens"],
                "output_tokens": value["output_tokens"],
            }
            details = value.get("input_tokens_details")
            if isinstance(details, dict) and isinstance(
                details.get("cached_tokens"), int
            ):
                result["cached_input_tokens"] = details["cached_tokens"]
            elif isinstance(value.get("cached_input_tokens"), int):
                result["cached_input_tokens"] = value["cached_input_tokens"]
            return result
        for child in value.values():
            found = _usage(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _usage(child)
            if found is not None:
                return found
    return None


def _trace_evidence(path: Path) -> dict[str, Any]:
    evidence = {
        "trigger_request_ids": [],
        "trigger_model_present": [],
        "trigger_wire_passthrough": [],
        "native_compaction_input_observed": False,
        "native_compaction_providers": [],
        "rosetta_handle_sent_to_pixel": False,
        "cockpit_baseline_error": None,
        "usage_by_request": {},
    }
    starts: dict[str, bool] = {}
    trigger_trace_ids: list[str] = []
    if not path.is_file():
        return evidence
    for line in path.open(encoding="utf-8"):
        event = json.loads(line)
        trace_request_id = str(event.get("request_id", ""))
        request_id = str(event.get("request_log_id") or trace_request_id)
        provider = event.get("provider_name")
        stage = event.get("stage")
        data = event.get("data")
        usage = _usage(data)
        if usage is not None:
            evidence["usage_by_request"][request_id] = usage
        if stage == "stream_start" and isinstance(data, dict):
            starts[trace_request_id] = data.get("wire_passthrough") is True
        if stage in {"raw_passthrough_request", "source_request", "target_request"}:
            if _contains_type(data, "compaction_trigger"):
                trigger_trace_ids.append(trace_request_id)
                evidence["trigger_request_ids"].append(request_id)
                evidence["trigger_model_present"].append(
                    isinstance(data, dict)
                    and isinstance(data.get("model"), str)
                    and bool(data.get("model"))
                )
            if _contains_type(data, "compaction"):
                evidence["native_compaction_input_observed"] = True
                if provider and provider not in evidence["native_compaction_providers"]:
                    evidence["native_compaction_providers"].append(provider)
            if provider == PIXEL and _contains_string_prefix(data, "rskc_v1_"):
                evidence["rosetta_handle_sent_to_pixel"] = True
        if stage == "upstream_error" and isinstance(data, dict):
            error_text = json.dumps(data, ensure_ascii=False)
            if (
                data.get("status_code") == 400
                and "invalid_request" in error_text
                and "model is required" in error_text
                and data.get("error_phase") == "stream_header"
            ):
                evidence["cockpit_baseline_error"] = {
                    "status_code": 400,
                    "code": "invalid_request",
                    "message": "model is required",
                    "error_phase": "stream_header",
                }
    evidence["trigger_wire_passthrough"] = [
        starts.get(item, False) for item in trigger_trace_ids
    ]
    return evidence


def _cell_timestamp(index: int) -> str:
    return (
        datetime.now().astimezone().replace(second=0, microsecond=0)
        + timedelta(minutes=index)
    ).strftime("%Y%m%d%H%M")


def _run_cell(cell: str, index: int, timeout_seconds: int) -> dict[str, Any]:
    run_id = _cell_timestamp(index)
    run_root = ROOT / "tmp" / "agent_testing_workspace" / run_id
    trace_root = Path("/Volumes/RAMDisk") / run_id
    if run_root.exists() or trace_root.exists():
        raise RuntimeError(f"timestamped cell root already exists: {run_id}")
    for directory in (
        run_root / "worktree",
        run_root / "codex_home",
        run_root / "gateway",
        run_root / "artifacts",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SUITE / "common" / "AGENTS.md", run_root / "worktree" / "AGENTS.md")
    trace_root.mkdir(parents=True)
    gateway_path = run_root / "gateway" / "config.jsonc"
    auth_path = run_root / "codex_home" / "auth.json"
    check_ignored(ROOT, gateway_path, auth_path)
    shutil.copy2(GATEWAY_CONFIG_SOURCE, gateway_path)

    prefix = run_root / "conda_env"
    subprocess.run(
        [
            "conda",
            "create",
            "--yes",
            "--quiet",
            "--prefix",
            str(prefix),
            "python=3.14.6",
        ],
        check=True,
        timeout=timeout_seconds,
    )
    version = subprocess.run(
        [
            str(prefix / "bin" / "python"),
            "-c",
            "import sys; print(sys.version.split()[0]); print(sys._is_gil_enabled())",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if version != ["3.14.6", "True"]:
        raise RuntimeError(
            f"isolated prefix is not standard-GIL Python 3.14.6: {version}"
        )

    port = free_port()
    initial_provider = CELL_INITIAL_PROVIDER[cell]
    client_key, group, group_name, admin_password = _prepare_cell_config(
        run_root,
        port=port,
        initial_provider=initial_provider,
        force_cockpit=cell
        in {
            "cell_3_cockpit_rosetta_to_pixel",
            "cell_4_pixel_to_cockpit_rosetta",
        },
    )
    validate_auth(run_root, port=port, client_key=client_key)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    stdout = (run_root / "gateway" / "stdout.log").open("wb")
    stderr = (run_root / "gateway" / "stderr.log").open("wb")
    gateway = subprocess.Popen(
        [
            str(prefix / "bin" / "python"),
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
            "--no-banner",
            "--local-mode",
            "--confirm-clear-existing-catalog",
        ],
        stdout=stdout,
        stderr=stderr,
        env=env,
    )
    try:
        wait_ready(port, client_key, gateway)
        protocol = _protocol(
            run_root,
            cell,
            lambda provider: _admin_switch(
                port, admin_password, group_name, group, provider
            ),
        )
    finally:
        gateway.terminate()
        try:
            gateway.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gateway.kill()
            gateway.wait(timeout=5)
        stdout.close()
        stderr.close()
    database = _database_evidence(run_root)
    trace = _trace_evidence(trace_root / "rosetta-trace.jsonl")
    previous: dict[str, Any] | None = None
    for request in database["requests"]:
        usage = trace["usage_by_request"].get(request["request_id"], {})
        request.update(usage)
        cached = request.get("cached_input_tokens")
        if isinstance(cached, int) and previous is not None:
            prior_input = previous.get("input_tokens")
            prior_output = previous.get("output_tokens")
            if isinstance(prior_input, int) and isinstance(prior_output, int):
                request["cache_delta"] = cached - (prior_input + prior_output)
                request["cache_delta_material"] = abs(request["cache_delta"]) > 200
        previous = request
    trace.pop("usage_by_request")
    success = protocol["success"]
    if cell == "cell_1_pixel_native":
        success = (
            success
            and database["mapping_count"] == 0
            and trace["trigger_wire_passthrough"] == [True]
            and trace["native_compaction_input_observed"]
        )
    elif cell == "cell_2_cockpit_native_failure":
        success = (
            success
            and trace["cockpit_baseline_error"] is not None
            and trace["trigger_model_present"] == [True]
            and trace["trigger_wire_passthrough"] == [True]
        )
    elif cell == "cell_3_cockpit_rosetta_to_pixel":
        success = (
            success
            and database["mapping_count"] >= 1
            and any(item["compaction_forced_rosetta"] for item in database["requests"])
            and not trace["rosetta_handle_sent_to_pixel"]
        )
    else:
        success = (
            success
            and database["mapping_count"] >= 1
            and COCKPIT in trace["native_compaction_providers"]
        )
    success = success and not any(
        item["compaction_reason"] == "comp_hash_changed"
        for item in database["requests"]
    )
    result = {
        "cell": cell,
        "classification": "passed" if success else "failed",
        "run_id": run_id,
        "model": MODEL,
        "initial_provider": initial_provider,
        "python_version": version[0],
        "gil_enabled": version[1] == "True",
        **protocol,
        **database,
        **trace,
        "success": success,
    }
    write_json(run_root / "artifacts" / "provider-matrix-cell.json", result)
    return result


def main() -> int:
    require_live_call_approval()
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    indices = {cell: index for index, cell in enumerate(CELL_INITIAL_PROVIDER, start=1)}
    classification, cells = run_matrix(
        lambda cell: _run_cell(cell, indices[cell], args.timeout_seconds)
    )
    summary = {
        "suite": "provider_compaction_matrix",
        "classification": classification,
        "cells": cells,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return (
        0 if classification == "success" else (2 if classification == "blocked" else 1)
    )


if __name__ == "__main__":
    raise SystemExit(main())
