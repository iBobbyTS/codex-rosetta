"""Regression tests for the bounded Codex JSONL error analyzer."""

from __future__ import annotations

import json
import runpy
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "analyze_codex_jsonl_errors.py"
)
SCRIPT = runpy.run_path(str(SCRIPT_PATH))
analyze_paths = SCRIPT["analyze_paths"]
render_markdown = SCRIPT["render_markdown"]


def _write_jsonl(path: Path, records: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def test_classifies_rate_limit_without_leaking_bearer_token(tmp_path: Path):
    log_path = tmp_path / "rollout-019f3cbf-be45-7813-9d46-ff29d2773507.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "type": "response_item",
                "payload": {
                    "message": "HTTP 429 rate limit; Authorization: Bearer sk-secret-token"
                },
            }
        ],
    )

    report = analyze_paths([tmp_path])

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


def test_deduplicates_same_session_id_by_largest_copy(tmp_path: Path):
    session_id = "019f3cbf-be45-7813-9d46-ff29d2773507"
    first = tmp_path / "active" / f"rollout-{session_id}.jsonl"
    backup = tmp_path / "backup" / f"rollout-{session_id}.jsonl"
    _write_jsonl(first, [{"message": "HTTP 429 rate limit"}])
    _write_jsonl(
        backup,
        [
            {"message": "HTTP 429 rate limit"},
            {"message": "HTTP 503 service unavailable"},
        ],
    )

    report = analyze_paths([tmp_path])

    assert report["scan"]["files_discovered"] == 2
    assert report["scan"]["files_selected"] == 1
    assert report["scan"]["duplicate_files_skipped"] == 1
    assert {category["key"] for category in report["categories"]} == {
        "upstream_rate_limit",
        "upstream_capacity",
    }


def test_bounds_oversized_lines_and_records_malformed_jsonl(tmp_path: Path):
    log_path = tmp_path / "history.jsonl"
    log_path.write_bytes(
        b'{"message":"HTTP 429 rate limit"}\n' + b"x" * 64 + b"\n" + b"{not-json}\n"
    )

    report = analyze_paths([tmp_path], max_line_bytes=40)

    assert report["scan"]["oversized_lines_skipped"] == 1
    assert report["scan"]["malformed_lines"] == 1
    assert any(group["category"] == "invalid_jsonl" for group in report["error_groups"])
    assert "JSONL 损坏" in render_markdown(report)
