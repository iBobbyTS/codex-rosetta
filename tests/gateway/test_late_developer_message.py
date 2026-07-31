"""Tests for late Codex instruction-message cache compatibility."""

from __future__ import annotations

import json
from typing import Any, cast

from codex_rosetta.auto_detect import ProviderType
from codex_rosetta.gateway.late_developer_message import (
    rewrite_late_codex_developer_messages,
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


def _wrapped(text: str) -> str:
    return f"<system>\n{text}\n</system>"


def _rewrite(body: dict[str, Any], *, enabled: bool = True):
    return rewrite_late_codex_developer_messages(
        body,
        enabled=enabled,
        source_provider="openai_responses",
        target_provider="openai_chat",
    )


def test_preserves_leading_instruction_prefix_and_rewrites_every_late_instruction():
    plugin_notice = "Capabilities from the Chrome plugin."
    fork_notice = "Fork debugging context."
    original = _body(
        {"type": "additional_tools", "role": "developer", "tools": []},
        _message("developer", "You are Codex."),
        _message("system", "System policy."),
        _message("user", "First task."),
        _message("developer", plugin_notice),
        _message("assistant", "Done."),
        _message("system", "Late system context."),
        _message("developer", fork_notice),
        _message("user", "Continue."),
    )

    rewritten, count = _rewrite(original)

    assert count == 3
    assert rewritten is not original
    assert rewritten["input"][:4] == original["input"][:4]
    assert original["input"][4]["role"] == "developer"
    assert rewritten["input"][4] == _message("user", _wrapped(plugin_notice))
    assert rewritten["input"][6] == _message("user", _wrapped("Late system context."))
    assert rewritten["input"][7] == _message("user", _wrapped(fork_notice))


def test_does_not_special_case_turn_aborted_text():
    marker = "<turn_aborted>runtime explanation</turn_aborted>"
    ordinary = "Capabilities from a plugin."
    original = _body(
        _message("developer", "You are Codex."),
        _message("user", "First task."),
        _message("developer", marker),
        _message("developer", ordinary),
    )

    rewritten, count = _rewrite(original)

    assert count == 2
    assert rewritten["input"][2] == _message("user", _wrapped(marker))
    assert rewritten["input"][3] == _message("user", _wrapped(ordinary))


def test_converted_chat_keeps_generic_system_envelope_as_separate_user_message():
    notice = "Capabilities from the Chrome plugin."
    original = _body(
        _message("developer", "You are Codex."),
        _message("user", "First task."),
        _message("developer", notice),
        _message("user", "Continue."),
    )

    rewritten, count = _rewrite(original)
    target = ConversionPipeline("openai_responses", "openai_chat").convert_request(
        rewritten
    )

    assert count == 1
    assert target["messages"] == [
        {"role": "system", "content": "You are Codex."},
        {"role": "user", "content": "First task."},
        {"role": "user", "content": _wrapped(notice)},
        {"role": "user", "content": "Continue."},
    ]


def test_non_message_history_ends_the_leading_instruction_prefix():
    original = _body(
        _message("developer", "You are Codex."),
        {"type": "reasoning", "summary": []},
        _message("developer", "Late context."),
    )

    rewritten, count = _rewrite(original)

    assert count == 1
    assert rewritten["input"][2] == _message("user", _wrapped("Late context."))


def test_preserves_string_content_shape():
    original = _body(
        _message("developer", "You are Codex."),
        _message("user", "Task."),
        {"type": "message", "role": "developer", "content": "Late context."},
    )

    rewritten, count = _rewrite(original)

    assert count == 1
    assert rewritten["input"][2] == {
        "type": "message",
        "role": "user",
        "content": _wrapped("Late context."),
    }


def test_wraps_text_across_multiple_parts_without_losing_nontext_content():
    image = {"type": "input_image", "image_url": "data:image/png;base64,AA=="}
    original = _body(
        _message("developer", "You are Codex."),
        _message("user", "Task."),
        {
            "type": "message",
            "role": "developer",
            "content": [
                {"type": "input_text", "text": "First."},
                image,
                {"type": "input_text", "text": "Second."},
            ],
        },
    )

    rewritten, count = _rewrite(original)

    assert count == 1
    assert rewritten["input"][2]["role"] == "user"
    assert rewritten["input"][2]["content"] == [
        {"type": "input_text", "text": "<system>\nFirst."},
        image,
        {"type": "input_text", "text": "Second.\n</system>"},
    ]


def test_wraps_nontext_only_content_with_text_boundary_parts():
    image = {"type": "input_image", "image_url": "data:image/png;base64,AA=="}
    original = _body(
        _message("developer", "You are Codex."),
        _message("user", "Task."),
        {"type": "message", "role": "developer", "content": [image]},
    )

    rewritten, count = _rewrite(original)

    assert count == 1
    assert rewritten["input"][2]["content"] == [
        {"type": "input_text", "text": "<system>"},
        image,
        {"type": "input_text", "text": "</system>"},
    ]


def test_rewrites_late_system_and_leaves_user_and_malformed_developer_unchanged():
    original = _body(
        _message("developer", "You are Codex."),
        _message("user", "Task."),
        _message("system", "Late system."),
        _message("user", "Continue."),
        {"type": "message", "role": "developer", "content": None},
    )

    rewritten, count = _rewrite(original)

    assert rewritten is not original
    assert count == 1
    assert rewritten["input"][2] == _message("user", _wrapped("Late system."))
    assert rewritten["input"][3:] == original["input"][3:]


def test_returns_original_body_when_developer_messages_are_only_in_prefix():
    original = _body(
        {"type": "additional_tools", "role": "developer", "tools": []},
        _message("developer", "You are Codex."),
        _message("system", "System policy."),
        _message("user", "Task."),
    )

    rewritten, count = _rewrite(original)

    assert rewritten is original
    assert count == 0


def test_requires_enabled_responses_to_chat_codex_turn_metadata():
    original = _body(
        _message("developer", "You are Codex."),
        _message("user", "Task."),
        _message("developer", "Late context."),
    )
    cases = [
        (
            original,
            {
                "enabled": False,
                "source_provider": "openai_responses",
                "target_provider": "openai_chat",
            },
        ),
        (
            original,
            {
                "enabled": True,
                "source_provider": "openai_chat",
                "target_provider": "openai_chat",
            },
        ),
        (
            original,
            {
                "enabled": True,
                "source_provider": "openai_responses",
                "target_provider": "openai_responses",
            },
        ),
        (
            {**original, "client_metadata": {}},
            {
                "enabled": True,
                "source_provider": "openai_responses",
                "target_provider": "openai_chat",
            },
        ),
        (
            {
                **original,
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
                **original,
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
        rewritten, count = rewrite_late_codex_developer_messages(
            body,
            enabled=cast(bool, options["enabled"]),
            source_provider=cast(ProviderType, options["source_provider"]),
            target_provider=cast(ProviderType, options["target_provider"]),
        )
        assert rewritten is body
        assert count == 0
