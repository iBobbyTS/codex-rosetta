"""Content-addressed replay helpers for model-facing Chat tool history.

This module owns only request-object identity and reconstruction. Persistence,
encryption, quotas, and TTLs live in ``observability.tool_history_store``.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast


class ToolHistoryObjectKind(StrEnum):
    """Kinds of independently cached Chat history objects."""

    CALL = "call"
    RESULT = "result"


@dataclass(frozen=True)
class ToolHistoryObject:
    """One ID-independent object and its stable location in Chat history."""

    kind: ToolHistoryObjectKind
    message_index: int
    tool_call_index: int | None
    protocol_id: str
    source_template: dict[str, Any]


@dataclass(frozen=True)
class ToolHistoryTranslationCandidate:
    """One source/target template pair eligible for durable persistence."""

    kind: ToolHistoryObjectKind
    source_template: dict[str, Any]
    target_template: dict[str, Any]


@dataclass(frozen=True)
class ToolHistorySnapshot:
    """Locations and source templates captured before history adaptation."""

    objects: tuple[ToolHistoryObject, ...]

    @classmethod
    def capture(cls, body: dict[str, Any]) -> ToolHistorySnapshot:
        """Capture ordered assistant calls and tool results from a Chat body."""
        objects: list[ToolHistoryObject] = []
        messages = body.get("messages")
        if not isinstance(messages, list):
            return cls(objects=())
        for message_index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            message = cast(dict[str, Any], message)
            objects.extend(_capture_message_objects(message_index, message))
        return cls(objects=tuple(objects))

    def apply(
        self,
        body: dict[str, Any],
        target_templates: list[dict[str, Any] | None],
    ) -> dict[str, Any]:
        """Apply ordered cache hits while injecting each current protocol ID."""
        if len(target_templates) != len(self.objects):
            raise ValueError("tool-history translation count does not match snapshot")
        if not any(target is not None for target in target_templates):
            return body
        adapted = copy.deepcopy(body)
        for item, target_template in zip(
            self.objects,
            target_templates,
            strict=True,
        ):
            if target_template is None:
                continue
            replacement = inject_tool_history_object_id(
                item.kind,
                target_template,
                item.protocol_id,
            )
            _replace_snapshot_object(adapted, item, replacement)
        return adapted

    def collect_miss_candidates(
        self,
        adapted_body: dict[str, Any],
        *,
        hit_indexes: set[int],
    ) -> list[ToolHistoryTranslationCandidate]:
        """Collect translated call misses and every independently missed result."""
        candidates: list[ToolHistoryTranslationCandidate] = []
        for index, item in enumerate(self.objects):
            if index in hit_indexes:
                continue
            target = _snapshot_object(adapted_body, item)
            if not isinstance(target, dict):
                continue
            target_template = tool_history_object_template(item.kind, target)
            if (
                item.kind is ToolHistoryObjectKind.CALL
                and target_template == item.source_template
            ):
                continue
            candidates.append(
                ToolHistoryTranslationCandidate(
                    kind=item.kind,
                    source_template=item.source_template,
                    target_template=target_template,
                )
            )
        return candidates


def tool_history_object_template(
    kind: ToolHistoryObjectKind | str,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deep copy with only the protocol's top-level ID removed."""
    normalized_kind = ToolHistoryObjectKind(kind)
    id_field = "id" if normalized_kind is ToolHistoryObjectKind.CALL else "tool_call_id"
    return copy.deepcopy({key: item for key, item in value.items() if key != id_field})


def canonical_tool_history_template(value: dict[str, Any]) -> bytes:
    """Serialize one exact object template for keyed content addressing."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def inject_tool_history_object_id(
    kind: ToolHistoryObjectKind | str,
    template: dict[str, Any],
    protocol_id: str,
) -> dict[str, Any]:
    """Rebuild a cached template with the current request's protocol ID."""
    normalized_kind = ToolHistoryObjectKind(kind)
    if normalized_kind is ToolHistoryObjectKind.CALL:
        return {"id": protocol_id, **copy.deepcopy(template)}
    rebuilt: dict[str, Any] = {}
    inserted = False
    for key, value in template.items():
        rebuilt[key] = copy.deepcopy(value)
        if key == "role":
            rebuilt["tool_call_id"] = protocol_id
            inserted = True
    if not inserted:
        rebuilt = {"tool_call_id": protocol_id, **rebuilt}
    return rebuilt


def _capture_message_objects(
    message_index: int,
    message: dict[str, Any],
) -> list[ToolHistoryObject]:
    role = message.get("role")
    if role == "assistant":
        return _capture_assistant_calls(message_index, message.get("tool_calls"))
    if role != "tool":
        return []
    call_id = message.get("tool_call_id")
    if not isinstance(call_id, str) or not call_id:
        return []
    return [
        ToolHistoryObject(
            kind=ToolHistoryObjectKind.RESULT,
            message_index=message_index,
            tool_call_index=None,
            protocol_id=call_id,
            source_template=tool_history_object_template(
                ToolHistoryObjectKind.RESULT,
                message,
            ),
        )
    ]


def _capture_assistant_calls(
    message_index: int,
    value: Any,
) -> list[ToolHistoryObject]:
    if not isinstance(value, list):
        return []
    calls: list[ToolHistoryObject] = []
    for tool_call_index, tool_call in enumerate(value):
        if not isinstance(tool_call, dict):
            continue
        tool_call = cast(dict[str, Any], tool_call)
        call_id = tool_call.get("id")
        if not isinstance(call_id, str) or not call_id:
            continue
        calls.append(
            ToolHistoryObject(
                kind=ToolHistoryObjectKind.CALL,
                message_index=message_index,
                tool_call_index=tool_call_index,
                protocol_id=call_id,
                source_template=tool_history_object_template(
                    ToolHistoryObjectKind.CALL,
                    tool_call,
                ),
            )
        )
    return calls


def _snapshot_object(body: dict[str, Any], item: ToolHistoryObject) -> Any:
    messages = body.get("messages")
    if not isinstance(messages, list) or item.message_index >= len(messages):
        return None
    message = messages[item.message_index]
    if item.kind is ToolHistoryObjectKind.RESULT:
        return message
    if not isinstance(message, dict):
        return None
    tool_calls = message.get("tool_calls")
    if (
        not isinstance(tool_calls, list)
        or item.tool_call_index is None
        or item.tool_call_index >= len(tool_calls)
    ):
        return None
    return tool_calls[item.tool_call_index]


def _replace_snapshot_object(
    body: dict[str, Any],
    item: ToolHistoryObject,
    replacement: dict[str, Any],
) -> None:
    messages = body.get("messages")
    if not isinstance(messages, list) or item.message_index >= len(messages):
        raise ValueError("tool-history message location changed during replay")
    if item.kind is ToolHistoryObjectKind.RESULT:
        messages[item.message_index] = replacement
        return
    message = messages[item.message_index]
    if not isinstance(message, dict):
        raise ValueError("tool-history assistant message changed during replay")
    tool_calls = message.get("tool_calls")
    if (
        not isinstance(tool_calls, list)
        or item.tool_call_index is None
        or item.tool_call_index >= len(tool_calls)
    ):
        raise ValueError("tool-history call location changed during replay")
    tool_calls[item.tool_call_index] = replacement
