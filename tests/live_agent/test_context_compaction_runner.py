"""Tests for the isolated context-compaction live runner evaluator."""

from __future__ import annotations

import json
import os
import runpy
import select
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest


RUNNER = runpy.run_path(
    str(Path(__file__).parent / "context_compaction" / "run_live.py"),
    run_name="context_compaction_live_runner",
)
_command_start_count = RUNNER["_command_start_count"]
_count_matches_expected = RUNNER["_count_matches_expected"]
_trace_result = RUNNER["_trace_result"]
_app_server_command = RUNNER["_app_server_command"]

MATRIX = runpy.run_path(
    str(Path(__file__).parent / "context_compaction" / "provider_matrix.py"),
    run_name="provider_compaction_matrix",
)
evaluate_matrix = MATRIX["evaluate_matrix"]
run_matrix = MATRIX["run_matrix"]

LIVE_MATRIX_RUNNER = runpy.run_path(
    str(Path(__file__).parent / "context_compaction" / "run_provider_matrix.py"),
    run_name="provider_compaction_live_runner",
)
_provider_trace_evidence = LIVE_MATRIX_RUNNER["_trace_evidence"]


def test_trace_result_observes_converted_rosetta_compaction_requests(tmp_path) -> None:
    trace = tmp_path / "trace.jsonl"
    events = [
        {
            "request_id": "trigger",
            "model": "deepseek-v4-flash",
            "stage": "source_request",
            "data": {"input": [{"type": "compaction_trigger"}]},
        },
        {
            "request_id": "followup",
            "model": "deepseek-v4-flash",
            "stage": "target_request",
            "data": {"messages": [{"type": "compaction"}]},
        },
    ]
    trace.write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )

    result = _trace_result(trace)

    assert result["trigger_request_count"] == 1
    assert result["followup_compaction_input_observed"] is True
    assert result["trigger_wire_passthrough"] == [False]


def test_command_start_count_deduplicates_item_ids(tmp_path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    events = [
        {
            "type": "item.started",
            "item": {"id": "command-1", "type": "command_execution"},
        },
        {
            "type": "item.started",
            "item": {"id": "command-1", "type": "command_execution"},
        },
        {
            "type": "item.completed",
            "item": {"id": "command-1", "type": "command_execution"},
        },
    ]
    (artifacts / "codex.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )

    assert _command_start_count(tmp_path) == 1


def test_count_matches_exact_or_minimum_contract() -> None:
    assert _count_matches_expected(
        1, {"exact": 1}, exact_key="exact", minimum_key="minimum"
    )
    assert not _count_matches_expected(
        2, {"exact": 1}, exact_key="exact", minimum_key="minimum"
    )
    assert _count_matches_expected(
        2, {"minimum": 1}, exact_key="exact", minimum_key="minimum"
    )


def _standalone_app_server_command() -> list[str]:
    command = _app_server_command()
    if command[0] == "codex":
        pytest.skip("standalone codex-app-server binary is not available")
    return command


def test_app_server_command_honors_explicit_binary_override(
    monkeypatch, tmp_path
) -> None:
    binary = tmp_path / "codex-app-server"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("CODEX_APP_SERVER_BIN", str(binary))

    assert _app_server_command() == [str(binary), "--listen", "stdio://"]


def test_codex_0149_standalone_app_server_reports_its_version() -> None:
    command = _standalone_app_server_command()
    completed = subprocess.run(
        [command[0], "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "codex-app-server 0.149.0"


def test_codex_0149_standalone_app_server_completes_stdio_initialize(tmp_path) -> None:
    command = _standalone_app_server_command()
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )
    try:
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "codex-rosetta-test",
                            "title": "Codex Rosetta Test",
                            "version": "0.149.0",
                        },
                        "capabilities": {
                            "experimentalApi": True,
                            "requestAttestation": False,
                            "mcpServerOpenAIFormElicitation": False,
                        },
                    },
                }
            )
            + "\n"
        )
        process.stdin.flush()
        ready, _, _ = select.select([process.stdout], [], [], 20)
        if not ready:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(
                f"standalone app-server did not answer initialize: {stderr}"
            )
        line = process.stdout.readline()
        if not line:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(
                f"standalone app-server closed before initialize response: {stderr}"
            )
        response = json.loads(line)
        assert response["id"] == 1
        assert response["result"]["userAgent"].endswith("; 0.149.0)")
        assert response["result"]["codexHome"] == str(codex_home)
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)


