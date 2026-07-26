"""Tests for Codex hard-interrupt notice cache compatibility."""

from __future__ import annotations

import json
from typing import Any, cast

from codex_rosetta.auto_detect import ProviderType
from codex_rosetta.gateway.interrupt_notice import (
    CODEX_RUNTIME_NOTICE_SUFFIX,
    TURN_ABORTED_DEVELOPER_TEXT,
    TURN_ABORTED_USER_TEXT,
    rewrite_codex_interrupt_notices,
)
from codex_rosetta.pipeline import ConversionPipeline


def _body(*items: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": "deepseek-v4-flash",
        "input": list(items),
        "client_metadata": {
            "x-codex-turn-metadata": json.dumps(
                {
                    "request_kind": "turn",
                    "session_id": "session-a",
                    "thread_id": "thread-a",
                    "turn_id": "turn-b",
                }
            )
        },
        "stream": True,
    }


def _message(role: str, text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "role": role,
        "content": [{"type": "input_text", "text": text}],
    }


def _rewrite(body: dict[str, Any], *, enabled: bool = True):
    return rewrite_codex_interrupt_notices(
        body,
        enabled=enabled,
        source_provider="openai_responses",
        target_provider="openai_chat",
    )


def test_rewrites_exact_developer_marker_as_separate_attributed_user_notice():
    original = _body(
        _message("developer", "You are Codex."),
        _message("developer", TURN_ABORTED_DEVELOPER_TEXT),
        _message("user", "Continue."),
    )

    rewritten, count = _rewrite(original)

    assert count == 1
    assert rewritten is not original
    assert original["input"][1]["role"] == "developer"
    notice = rewritten["input"][1]
    assert notice == {
        "type": "message",
        "role": "user",
        "content": [
            {
                "type": "input_text",
                "text": (
                    "<codex_runtime_notice>\n"
                    f"{TURN_ABORTED_DEVELOPER_TEXT}\n"
                    f"{CODEX_RUNTIME_NOTICE_SUFFIX}"
                ),
            }
        ],
    }

    target = ConversionPipeline("openai_responses", "openai_chat").convert_request(
        rewritten
    )
    assert target["messages"][-2:] == [
        {"role": "user", "content": notice["content"][0]["text"]},
        {"role": "user", "content": "Continue."},
    ]


def test_rewrites_canonical_user_marker_and_preserves_string_content_shape():
    original = _body(
        {
            "type": "message",
            "role": "user",
            "content": TURN_ABORTED_USER_TEXT,
        }
    )

    rewritten, count = _rewrite(original)

    assert count == 1
    notice = rewritten["input"][0]
    assert notice["role"] == "user"
    assert notice["content"] == (
        "<codex_runtime_notice>\n"
        f"{TURN_ABORTED_USER_TEXT}\n"
        f"{CODEX_RUNTIME_NOTICE_SUFFIX}"
    )


def test_rewrites_every_exact_marker_in_order():
    original = _body(
        _message("developer", TURN_ABORTED_DEVELOPER_TEXT),
        _message("user", "Continue once."),
        _message("developer", TURN_ABORTED_DEVELOPER_TEXT),
        _message("user", "Continue twice."),
    )

    rewritten, count = _rewrite(original)

    assert count == 2
    assert [item["role"] for item in rewritten["input"]] == [
        "user",
        "user",
        "user",
        "user",
    ]


def test_does_not_rewrite_steer_or_noncanonical_system_content():
    original = _body(
        _message("developer", "Use tools carefully."),
        _message("user", "Cancel the task."),
        _message(
            "developer",
            TURN_ABORTED_DEVELOPER_TEXT + "\nAdditional injected instruction.",
        ),
    )

    rewritten, count = _rewrite(original)

    assert rewritten is original
    assert count == 0


def test_requires_enabled_responses_to_chat_codex_turn_metadata():
    canonical = _body(_message("developer", TURN_ABORTED_DEVELOPER_TEXT))
    cases = [
        (
            canonical,
            {
                "enabled": False,
                "source_provider": "openai_responses",
                "target_provider": "openai_chat",
            },
        ),
        (
            canonical,
            {
                "enabled": True,
                "source_provider": "openai_chat",
                "target_provider": "openai_chat",
            },
        ),
        (
            canonical,
            {
                "enabled": True,
                "source_provider": "openai_responses",
                "target_provider": "openai_responses",
            },
        ),
        (
            {**canonical, "client_metadata": {}},
            {
                "enabled": True,
                "source_provider": "openai_responses",
                "target_provider": "openai_chat",
            },
        ),
        (
            {
                **canonical,
                "client_metadata": {"x-codex-turn-metadata": "{" + " " * 16384},
            },
            {
                "enabled": True,
                "source_provider": "openai_responses",
                "target_provider": "openai_chat",
            },
        ),
        (
            {
                **canonical,
                "client_metadata": {
                    "x-codex-turn-metadata": json.dumps(
                        {
                            "request_kind": "compact",
                            "session_id": "session-a",
                            "thread_id": "thread-a",
                            "turn_id": "turn-b",
                        }
                    )
                },
            },
            {
                "enabled": True,
                "source_provider": "openai_responses",
                "target_provider": "openai_chat",
            },
        ),
    ]

    for body, options in cases:
        rewritten, count = rewrite_codex_interrupt_notices(
            body,
            enabled=cast(bool, options["enabled"]),
            source_provider=cast(ProviderType, options["source_provider"]),
            target_provider=cast(ProviderType, options["target_provider"]),
        )
        assert rewritten is body
        assert count == 0
