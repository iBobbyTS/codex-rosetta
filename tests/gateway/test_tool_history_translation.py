from __future__ import annotations

import json

from codex_rosetta.gateway.tool_history_translation import (
    ToolHistoryObjectKind,
    ToolHistorySnapshot,
)


def _history_body(call_id: str) -> dict:
    return {
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "exec_command",
                            "arguments": json.dumps(
                                {"cmd": "pwd", "metadata": {"id": "keep-me"}}
                            ),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": "workspace result",
                "metadata": {"id": "keep-result-id"},
            },
        ]
    }


def test_snapshot_replays_call_and_result_independently_with_current_ids():
    body = _history_body("fork-call")
    snapshot = ToolHistorySnapshot.capture(body)

    assert [item.kind for item in snapshot.objects] == [
        ToolHistoryObjectKind.CALL,
        ToolHistoryObjectKind.RESULT,
    ]
    assert "id" not in snapshot.objects[0].source_template
    assert (
        snapshot.objects[0]
        .source_template["function"]["arguments"]
        .endswith('"keep-me"}}')
    )
    assert "tool_call_id" not in snapshot.objects[1].source_template
    assert snapshot.objects[1].source_template["metadata"]["id"] == "keep-result-id"

    replayed = snapshot.apply(
        body,
        [
            {
                "type": "function",
                "function": {
                    "name": "Bash",
                    "arguments": json.dumps(
                        {"command": "pwd", "metadata": {"id": "keep-me"}}
                    ),
                },
            },
            {
                "role": "tool",
                "content": "workspace result",
                "metadata": {"id": "keep-result-id"},
            },
        ],
    )

    call = replayed["messages"][0]["tool_calls"][0]
    result = replayed["messages"][1]
    assert call["id"] == "fork-call"
    assert call["function"]["name"] == "Bash"
    assert json.loads(call["function"]["arguments"])["metadata"]["id"] == "keep-me"
    assert result["tool_call_id"] == "fork-call"
    assert result["metadata"]["id"] == "keep-result-id"


def test_snapshot_collects_only_missed_calls_changed_by_existing_translation():
    before = _history_body("call-new")
    snapshot = ToolHistorySnapshot.capture(before)
    localized = _history_body("call-new")
    localized["messages"][0]["tool_calls"][0]["function"]["name"] = "Bash"
    localized["messages"][0]["tool_calls"][0]["function"]["arguments"] = (
        '{"command":"pwd"}'
    )

    candidates = snapshot.collect_miss_candidates(localized, hit_indexes=set())

    assert [candidate.kind for candidate in candidates] == [
        ToolHistoryObjectKind.CALL,
        ToolHistoryObjectKind.RESULT,
    ]
    assert candidates[0].target_template["function"]["name"] == "Bash"
    assert candidates[1].source_template == candidates[1].target_template
