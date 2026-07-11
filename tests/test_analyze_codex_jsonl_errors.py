"""Regression tests for the bounded Codex JSONL error analyzer."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "analyze_codex_jsonl_errors.py"
)
SCRIPT = runpy.run_path(str(SCRIPT_PATH))
analyze_paths = SCRIPT["analyze_paths"]
render_markdown = SCRIPT["render_markdown"]
parse_args = SCRIPT["_parse_args"]


def _write_jsonl(path: Path, records: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def _tool_failure(message: str) -> dict[str, object]:
    return {
        "type": "response_item",
        "payload": {"type": "function_call_output", "output": message},
    }


def test_default_roots_follow_current_home_and_preserve_backup_root():
    args = parse_args([])

    assert args.roots == [
        Path.home() / ".codex" / "archived_sessions",
        Path.home() / ".codex" / "sessions",
        Path("/Volumes/Backups/AI Agent Sessions/Codex"),
    ]
    assert "/Users/ibobby/.codex" not in SCRIPT_PATH.read_text(encoding="utf-8")


def test_classifies_rate_limit_without_leaking_bearer_token(tmp_path: Path):
    log_path = tmp_path / "rollout-019f3cbf-be45-7813-9d46-ff29d2773507.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "schema_version": 1,
                "payload": {
                    "type": "inference_failed",
                    "error": "HTTP 429 rate limit; Authorization: Bearer sk-secret-token",
                },
            }
        ],
    )

    report = analyze_paths([], trace_roots=[tmp_path])

    assert report["categories"] == [
        {
            "key": "upstream_rate_limit",
            "label": "上游限流 (429)",
            "count": 1,
            "retry_advice": {
                "retry": "是，遵守 Retry-After，指数退避最多 2 次",
                "key_rotation": "可：仅确认限额为 key 级时",
                "provider_failover": "是：同能力候选 provider",
            },
        }
    ]
    signature = report["error_groups"][0]["signature"]
    assert "sk-secret-token" not in signature
    assert "<redacted>" in signature
    assert report["error_groups"][0]["evidence"] == "structured_provider"
    assert report["structured_provider_failover_candidates"] == {
        "upstream_rate_limit": 1
    }


def test_redaction_preserves_non_token_secrets_and_redacts_token_boundary():
    value = (
        "secret=ordinary-secret; client_secret=ordinary-client-secret; "
        "access_token=access-token-value; api_key=api-key-value; "
        "Authorization=Basic authorization-value; Bearer bearer-value"
    )

    redacted = SCRIPT["redact_text"](value)

    assert "secret=ordinary-secret" in redacted
    assert "client_secret=ordinary-client-secret" in redacted
    for sensitive in (
        "access-token-value",
        "api-key-value",
        "authorization-value",
        "bearer-value",
    ):
        assert sensitive not in redacted
    assert "access_token=<redacted>" in redacted
    assert "api_key=<redacted>" in redacted
    assert "Authorization=<redacted>" in redacted
    assert "Bearer <redacted>" in redacted


def test_redaction_covers_bare_gateway_internal_and_google_keys_only():
    gateway_key = "rsk-" + "a" * 48
    internal_key = "rsk-internal-" + "b" * 32
    google_key = "AIza" + "C" * 35
    preserved = (
        "password=keep-password; secret=keep-secret; "
        "client_secret=keep-client-secret; prompt=keep-prompt"
    )

    redacted = SCRIPT["redact_text"](
        f"{gateway_key} {internal_key} {google_key}; {preserved}"
    )

    assert redacted.count("<redacted-key>") == 3
    for token in (gateway_key, internal_key, google_key):
        assert token not in redacted
    for content in (
        "password=keep-password",
        "secret=keep-secret",
        "client_secret=keep-client-secret",
        "prompt=keep-prompt",
    ):
        assert content in redacted


def test_deduplicates_same_session_id_by_largest_copy(tmp_path: Path):
    session_id = "019f3cbf-be45-7813-9d46-ff29d2773507"
    first = tmp_path / "active" / f"rollout-{session_id}.jsonl"
    backup = tmp_path / "backup" / f"rollout-{session_id}.jsonl"
    _write_jsonl(
        first,
        [
            {
                "schema_version": 1,
                "payload": {"type": "inference_failed", "error": "HTTP 429 rate limit"},
            }
        ],
    )
    _write_jsonl(
        backup,
        [
            {
                "schema_version": 1,
                "payload": {"type": "inference_failed", "error": "HTTP 429 rate limit"},
            },
            {
                "schema_version": 1,
                "payload": {
                    "type": "inference_failed",
                    "error": "HTTP 503 service unavailable",
                },
            },
        ],
    )

    report = analyze_paths([], trace_roots=[tmp_path])

    assert report["scan"]["files_discovered"] == 2
    assert report["scan"]["files_selected"] == 1
    assert report["scan"]["duplicate_files_skipped"] == 1
    assert {category["key"] for category in report["categories"]} == {
        "upstream_rate_limit",
        "upstream_capacity",
    }


def test_bounds_oversized_lines_and_records_malformed_jsonl(tmp_path: Path):
    log_path = tmp_path / "history.jsonl"
    log_path.write_bytes(b'{"x":1}\n' + b"x" * 64 + b"\n" + b"{not-json}\n")

    report = analyze_paths([tmp_path], max_line_bytes=40)

    assert report["scan"]["oversized_lines_skipped"] == 1
    assert report["scan"]["malformed_lines"] == 1
    assert any(group["category"] == "invalid_jsonl" for group in report["error_groups"])
    assert "JSONL 损坏" in render_markdown(report)


def test_candidate_file_limit_accepts_exact_count_and_drops_plus_one(
    tmp_path: Path,
) -> None:
    for name in ("a", "b"):
        _write_jsonl(
            tmp_path / f"{name}.jsonl",
            [_tool_failure(f"fatal error retained-{name}")],
        )

    exact = analyze_paths([tmp_path], max_candidate_files=2)

    assert exact["scan"]["candidate_files_retained"] == 2
    assert exact["retention"]["candidate_files_dropped"] == 0

    _write_jsonl(
        tmp_path / "c.jsonl",
        [_tool_failure("fatal error dropped-c")],
    )
    truncated = analyze_paths([tmp_path], max_candidate_files=2)

    assert truncated["scan"]["files_discovered"] == 3
    assert truncated["scan"]["candidate_files_retained"] == 2
    assert truncated["scan"]["files_selected"] == 2
    assert truncated["retention"]["candidate_files_dropped"] == 1
    signatures = [group["signature"] for group in truncated["error_groups"]]
    assert signatures == ["fatal error retained-a", "fatal error retained-b"]
    assert "文件列表已截断：未保留 1 个候选文件" in render_markdown(truncated)


def test_error_group_limit_accepts_exact_count_and_drops_plus_one(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.jsonl"
    records: list[object] = [
        _tool_failure(f"fatal error group-{index}") for index in range(3)
    ]
    _write_jsonl(path, records)

    exact = analyze_paths([tmp_path], max_error_groups=3, sample_limit=0)

    assert len(exact["error_groups"]) == 3
    assert exact["retention"]["error_group_occurrences_dropped"] == 0
    assert all(not group["samples"] for group in exact["error_groups"])

    _write_jsonl(path, [*records, _tool_failure("fatal error group-extra")])
    truncated = analyze_paths([tmp_path], max_error_groups=3, sample_limit=0)

    assert len(truncated["error_groups"]) == 3
    assert truncated["categories"][0]["count"] == 4
    assert truncated["retention"]["error_group_occurrences_dropped"] == 1
    assert truncated["retention"]["error_group_overflow_by_category"] == {"unknown": 1}
    assert all(
        "overflow" not in group["signature"] for group in truncated["error_groups"]
    )
    assert "错误签名组已截断：未保留 1 次溢出记录" in render_markdown(truncated)


def test_error_group_limit_stays_deterministic_under_many_distinct_errors(
    tmp_path: Path,
) -> None:
    _write_jsonl(
        tmp_path / "history.jsonl",
        [_tool_failure(f"fatal error distinct-{index:03d}") for index in range(500)],
    )

    first = analyze_paths([tmp_path], max_error_groups=25, sample_limit=0)
    second = analyze_paths([tmp_path], max_error_groups=25, sample_limit=0)

    assert len(first["error_groups"]) == 25
    assert first["categories"][0]["count"] == 500
    assert first["retention"]["error_group_occurrences_dropped"] == 475
    assert first["retention"]["error_group_overflow_by_category"] == {"unknown": 475}
    assert [group["signature"] for group in first["error_groups"]] == [
        group["signature"] for group in second["error_groups"]
    ]
    assert all(not group["samples"] for group in first["error_groups"])


def test_ignores_prompt_text_and_detects_structured_tool_failure(tmp_path: Path):
    log_path = tmp_path / "history.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "content": "Mention error and permission denied in these instructions.",
                    "message": "HTTP 429 in a normal conversation item.",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": '{"message":"Wait timed out.","timed_out":true}',
                },
            },
        ],
    )

    report = analyze_paths([tmp_path])

    assert report["categories"][0]["key"] == "tool_timeout"
    assert report["categories"][0]["count"] == 1
    assert all(
        "Mention error" not in group["signature"] for group in report["error_groups"]
    )


def test_session_terminal_error_uses_real_shape_and_allows_failover(
    tmp_path: Path,
) -> None:
    _write_jsonl(
        tmp_path / "session.jsonl",
        [
            {
                "type": "event_msg",
                "payload": {
                    "type": "error",
                    "message": "upstream closed the connection",
                    "codex_error_info": {
                        "http_connection_failed": {"http_status_code": None}
                    },
                },
            }
        ],
    )

    report = analyze_paths([tmp_path])

    assert report["structured_provider_failover_candidates"] == {
        "upstream_connection": 1
    }
    assert len(report["error_groups"]) == 1
    group = report["error_groups"][0]
    assert group["evidence"] == "session_terminal"
    assert group["provider_failover_eligible"] is True
    assert "upstream closed the connection" in group["signature"]
    assert "Codex error: http connection failed" in group["signature"]


def test_session_terminal_generic_connection_message_needs_no_structured_info(
    tmp_path: Path,
) -> None:
    _write_jsonl(
        tmp_path / "session.jsonl",
        [
            {
                "type": "event_msg",
                "payload": {
                    "type": "error",
                    "message": "upstream closed the connection",
                },
            }
        ],
    )

    report = analyze_paths([tmp_path])

    assert report["structured_provider_failover_candidates"] == {
        "upstream_connection": 1
    }
    assert report["error_groups"][0]["category"] == "upstream_connection"


def test_session_stream_error_collects_details_without_authorizing_failover(
    tmp_path: Path,
) -> None:
    _write_jsonl(
        tmp_path / "session.jsonl",
        [
            {
                "type": "event_msg",
                "payload": {
                    "type": "stream_error",
                    "message": "connection reset by peer",
                    "additional_details": "HTTP 503 service unavailable",
                    "codex_error_info": {
                        "response_stream_disconnected": {"http_status_code": 503}
                    },
                },
            }
        ],
    )

    report = analyze_paths([tmp_path])

    assert report["structured_provider_failover_candidates"] == {}
    assert len(report["error_groups"]) == 1
    group = report["error_groups"][0]
    assert group["category"] == "upstream_capacity"
    assert group["evidence"] == "session_transient"
    assert group["provider_failover_eligible"] is False
    assert "connection reset by peer" in group["signature"]
    assert "HTTP 503 service unavailable" in group["signature"]
    assert "Codex error: response stream disconnected; HTTP 503" in group["signature"]


def test_only_terminal_session_event_authorizes_same_connection_failure(
    tmp_path: Path,
) -> None:
    _write_jsonl(
        tmp_path / "session.jsonl",
        [
            {
                "type": "event_msg",
                "payload": {
                    "type": "stream_error",
                    "message": "connection reset by peer",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "error",
                    "message": "connection reset by peer",
                },
            },
        ],
    )

    report = analyze_paths([tmp_path])

    assert report["structured_provider_failover_candidates"] == {
        "upstream_connection": 1
    }
    assert {
        (group["evidence"], group["provider_failover_eligible"])
        for group in report["error_groups"]
    } == {("session_transient", False), ("session_terminal", True)}


def test_trace_env_root_is_parsed_separately_from_session_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_root = tmp_path / "sessions"
    trace_root = tmp_path / "traces"
    shared_name = "rollout-019f3cbf-be45-7813-9d46-ff29d2773507.jsonl"
    _write_jsonl(
        session_root / shared_name,
        [
            {
                "type": "event_msg",
                "payload": {"type": "error", "message": "connection failed"},
            }
        ],
    )
    _write_jsonl(
        trace_root / shared_name,
        [
            {
                "schema_version": 1,
                "payload": {
                    "type": "inference_failed",
                    "error": "HTTP 503 service unavailable",
                },
            }
        ],
    )
    monkeypatch.setenv("CODEX_ROLLOUT_TRACE_ROOT", str(trace_root))

    args = parse_args([str(session_root)])
    report = analyze_paths(args.roots, trace_roots=args.trace_roots)

    assert args.trace_roots == [trace_root]
    assert report["trace_inputs"] == [str(trace_root)]
    assert report["scan"]["files_discovered"] == 2
    assert report["scan"]["files_selected"] == 2
    assert report["scan"]["duplicate_files_skipped"] == 0
    assert {group["evidence"] for group in report["error_groups"]} == {
        "session_terminal",
        "structured_provider",
    }

    reversed_report = analyze_paths([trace_root], trace_roots=[session_root])
    assert reversed_report["error_groups"] == []
    assert reversed_report["structured_provider_failover_candidates"] == {}


def test_structured_failed_container_keeps_non_keyword_message(
    tmp_path: Path,
) -> None:
    _write_jsonl(
        tmp_path / "session.jsonl",
        [
            {
                "type": "response_item",
                "payload": {
                    "status": "failed",
                    "message": "Provider disconnected before producing a response",
                },
            }
        ],
    )

    report = analyze_paths([tmp_path])

    assert report["structured_provider_failover_candidates"] == {}
    assert len(report["error_groups"]) == 1
    assert report["error_groups"][0]["category"] == "upstream_connection"
    assert report["error_groups"][0]["evidence"] == "structured_runtime"
