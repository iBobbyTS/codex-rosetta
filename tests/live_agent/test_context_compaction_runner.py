"""Tests for the isolated context-compaction live runner evaluator."""

from __future__ import annotations

import json
import runpy
from pathlib import Path


RUNNER = runpy.run_path(
    str(Path(__file__).parent / "context_compaction" / "run_live.py"),
    run_name="context_compaction_live_runner",
)
_command_start_count = RUNNER["_command_start_count"]
_count_matches_expected = RUNNER["_count_matches_expected"]
_trace_result = RUNNER["_trace_result"]

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
