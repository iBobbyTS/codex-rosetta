"""Late Codex instruction-message conversion for Chat-provider cache stability."""

from __future__ import annotations

import copy
import json
from typing import Any

from codex_rosetta.auto_detect import ProviderType

_CODEX_METADATA_MAX_ID_CHARS = 512
_SYSTEM_OPEN = "<system>"
_SYSTEM_CLOSE = "</system>"


def _has_valid_codex_turn_metadata(body: dict[str, Any]) -> bool:
    metadata = body.get("client_metadata")
    if not isinstance(metadata, dict):
        return False
    raw = metadata.get("x-codex-turn-metadata")
    if not isinstance(raw, str) or len(raw) > 16 * 1024:
        return False
    try:
        decoded = json.loads(raw)
    except TypeError, ValueError:
        return False
    if not isinstance(decoded, dict) or decoded.get("request_kind") != "turn":
        return False
    for field in ("session_id", "thread_id", "turn_id"):
        value = decoded.get(field)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > _CODEX_METADATA_MAX_ID_CHARS
        ):
            return False
    return True


def _wrapped_content(content: Any) -> str | list[Any] | None:
    if isinstance(content, str):
        return f"{_SYSTEM_OPEN}\n{content}\n{_SYSTEM_CLOSE}"
    if not isinstance(content, list):
        return None

    wrapped = copy.deepcopy(content)
    text_indexes = [
        index
        for index, part in enumerate(wrapped)
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    if not text_indexes:
        return [
            {"type": "input_text", "text": _SYSTEM_OPEN},
            *wrapped,
            {"type": "input_text", "text": _SYSTEM_CLOSE},
        ]

    first = text_indexes[0]
    last = text_indexes[-1]
    wrapped[first]["text"] = f"{_SYSTEM_OPEN}\n{wrapped[first]['text']}"
    wrapped[last]["text"] = f"{wrapped[last]['text']}\n{_SYSTEM_CLOSE}"
    return wrapped


def _rewrite_item(item: Any) -> tuple[Any, bool]:
    if (
        not isinstance(item, dict)
        or item.get("type") != "message"
        or item.get("role") not in {"system", "developer"}
    ):
        return item, False

    content = _wrapped_content(item.get("content"))
    if content is None:
        return item, False
    rewritten = item.copy()
    rewritten["role"] = "user"
    rewritten["content"] = content
    return rewritten, True


def rewrite_late_codex_developer_messages(
    body: dict[str, Any],
    *,
    enabled: bool,
    source_provider: ProviderType,
    target_provider: ProviderType,
) -> tuple[dict[str, Any], int]:
    """Rewrite Codex instruction messages after the leading instruction prefix.

    The leading contiguous system/developer message prefix remains authoritative.
    Once ordinary conversation history begins, later system/developer messages
    become separate user messages whose original content is enclosed by
    ``<system>...</system>``. This is a request-local role conversion and does
    not inspect the message text.

    Args:
        body: Parsed inbound request body.
        enabled: Effective Provider compatibility setting.
        source_provider: Inbound protocol selected by the route.
        target_provider: Upstream protocol selected by the route.

    Returns:
        The original body and zero when no item matches, otherwise a copy with
        every valid late instruction message rewritten and the rewritten count.
    """
    if (
        not enabled
        or source_provider not in {"openai_responses", "open_responses"}
        or target_provider != "openai_chat"
        or not _has_valid_codex_turn_metadata(body)
    ):
        return body, 0
    items = body.get("input")
    if not isinstance(items, list):
        return body, 0

    leading_instructions = True
    rewritten_items: list[Any] = []
    count = 0
    for item in items:
        if leading_instructions:
            if isinstance(item, dict) and item.get("type") == "additional_tools":
                rewritten_items.append(item)
                continue
            if (
                isinstance(item, dict)
                and item.get("type") == "message"
                and item.get("role") in {"system", "developer"}
            ):
                rewritten_items.append(item)
                continue
            leading_instructions = False

        rewritten, changed = _rewrite_item(item)
        rewritten_items.append(rewritten)
        count += int(changed)
    if count == 0:
        return body, 0

    rewritten_body = body.copy()
    rewritten_body["input"] = rewritten_items
    return rewritten_body, count
