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
