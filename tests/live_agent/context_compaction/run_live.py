#!/usr/bin/env python3
"""Run one isolated real-Codex context-compaction smoke test."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codex_rosetta.gateway.live_gate import require_live_call_approval
from gateway_runtime import (
    GATEWAY_CONFIG_SOURCE,
    check_ignored as _shared_check_ignored,
    codex_env as _codex_env,
    configure_gateway_and_codex,
    free_port as _free_port,
    validate_auth as _validate_auth,
    wait_ready as _wait_ready,
    write_json as _write_json,
)


SUITE = Path(__file__).resolve().parent
ROOT = SUITE.parents[2]
DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_TASK_ID = "02"
DEFAULT_TRIGGER = "manual"


def _is_gpt_model(model: str) -> bool:
    return model.startswith("gpt-")


def _check_ignored(*paths: Path) -> None:
    _shared_check_ignored(ROOT, *paths)


def _copy_task(run_root: Path, task_id: str) -> None:
    task = SUITE / task_id
    if not (task / "TASK.md").is_file() or not (task / "expected.json").is_file():
        raise ValueError(f"unknown context-compaction task: {task_id}")
    worktree = run_root / "worktree"
    shutil.copytree(SUITE / "common", worktree, dirs_exist_ok=True)
    shutil.copytree(task, worktree, dirs_exist_ok=True)


def _configure_run(
    run_root: Path,
    gateway_log_root: Path,
    *,
    model: str,
    port: int,
    auto_compact_token_limit: int,
    expected_gateway_provider: str | None,
) -> tuple[str, list[str]]:
    return configure_gateway_and_codex(
        ROOT,
        run_root,
        gateway_log_root,
        model=model,
        port=port,
        auto_compact_token_limit=auto_compact_token_limit,
        expected_gateway_provider=expected_gateway_provider,
    )


def _contains_item_type(value: Any, item_type: str) -> bool:
    if isinstance(value, dict):
        if value.get("type") == item_type:
            return True
        return any(_contains_item_type(child, item_type) for child in value.values())
    if isinstance(value, list):
        return any(_contains_item_type(child, item_type) for child in value)
    return False


def _trace_result(path: Path) -> dict[str, Any]:
    starts: dict[str, bool] = {}
    trigger_ids: set[str] = set()
    followup_ids: set[str] = set()
    errors: dict[str, int] = {}
    models: set[str] = set()
    if not path.is_file():
        return {
            "trace_present": False,
            "models": [],
            "trigger_request_count": 0,
            "trigger_wire_passthrough": [],
            "followup_compaction_input_observed": False,
            "trigger_upstream_errors": [],
            "upstream_error_statuses": [],
        }
    for line in path.open(encoding="utf-8"):
        event = json.loads(line)
        request_id = str(event.get("request_id", ""))
        model = event.get("model")
        if isinstance(model, str):
            models.add(model)
        stage = event.get("stage")
        data = event.get("data")
        if stage == "stream_start" and isinstance(data, dict):
            starts[request_id] = data.get("wire_passthrough") is True
        elif stage in {"raw_passthrough_request", "source_request", "target_request"}:
            if _contains_item_type(data, "compaction_trigger"):
                trigger_ids.add(request_id)
            elif _contains_item_type(data, "compaction"):
                followup_ids.add(request_id)
        elif stage == "upstream_error" and isinstance(data, dict):
            status = data.get("status_code")
            if isinstance(status, int):
                errors[request_id] = status
    return {
        "trace_present": True,
        "models": sorted(models),
        "trigger_request_count": len(trigger_ids),
        "trigger_wire_passthrough": [
            starts.get(item, False) for item in sorted(trigger_ids)
        ],
        "followup_compaction_input_observed": bool(followup_ids),
        "trigger_upstream_errors": [
            errors[item] for item in trigger_ids if item in errors
        ],
        "upstream_error_statuses": sorted(set(errors.values())),
    }


def _request_profiles(run_root: Path) -> list[dict[str, Any]]:
    databases = list((run_root / "gateway").rglob("gateway.db"))
    if len(databases) != 1:
        return []
    with sqlite3.connect(databases[0]) as connection:
        rows = connection.execute(
            "SELECT profile FROM request_log WHERE profile LIKE '%compaction_mode%'"
        ).fetchall()
    return [json.loads(profile) for (profile,) in rows]


def _compaction_mapping_count(run_root: Path) -> int:
    databases = list((run_root / "gateway").rglob("gateway.db"))
    if len(databases) != 1:
        return 0
    with sqlite3.connect(databases[0]) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM codex_compaction_mappings"
        ).fetchone()
    return int(row[0]) if row else 0


def _command_start_count(run_root: Path) -> int:
    path = run_root / "artifacts" / "codex.jsonl"
    if not path.is_file():
        return 0
    item_ids: set[str] = set()
    anonymous_starts = 0
    for line in path.open(encoding="utf-8"):
        event = json.loads(line)
        if event.get("type") != "item.started":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            item_ids.add(item_id)
        else:
            anonymous_starts += 1
    return len(item_ids) + anonymous_starts


def _count_matches_expected(
    observed: int,
    expected: dict[str, Any],
    *,
    exact_key: str,
    minimum_key: str,
) -> bool:
    exact = expected.get(exact_key)
    if isinstance(exact, int):
        return observed == exact
    minimum = expected.get(minimum_key)
    return not isinstance(minimum, int) or observed >= minimum


def _run_codex(run_root: Path, timeout_seconds: int) -> tuple[int, str | None]:
    prompt = (run_root / "worktree" / "TASK.md").read_text(encoding="utf-8")
    stdout_path = run_root / "artifacts" / "codex.jsonl"
    stderr_path = run_root / "artifacts" / "codex.stderr"
    final_path = run_root / "artifacts" / "final.txt"
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        try:
            completed = subprocess.run(
                [
                    "codex",
                    "exec",
                    "--json",
                    "--skip-git-repo-check",
                    "-C",
                    str(run_root / "worktree"),
                    "-o",
                    str(final_path),
                    prompt,
                ],
                check=False,
                stdout=stdout,
                stderr=stderr,
                env=_codex_env(run_root),
                timeout=timeout_seconds,
            )
            return completed.returncode, None
        except subprocess.TimeoutExpired:
            return 124, f"codex timed out after {timeout_seconds} seconds"


class _AppServerClient:
    def __init__(
        self, run_root: Path, timeout_seconds: int, *, record_protocol: bool = True
    ) -> None:
        self.protocol_path = run_root / "artifacts" / "app-server.jsonl"
        self.record_protocol = record_protocol
        self.deadline = time.monotonic() + timeout_seconds
        self.messages: list[dict[str, Any]] = []
        self._stderr = (run_root / "artifacts" / "app-server.stderr").open("wb")
        self.process = subprocess.Popen(
            ["codex", "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            env=_codex_env(run_root),
            text=True,
            bufsize=1,
        )
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("failed to open Codex app-server stdio")
        self._attestation = subprocess.Popen(
            ["node", str(SUITE / "devicecheck_attestation.js")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        ready = self._read_attestation_message()
        if ready != {"ready": True}:
            raise RuntimeError("DeviceCheck attestation helper did not become ready")

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def receive(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        while time.monotonic() < self.deadline:
            line = self.process.stdout.readline()
            if line:
                message = json.loads(line)
                self.messages.append(message)
                if self.record_protocol:
                    with self.protocol_path.open("a", encoding="utf-8") as artifact:
                        artifact.write(json.dumps(message, ensure_ascii=False) + "\n")
                return message
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"Codex app-server exited with {self.process.returncode}"
                )
        raise TimeoutError("Codex app-server protocol timed out")

    def _read_attestation_message(self) -> dict[str, Any]:
        if self._attestation.stdout is None:
            raise RuntimeError("DeviceCheck attestation helper stdout is unavailable")
        line = self._attestation.stdout.readline()
        if not line:
            raise RuntimeError("DeviceCheck attestation helper disconnected")
        message = json.loads(line)
        if not isinstance(message, dict):
            raise RuntimeError("DeviceCheck attestation helper returned invalid output")
        return message

    def _generate_attestation(self) -> str:
        if self._attestation.stdin is None:
            raise RuntimeError("DeviceCheck attestation helper stdin is unavailable")
        self._attestation.stdin.write("generate\n")
        self._attestation.stdin.flush()
        message = self._read_attestation_message()
        token = message.get("token")
        if not isinstance(token, str) or not token:
            raise RuntimeError(
                f"DeviceCheck attestation generation failed: {message.get('error')}"
            )
        return token

    def _handle_server_request(self, message: dict[str, Any]) -> bool:
        if message.get("method") != "attestation/generate" or "id" not in message:
            return False
        self.send(
            {
                "id": message["id"],
                "result": {"token": self._generate_attestation()},
            }
        )
        return True

    def request(self, request_id: int, method: str, params: dict[str, Any]) -> Any:
        self.send({"method": method, "id": request_id, "params": params})
        while True:
            message = self.receive()
            if self._handle_server_request(message):
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"{method} failed: {message['error']}")
            return message.get("result")

    def wait_for_turn(self, thread_id: str) -> dict[str, Any]:
        while True:
            message = self.receive()
            if self._handle_server_request(message):
                continue
            if message.get("method") != "turn/completed":
                continue
            params = message.get("params")
            if isinstance(params, dict) and params.get("threadId") == thread_id:
                return params

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self._attestation.terminate()
        try:
            self._attestation.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._attestation.kill()
            self._attestation.wait(timeout=5)
        self._stderr.close()


def _require_completed_turn(params: dict[str, Any], label: str) -> None:
    turn = params.get("turn")
    if not isinstance(turn, dict) or turn.get("status") != "completed":
        raise RuntimeError(f"{label} turn did not complete")


def _run_manual_compact(
    run_root: Path, timeout_seconds: int, success_marker: str
) -> tuple[int, str | None]:
    client = _AppServerClient(run_root, timeout_seconds)

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
        started = client.request(
            2,
            "thread/start",
            {
                "cwd": str(run_root / "worktree"),
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
            },
        )
        thread = started.get("thread") if isinstance(started, dict) else None
        thread_id = thread.get("id") if isinstance(thread, dict) else None
        if not isinstance(thread_id, str) or not thread_id:
            raise RuntimeError("thread/start did not return a thread id")
        client.request(
            3,
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": "Reply only READY:MANUAL_COMPACT"}],
            },
        )
        _require_completed_turn(client.wait_for_turn(thread_id), "seed")
        client.request(4, "thread/compact/start", {"threadId": thread_id})
        _require_completed_turn(client.wait_for_turn(thread_id), "manual compact")
        client.request(
            5,
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": f"Reply only {success_marker}"}],
            },
        )
        _require_completed_turn(client.wait_for_turn(thread_id), "post-compact")
        observed = success_marker in json.dumps(client.messages, ensure_ascii=False)
        (run_root / "artifacts" / "final.txt").write_text(
            success_marker if observed else "",
            encoding="utf-8",
        )
        return (0, None) if observed else (1, "success marker not observed")
    except TimeoutError as exc:
        return 124, str(exc)
    except RuntimeError as exc:
        return 1, str(exc)
    finally:
        client.close()


def main() -> int:
    require_live_call_approval()
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    parser.add_argument(
        "--trigger",
        choices=("manual", "context-limit"),
        default=DEFAULT_TRIGGER,
    )
    parser.add_argument("--timeout-seconds", type=int)
    args = parser.parse_args()

    expected = json.loads(
        (SUITE / args.task_id / "expected.json").read_text(encoding="utf-8")
    )
    timeout_seconds = args.timeout_seconds or int(expected["timeout_seconds"])
    run_id = datetime.now().astimezone().strftime("%Y%m%d%H%M")
    run_root = ROOT / "tmp" / "agent_testing_workspace" / run_id
    gateway_log_root = Path("/Volumes/RAMDisk") / run_id
    if run_root.exists() or gateway_log_root.exists():
        raise RuntimeError(f"timestamped run root already exists: {run_id}")
    for directory in (
        run_root / "worktree",
        run_root / "codex_home",
        run_root / "gateway",
        run_root / "artifacts",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    _copy_task(run_root, args.task_id)

    gateway_path = run_root / "gateway" / "config.jsonc"
    auth_path = run_root / "codex_home" / "auth.json"
    _check_ignored(gateway_path, auth_path)
    shutil.copy2(GATEWAY_CONFIG_SOURCE, gateway_path)
    gateway_log_root.mkdir(parents=True)
    (run_root / "artifacts" / "gateway-log-root.txt").write_text(
        str(gateway_log_root) + "\n",
        encoding="utf-8",
    )

    port = _free_port()
    try:
        client_key, configured_providers = _configure_run(
            run_root,
            gateway_log_root,
            model=args.model,
            port=port,
            auto_compact_token_limit=int(expected["model_auto_compact_token_limit"]),
            expected_gateway_provider=(
                None if _is_gpt_model(args.model) else expected.get("gateway_provider")
            ),
        )
    except RuntimeError as exc:
        result = {
            "suite": "context_compaction",
            "task_id": args.task_id,
            "trigger": args.trigger,
            "classification": "user_decision_required",
            "success": False,
            "user_decision_required": True,
            "model": args.model,
            "runner_error": str(exc),
        }
        _write_json(run_root / "artifacts" / "automation-result.json", result)
        print(json.dumps(result, ensure_ascii=False))
        return 2
    _validate_auth(run_root, port=port, client_key=client_key)

    stdout = (run_root / "gateway" / "stdout.log").open("wb")
    stderr = (run_root / "gateway" / "stderr.log").open("wb")
    gateway = subprocess.Popen(
        [
            "codex-rosetta-gateway",
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
    )
    (run_root / "gateway" / "pid").write_text(str(gateway.pid) + "\n")
    codex_exit = 1
    runner_error: str | None = None
    try:
        _wait_ready(port, client_key, gateway)
        if args.trigger == "manual":
            codex_exit, runner_error = _run_manual_compact(
                run_root,
                timeout_seconds,
                expected["success_marker"],
            )
        else:
            codex_exit, runner_error = _run_codex(run_root, timeout_seconds)
    finally:
        gateway.terminate()
        try:
            gateway.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gateway.kill()
            gateway.wait(timeout=5)
        stdout.close()
        stderr.close()

    final_path = run_root / "artifacts" / "final.txt"
    final_text = final_path.read_text(encoding="utf-8") if final_path.is_file() else ""
    trace = _trace_result(gateway_log_root / "rosetta-trace.jsonl")
    profiles = _request_profiles(run_root)
    expected_mode = str(expected["expected_mode"])
    expected_reason = (
        "user_requested"
        if args.trigger == "manual"
        else str(expected["expected_reason"])
    )
    matching_profiles = [
        profile
        for profile in profiles
        if profile.get("compaction_mode") == expected_mode
        and profile.get("compaction_reason") == expected_reason
    ]
    mapping_count = _compaction_mapping_count(run_root)
    command_start_count = _command_start_count(run_root)
    profile_count_matches = _count_matches_expected(
        len(matching_profiles),
        expected,
        exact_key="expected_compaction_count",
        minimum_key="required_complete_protocol_chains_min",
    )
    mapping_count_matches = _count_matches_expected(
        mapping_count,
        expected,
        exact_key="expected_rosetta_mapping_rows",
        minimum_key="expected_rosetta_mapping_rows_min",
    )
    command_count_matches = args.trigger == "manual" or _count_matches_expected(
        command_start_count,
        expected,
        exact_key="expected_command_starts",
        minimum_key="expected_command_starts_min",
    )
    common_success = (
        codex_exit == 0
        and expected["success_marker"] in final_text
        and not trace["trigger_upstream_errors"]
        and trace["followup_compaction_input_observed"]
        and profile_count_matches
        and mapping_count_matches
        and command_count_matches
    )
    if expected_mode == "native":
        success = (
            common_success
            and trace["trigger_request_count"] == 1
            and trace["trigger_wire_passthrough"] == [True]
            and len(matching_profiles) == 1
            and matching_profiles[0].get("wire_passthrough") is True
        )
    else:
        success = common_success and trace["trigger_request_count"] >= 1
    provider_unavailable = any(
        status in {401, 403, 404, 408, 429, 500, 502, 503, 504}
        for status in trace["upstream_error_statuses"]
    )
    configuration_blocked = bool(
        runner_error
        and (
            "failed to load configuration" in runner_error
            or "model_catalog" in runner_error
        )
    )
    if success:
        classification = "completed"
    elif provider_unavailable or configuration_blocked:
        classification = "provider_unavailable_requires_user_decision"
    elif trace["trigger_upstream_errors"]:
        classification = "remote_compaction_error_reproduced"
    elif not matching_profiles and trace["trigger_request_count"] == 0:
        classification = "not_triggered"
    else:
        classification = "infrastructure_failure"
    result = {
        "suite": "context_compaction",
        "task_id": args.task_id,
        "trigger": args.trigger,
        "classification": classification,
        "success": success,
        "user_decision_required": provider_unavailable or configuration_blocked,
        "model": args.model,
        "model_substitution": args.model != expected.get("default_model"),
        "gateway_provider": (
            configured_providers[0] if len(configured_providers) == 1 else None
        ),
        "gateway_providers": configured_providers,
        "codex_model_provider": "codex_rosetta",
        "codex_exit_code": codex_exit,
        "success_marker_observed": expected["success_marker"] in final_text,
        "runner_error": runner_error,
        **trace,
        "expected_compaction_mode": expected_mode,
        "matching_compaction_profile_count": len(matching_profiles),
        "matching_profile_wire_passthrough": [
            profile.get("wire_passthrough") is True for profile in matching_profiles
        ],
        "rosetta_compaction_mapping_count": mapping_count,
        "command_start_count": command_start_count,
        "profile_count_matches": profile_count_matches,
        "mapping_count_matches": mapping_count_matches,
        "command_count_matches": command_count_matches,
    }
    _write_json(run_root / "artifacts" / "automation-result.json", result)
    print(run_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
