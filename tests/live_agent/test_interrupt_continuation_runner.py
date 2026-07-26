"""Deterministic checks for interrupt-continuation live evidence parsing."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from interrupt_continuation.evidence import trace_usage
from interrupt_continuation.run_live import _request_surface, _validate_trace_surfaces


def test_trace_usage_keeps_request_tokens_and_signed_cache_delta(tmp_path):
    path = tmp_path / "trace.jsonl"
    events = [
        {
            "request_id": "first",
            "stage": "target_request",
            "data": {"messages": [{"role": "system"}]},
        },
        {
            "request_id": "first",
            "stage": "upstream_chunk",
            "data": {
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 4,
                    "total_tokens": 104,
                    "input_tokens_details": {
                        "cached_tokens": 40,
                        "cache_write_tokens": 0,
                    },
                }
            },
        },
        {
            "request_id": "second",
            "stage": "target_request",
            "data": {"messages": [{"role": "system"}, {"role": "user"}]},
        },
        {
            "request_id": "second",
            "stage": "source_event",
            "data": {
                "response": {
                    "usage": {
                        "input_tokens": 120,
                        "output_tokens": 5,
                        "total_tokens": 125,
                        "input_tokens_details": {
                            "cached_tokens": 96,
                            "cache_write_tokens": 0,
                        },
                    }
                }
            },
        },
    ]
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n")

    assert trace_usage(path) == [
        {
            "request_id": "first",
            "target_message_count": 1,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 4,
                "total_tokens": 104,
                "cached_tokens": 40,
                "cache_write_tokens": 0,
            },
            "cached_tokens_delta": None,
        },
        {
            "request_id": "second",
            "target_message_count": 2,
            "usage": {
                "input_tokens": 120,
                "output_tokens": 5,
                "total_tokens": 125,
                "cached_tokens": 96,
                "cache_write_tokens": 0,
            },
            "cached_tokens_delta": 56,
        },
    ]


def test_request_surface_rejects_dynamic_skill_plugin_context():
    clean = _request_surface(
        {
            "messages": [
                {"role": "system", "content": "fixed instructions"},
                {"role": "user", "content": "hello"},
            ],
            "tools": [{"type": "function", "function": {"name": "plan"}}],
        }
    )
    contaminated = _request_surface(
        {
            "messages": [
                {
                    "role": "system",
                    "content": "fixed instructions\n<plugins_instructions>",
                }
            ],
            "tools": [{"type": "function", "function": {"name": "plan"}}],
        }
    )

    assert clean["dynamic_marker_hits"] == []
    assert contaminated["dynamic_marker_hits"] == ["<plugins_instructions>"]
    assert _validate_trace_surfaces(
        [
            {"request_id": "clean", "target_request": clean},
            {"request_id": "contaminated", "target_request": contaminated},
        ]
    ) == {
        "status": "confounded",
        "reason": "dynamic_context_marker",
        "markers": ["<plugins_instructions>"],
    }


def test_request_surface_requires_stable_tool_surface():
    base = _request_surface(
        {
            "messages": [{"role": "system", "content": "fixed"}],
            "tools": [{"type": "function", "function": {"name": "plan"}}],
        }
    )
    changed = _request_surface(
        {
            "messages": [{"role": "system", "content": "fixed"}],
            "tools": [
                {"type": "function", "function": {"name": "plan"}},
                {"type": "function", "function": {"name": "new_tool"}},
            ],
        }
    )

    result = _validate_trace_surfaces(
        [
            {
                "request_id": "base",
                "original_request": base,
                "target_request": base,
            },
            {
                "request_id": "changed",
                "original_request": base,
                "target_request": changed,
            },
        ]
    )
    assert result["status"] == "confounded"
    assert result["reason"] == "tool_surface_changed"
