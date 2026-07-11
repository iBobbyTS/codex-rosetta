"""Gateway-local phase buffering for Responses streams."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from codex_rosetta.converters.openai_responses._constants import ResponsesEventType

COMMENTARY_PHASE = "commentary"
FINAL_ANSWER_PHASE = "final_answer"
DEFAULT_MAX_BUFFERED_EVENTS = 256
DEFAULT_MAX_BUFFERED_BYTES = 1024 * 1024

_MESSAGE_EVENT_TYPES = {
    ResponsesEventType.CONTENT_PART_ADDED,
    ResponsesEventType.CONTENT_PART_DONE,
    ResponsesEventType.OUTPUT_TEXT_DELTA,
    ResponsesEventType.OUTPUT_TEXT_DONE,
}
_TOOL_ITEM_TYPES = {
    "function_call",
    "custom_tool_call",
    "mcp_call",
    "shell_call",
    "computer_call",
    "tool_search_call",
    "web_search_call",
    "image_generation_call",
}
_TOOL_EVENT_TYPES = {
    ResponsesEventType.FUNCTION_CALL_ARGS_DELTA,
    ResponsesEventType.FUNCTION_CALL_ARGS_DONE,
    ResponsesEventType.CUSTOM_TOOL_CALL_INPUT_DELTA,
    ResponsesEventType.CUSTOM_TOOL_CALL_INPUT_DONE,
}
_TERMINAL_EVENT_TYPES = {
    ResponsesEventType.RESPONSE_COMPLETED,
    ResponsesEventType.RESPONSE_FAILED,
    ResponsesEventType.RESPONSE_DONE,
}


class ResponsesPhaseBuffer:
    """Delay Responses message text until final/tool status is known.

    This is intentionally a gateway-layer adapter rather than converter logic:
    it exists to make Chat-upstream work text fold as Responses commentary for
    Codex-like clients without changing provider-neutral IR semantics.
    """

    def __init__(
        self,
        *,
        window_id: str,
        max_buffered_events: int = DEFAULT_MAX_BUFFERED_EVENTS,
        max_buffered_bytes: int = DEFAULT_MAX_BUFFERED_BYTES,
    ) -> None:
        self.window_id = window_id
        self._max_buffered_events = max_buffered_events
        self._max_buffered_bytes = max_buffered_bytes
        self._buffer: list[dict[str, Any]] = []
        self._buffered_bytes = 0
        self._message_item_ids: set[str] = set()
        self._commentary = False
        self._terminal_seen = False
        self._passthrough = False

    def process(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        """Process one Responses event and return events ready to send."""
        if self._passthrough:
            return [event]

        if self._terminal_seen:
            return [self._annotate_if_needed(event)]

        if self._has_tool_signal(event):
            self._commentary = True
            emitted = self._flush_buffer(phase=COMMENTARY_PHASE)
            emitted.append(self._annotate_if_needed(event))
            if event.get("type") in _TERMINAL_EVENT_TYPES:
                self._terminal_seen = True
            return emitted

        event_type = event.get("type")
        if event_type in _TERMINAL_EVENT_TYPES:
            self._terminal_seen = True
            phase = (
                COMMENTARY_PHASE
                if self._commentary
                else _final_buffer_phase_for_terminal(event_type)
            )
            emitted = self._flush_buffer(phase=phase)
            emitted.append(_with_message_phase(event, phase) if phase else event)
            return emitted

        if self._should_buffer(event):
            event_size = _serialized_size(event)
            if (
                len(self._buffer) >= self._max_buffered_events
                or self._buffered_bytes + event_size > self._max_buffered_bytes
            ):
                # Phase inference is optional compatibility metadata.  If a
                # provider emits an unusually large pre-tool message, preserve
                # streaming and memory safety by releasing the prefix unchanged
                # and disabling inference for the remainder of this response.
                self._passthrough = True
                emitted = self._flush_buffer(phase=None)
                emitted.append(event)
                return emitted
            self._remember_message_item(event)
            self._buffer.append(event)
            self._buffered_bytes += event_size
            return []

        return [self._annotate_if_needed(event)]

    def flush(self) -> list[dict[str, Any]]:
        """Release buffered events after a normal EOF without a terminal event."""
        return self._flush_buffer(phase=None)

    def _flush_buffer(self, *, phase: str | None) -> list[dict[str, Any]]:
        if not self._buffer:
            return []

        buffered = self._buffer
        self._buffer = []
        self._buffered_bytes = 0
        if phase is None:
            return list(buffered)
        return [_with_message_phase(event, phase) for event in buffered]

    def _should_buffer(self, event: dict[str, Any]) -> bool:
        if self._commentary:
            return False

        event_type = event.get("type")
        if event_type in _MESSAGE_EVENT_TYPES:
            item_id = event.get("item_id")
            return not item_id or item_id in self._message_item_ids

        if event_type in (
            ResponsesEventType.OUTPUT_ITEM_ADDED,
            ResponsesEventType.OUTPUT_ITEM_DONE,
        ):
            return _item_type(event) == "message"

        return False

    def _remember_message_item(self, event: dict[str, Any]) -> None:
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "message":
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id:
                self._message_item_ids.add(item_id)

    def _annotate_if_needed(self, event: dict[str, Any]) -> dict[str, Any]:
        if not self._commentary:
            return event
        return _with_message_phase(event, COMMENTARY_PHASE)

    def _has_tool_signal(self, event: dict[str, Any]) -> bool:
        event_type = event.get("type")
        if event_type in _TOOL_EVENT_TYPES:
            return True

        if event_type in (
            ResponsesEventType.OUTPUT_ITEM_ADDED,
            ResponsesEventType.OUTPUT_ITEM_DONE,
        ):
            return _item_type(event) in _TOOL_ITEM_TYPES

        if event_type == ResponsesEventType.RESPONSE_COMPLETED:
            return _completed_has_tool_output(event)

        return False


def _item_type(event: dict[str, Any]) -> str | None:
    item = event.get("item")
    if not isinstance(item, dict):
        return None
    item_type = item.get("type")
    return item_type if isinstance(item_type, str) else None


def _serialized_size(event: dict[str, Any]) -> int:
    """Return the UTF-8 JSON size used for buffer accounting."""
    return len(
        json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _completed_has_tool_output(event: dict[str, Any]) -> bool:
    response = event.get("response")
    if not isinstance(response, dict):
        return False
    output = response.get("output")
    if not isinstance(output, list):
        return False
    return any(
        isinstance(item, dict) and item.get("type") in _TOOL_ITEM_TYPES
        for item in output
    )


def _final_buffer_phase_for_terminal(event_type: str | None) -> str | None:
    if event_type == ResponsesEventType.RESPONSE_COMPLETED:
        return FINAL_ANSWER_PHASE
    return None


def _with_message_phase(event: dict[str, Any], phase: str) -> dict[str, Any]:
    event_type = event.get("type")
    if event_type in (
        ResponsesEventType.OUTPUT_ITEM_ADDED,
        ResponsesEventType.OUTPUT_ITEM_DONE,
    ):
        if _item_type(event) != "message":
            return event
        annotated = deepcopy(event)
        item = annotated.get("item")
        if isinstance(item, dict):
            item["phase"] = phase
        return annotated

    if event_type == ResponsesEventType.RESPONSE_COMPLETED:
        return _annotate_completed_messages(event, phase=phase)

    return event


def _annotate_completed_messages(
    event: dict[str, Any], *, phase: str
) -> dict[str, Any]:
    response = event.get("response")
    if not isinstance(response, dict):
        return event
    output = response.get("output")
    if not isinstance(output, list):
        return event
    if not any(
        isinstance(item, dict) and item.get("type") == "message" for item in output
    ):
        return event

    annotated = deepcopy(event)
    annotated_response = annotated.get("response")
    if not isinstance(annotated_response, dict):
        return annotated
    annotated_output = annotated_response.get("output")
    if not isinstance(annotated_output, list):
        return annotated
    for item in annotated_output:
        if isinstance(item, dict) and item.get("type") == "message":
            item["phase"] = phase
    return annotated