def test_codex_0149_standalone_app_server_serves_websocket_readyz(tmp_path) -> None:
    command = _standalone_app_server_command()
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [command[0], "--listen", f"ws://127.0.0.1:{port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )
    try:
        response = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/readyz", timeout=0.5
                ) as ready:
                    response = (ready.status, ready.read().decode())
                    break
            except OSError:
                if process.poll() is not None:
                    break
                time.sleep(0.1)
        if response is None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(
                f"standalone app-server did not become ready: {stderr}"
            )
        assert response == (200, "")
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)


def test_provider_matrix_baseline_mismatch_is_blocked() -> None:
    assert (
        evaluate_matrix(
            {
                "cell_1_pixel_native": {"success": True},
                "cell_2_cockpit_native_failure": {"success": False},
            }
        )
        == "blocked"
    )


def test_provider_matrix_runs_second_baseline_after_first_runner_error() -> None:
    calls: list[str] = []

    def run_cell(cell: str) -> dict[str, object]:
        calls.append(cell)
        if cell == "cell_1_pixel_native":
            raise RuntimeError("cell one infrastructure failure")
        return {"success": True}

    classification, cells = run_matrix(run_cell)

    assert classification == "blocked"
    assert calls == ["cell_1_pixel_native", "cell_2_cockpit_native_failure"]
    assert cells["cell_1_pixel_native"] == {
        "success": False,
        "classification": "runner_error",
        "error_type": "RuntimeError",
    }


def test_provider_matrix_success_requires_both_main_cells() -> None:
    cells = {
        "cell_1_pixel_native": {"success": True},
        "cell_2_cockpit_native_failure": {"success": True},
        "cell_3_cockpit_rosetta_to_pixel": {"success": True},
        "cell_4_pixel_to_cockpit_rosetta": {"success": True},
    }
    assert evaluate_matrix(cells) == "success"
    cells["cell_3_cockpit_rosetta_to_pixel"]["success"] = False
    assert evaluate_matrix(cells) == "failure"


def test_provider_matrix_runs_cell_four_after_cell_three_failure() -> None:
    calls: list[str] = []

    def run_cell(cell: str) -> dict[str, object]:
        calls.append(cell)
        return {"success": cell != "cell_3_cockpit_rosetta_to_pixel"}

    classification, _ = run_matrix(run_cell)

    assert classification == "failure"
    assert calls == [
        "cell_1_pixel_native",
        "cell_2_cockpit_native_failure",
        "cell_3_cockpit_rosetta_to_pixel",
        "cell_4_pixel_to_cockpit_rosetta",
    ]


def test_provider_trace_evidence_uses_request_log_id_and_provider(tmp_path) -> None:
    trace = tmp_path / "trace.jsonl"
    events = [
        {
            "request_id": "trace-trigger",
            "request_log_id": "logged-trigger",
            "provider_name": "Pixel (Plus)",
            "stage": "stream_start",
            "data": {"wire_passthrough": True},
        },
        {
            "request_id": "trace-trigger",
            "request_log_id": "logged-trigger",
            "provider_name": "Pixel (Plus)",
            "stage": "raw_passthrough_request",
            "data": {
                "model": "gpt-5.6-terra",
                "input": [{"type": "compaction_trigger"}],
            },
        },
        {
            "request_id": "trace-replay",
            "request_log_id": "logged-replay",
            "provider_name": "Cockpit Tools",
            "stage": "raw_passthrough_request",
            "data": {"input": [{"type": "compaction", "opaque": "redacted"}]},
        },
    ]
    trace.write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )

    evidence = _provider_trace_evidence(trace)

    assert evidence["trigger_request_ids"] == ["logged-trigger"]
    assert evidence["trigger_model_present"] == [True]
    assert evidence["trigger_wire_passthrough"] == [True]
    assert evidence["native_compaction_providers"] == ["Cockpit Tools"]
