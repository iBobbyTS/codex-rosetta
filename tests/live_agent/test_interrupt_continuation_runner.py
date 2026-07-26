"""Deterministic checks for interrupt-continuation live evidence parsing."""

import json
import socketserver
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from interrupt_continuation.evidence import trace_usage
from interrupt_continuation.run_live import (
    _TURN_ABORTED_MARKER,
    _WRAPPED_TURN_ABORTED_NOTICE,
    _deepseek_usage_from_sse_line,
    _inject_deepseek_user_id,
    _request_surface,
    _validate_interrupt_cache_contract,
    _validate_trace_surfaces,
)


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


def test_request_surface_allows_canonical_turn_aborted_marker():
    base = _request_surface(
        {
            "messages": [
                {"role": "system", "content": "fixed instructions"},
                {"role": "user", "content": "hello"},
            ],
            "tools": [{"type": "function", "function": {"name": "plan"}}],
        }
    )
    interrupted = _request_surface(
        {
            "messages": [
                {"role": "system", "content": "fixed instructions"},
                {
                    "role": "system",
                    "content": _TURN_ABORTED_MARKER,
                },
                {"role": "user", "content": "hello"},
            ],
            "tools": [{"type": "function", "function": {"name": "plan"}}],
        }
    )

    assert interrupted["expected_turn_aborted_count"] == 1
    assert interrupted["context_fingerprint"] == base["context_fingerprint"]
    assert (
        _validate_trace_surfaces(
            [
                {
                    "request_id": "base",
                    "original_request": base,
                    "target_request": base,
                },
                {
                    "request_id": "interrupted",
                    "original_request": interrupted,
                    "target_request": interrupted,
                },
            ]
        )["status"]
        == "valid"
    )


def test_interrupt_contract_requires_wrapped_user_notice_and_cached_continuation():
    surface = _request_surface(
        {
            "messages": [
                {"role": "system", "content": "fixed instructions"},
                {"role": "user", "content": _WRAPPED_TURN_ABORTED_NOTICE},
                {"role": "user", "content": "continue"},
            ],
            "tools": [],
        }
    )

    assert surface["expected_turn_aborted_count"] == 0
    assert surface["wrapped_turn_aborted_count"] == 1
    assert _validate_interrupt_cache_contract(
        mode="interrupt",
        surfaces=[{"target_request": surface}],
        profiles=[{"interrupt_notice_rewritten_items": 1}],
        usage=[
            {
                "usage": {
                    "input_tokens": 15409,
                    "cached_tokens": 14336,
                    "output_tokens": 2,
                }
            }
        ],
        provider_request_count=3,
        upstream_usage=[
            None,
            None,
            {
                "input_tokens": 15409,
                "cached_tokens": 14336,
                "output_tokens": 2,
            },
        ],
    ) == {
        "status": "valid",
        "wrapped_notice_count": 1,
        "system_marker_count": 0,
        "rewritten_profile_count": 1,
        "provider_request_count": 3,
        "continuation_usage": {
            "input_tokens": 15409,
            "cached_tokens": 14336,
            "output_tokens": 2,
        },
        "usage_source": "test_proxy_numeric_summary",
    }


def test_interrupt_contract_rejects_native_system_marker_or_cache_miss():
    native = _request_surface(
        {
            "messages": [
                {"role": "system", "content": "fixed instructions"},
                {"role": "system", "content": _TURN_ABORTED_MARKER},
                {"role": "user", "content": "continue"},
            ],
            "tools": [],
        }
    )

    result = _validate_interrupt_cache_contract(
        mode="interrupt",
        surfaces=[{"target_request": native}],
        profiles=[],
        usage=[{"usage": {"input_tokens": 15409, "cached_tokens": 0}}],
        provider_request_count=3,
    )

    assert result["status"] == "invalid"
    assert result["reason"] == "interrupt_notice_shape"


def test_deepseek_user_id_proxy_overwrites_stale_id_without_changing_request():
    body = json.dumps(
        {"model": "deepseek-v4-flash", "messages": [], "user_id": "old"}
    ).encode()

    injected = json.loads(_inject_deepseek_user_id(body, "fresh-test-id"))

    assert injected == {
        "model": "deepseek-v4-flash",
        "messages": [],
        "user_id": "fresh-test-id",
    }


def test_deepseek_usage_from_sse_line_retains_only_numeric_usage():
    line = (
        b'data: {"usage":{"prompt_tokens":15409,"completion_tokens":2,'
        b'"total_tokens":15411,"prompt_cache_hit_tokens":14336,'
        b'"prompt_cache_miss_tokens":1073},"choices":[]}'
    )

    assert _deepseek_usage_from_sse_line(line) == {
        "input_tokens": 15409,
        "output_tokens": 2,
        "total_tokens": 15411,
        "cached_tokens": 14336,
        "cache_miss_tokens": 1073,
    }
    assert _deepseek_usage_from_sse_line(b"data: [DONE]") is None


def test_usage_recorder_does_not_override_http_server_lifecycle():
    from interrupt_continuation.run_live import _DeepSeekUserIdProxy

    assert _DeepSeekUserIdProxy.finish_request is socketserver.BaseServer.finish_request
