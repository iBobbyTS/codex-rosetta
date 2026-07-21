"""Bounded provider-schema checks for credentials hidden in JSON strings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codex_rosetta.auto_detect import ProviderType
from codex_rosetta.converters.openai_responses._constants import (
    RESPONSES_EMBEDDED_JSON_FIELDS,
    ResponsesEventType,
)
from codex_rosetta.observability.redaction import (
    JsonObjectMembers,
    SecretCollisionError,
    SecretRedactor,
)

_RESPONSES_TYPES = {"openai_responses", "open_responses"}


def _values(value: Any, name: str) -> tuple[Any, ...]:
    if isinstance(value, dict):
        return (value[name],) if name in value else ()
    if isinstance(value, JsonObjectMembers):
        return tuple(item for key, item in value.members if key == name)
    return ()


def _only(value: Any, name: str) -> Any:
    values = _values(value, name)
    return values[-1] if values else None


def _items(value: Any, name: str) -> tuple[Any, ...]:
    result: list[Any] = []
    for item in _values(value, name):
        if isinstance(item, list):
            result.extend(item)
    return tuple(result)


@dataclass
class _ArgumentBuffer:
    text: str = ""
    byte_count: int = 0
    fragment_count: int = 0


class ProviderCredentialSemanticGate:
    """Inspect only provider fields whose consumers decode embedded JSON.

    Argument fragments are retained per call with hard live-state bounds. Unknown
    strings are never parsed as JSON.
    """

    def __init__(
        self,
        redactor: SecretRedactor,
        target_provider: ProviderType | None,
        *,
        max_argument_bytes: int = 1_048_576,
        max_argument_fragments: int = 4096,
        max_argument_identities: int = 4096,
    ) -> None:
        self._redactor = redactor
        self._target_provider = target_provider
        self._max_argument_bytes = max_argument_bytes
        self._max_argument_fragments = max_argument_fragments
        self._max_argument_identities = max_argument_identities
        self._buffers: dict[tuple[Any, ...], _ArgumentBuffer] = {}
        self._responses_item_to_call: dict[str, str] = {}
        self._chat_tool_order: list[str] = []
        self._live_bytes = 0
        self._live_fragments = 0

    def inspect_document(self, value: Any) -> None:
        """Inspect known non-streaming response argument fields."""
        if self._target_provider in _RESPONSES_TYPES:
            self._inspect_responses_document(value)
        elif self._target_provider == "openai_chat":
            self._inspect_chat_document(value)

    def inspect_stream_event(self, event: Any) -> None:
        """Inspect one parsed stream event before its frame is released."""
        if self._target_provider in _RESPONSES_TYPES:
            self._inspect_responses_event(event)
        elif self._target_provider == "openai_chat":
            self._inspect_chat_event(event)

    def _inspect_argument(self, value: Any) -> None:
        if isinstance(value, str) and self._redactor.contains_json_semantic(value):
            raise SecretCollisionError

    def _inspect_tool_item(self, item: Any) -> None:
        for item_type in _values(item, "type"):
            field_names = RESPONSES_EMBEDDED_JSON_FIELDS.get(item_type, ())
            for field_name in field_names:
                for field_value in _values(item, field_name):
                    self._inspect_argument(field_value)

    def _inspect_responses_document(self, value: Any) -> None:
        for item in _items(value, "output"):
            self._inspect_tool_item(item)
        for response in _values(value, "response"):
            for item in _items(response, "output"):
                self._inspect_tool_item(item)

    def _inspect_chat_document(self, value: Any) -> None:
        for choice in _items(value, "choices"):
            for container_name in ("message", "delta"):
                for container in _values(choice, container_name):
                    for tool_call in _items(container, "tool_calls"):
                        for function in _values(tool_call, "function"):
                            for arguments in _values(function, "arguments"):
                                self._inspect_argument(arguments)

    def _append(self, key: tuple[Any, ...], fragment: str) -> None:
        encoded_len = len(fragment.encode("utf-8"))
        buffer = self._buffers.setdefault(key, _ArgumentBuffer())
        if (
            self._live_bytes + encoded_len > self._max_argument_bytes
            or self._live_fragments + 1 > self._max_argument_fragments
        ):
            self._clear_all()
            raise SecretCollisionError
        buffer.text += fragment
        buffer.byte_count += encoded_len
        buffer.fragment_count += 1
        self._live_bytes += encoded_len
        self._live_fragments += 1
        # Function arguments are JSON objects. Parse only once a fragment can
        # complete that schema value; raw token bytes are checked on every append.
        stripped = buffer.text.strip()
        if self._redactor.contains_wire_bytes(buffer.text.encode("utf-8")) or (
            stripped.startswith("{")
            and stripped.endswith("}")
            and self._redactor.contains_json_semantic(stripped)
        ):
            self._clear_all()
            raise SecretCollisionError

    def _clear(self, key: tuple[Any, ...]) -> None:
        buffer = self._buffers.pop(key, None)
        if buffer is not None:
            self._live_bytes -= buffer.byte_count
            self._live_fragments -= buffer.fragment_count

    def _clear_all(self) -> None:
        self._buffers.clear()
        self._responses_item_to_call.clear()
        self._chat_tool_order.clear()
        self._live_bytes = 0
        self._live_fragments = 0

    def finish(self) -> None:
        """Release all bounded identity and fragment state at stream end."""
        self._clear_all()

    def _identity_count(self) -> int:
        return len(self._responses_item_to_call) + len(self._chat_tool_order)

    def _reserve_identity(self) -> None:
        if self._identity_count() >= self._max_argument_identities:
            self._clear_all()
            raise SecretCollisionError

    def _register_responses_item(self, item: Any) -> None:
        if _only(item, "type") not in {"function_call", "custom_tool_call"}:
            return
        item_id = _only(item, "id")
        call_id = _only(item, "call_id")
        if not isinstance(item_id, str) or not isinstance(call_id, str):
            return
        if not item_id or not call_id:
            return
        if item_id not in self._responses_item_to_call:
            self._reserve_identity()
        self._responses_item_to_call[item_id] = call_id

    def _responses_call_id(self, event: Any) -> str | None:
        call_id = _only(event, "call_id")
        if isinstance(call_id, str) and call_id:
            return call_id
        item_id = _only(event, "item_id")
        if isinstance(item_id, str) and item_id:
            return self._responses_item_to_call.get(item_id)
        return None

    @staticmethod
    def _responses_key(call_id: str) -> tuple[Any, ...]:
        return ("responses", "call_id", call_id)

    def _clear_responses_call(self, call_id: str | None) -> None:
        if call_id is None:
            return
        self._clear(self._responses_key(call_id))
        for item_id, mapped_call_id in tuple(self._responses_item_to_call.items()):
            if mapped_call_id == call_id:
                del self._responses_item_to_call[item_id]

    def _inspect_responses_event(self, event: Any) -> None:
        event_types = _values(event, "type")
        event_type = event_types[-1] if event_types else None
        if event_type in {
            ResponsesEventType.FUNCTION_CALL_ARGS_DELTA,
            ResponsesEventType.CUSTOM_TOOL_CALL_INPUT_DELTA,
        }:
            deltas = _values(event, "delta")
            call_id = self._responses_call_id(event)
            if deltas and isinstance(deltas[-1], str) and call_id is not None:
                self._append(self._responses_key(call_id), deltas[-1])
            return
        if event_type in {
            ResponsesEventType.FUNCTION_CALL_ARGS_DONE,
            ResponsesEventType.CUSTOM_TOOL_CALL_INPUT_DONE,
        }:
            field_name = (
                "input"
                if event_type == ResponsesEventType.CUSTOM_TOOL_CALL_INPUT_DONE
                else "arguments"
            )
            for field_value in _values(event, field_name):
                self._inspect_argument(field_value)
            self._clear_responses_call(self._responses_call_id(event))
            return
        if event_type in {
            ResponsesEventType.OUTPUT_ITEM_ADDED,
            ResponsesEventType.OUTPUT_ITEM_DONE,
        }:
            for item in _values(event, "item"):
                self._inspect_tool_item(item)
                if event_type.endswith(".added"):
                    self._register_responses_item(item)
            if event_type.endswith(".done"):
                item = _only(event, "item")
                call_id = _only(item, "call_id")
                if not isinstance(call_id, str) or not call_id:
                    item_id = _only(item, "id")
                    call_id = self._responses_item_to_call.get(item_id)
                self._clear_responses_call(call_id)
            return
        if event_type == ResponsesEventType.RESPONSE_COMPLETED:
            self._inspect_responses_document(event)
            self._clear_all()

    def _chat_call_id(self, tool_call: Any) -> str | None:
        call_id = _only(tool_call, "id")
        if isinstance(call_id, str) and call_id:
            if call_id not in self._chat_tool_order:
                self._reserve_identity()
                self._chat_tool_order.append(call_id)
            return call_id
        tool_index = _only(tool_call, "index")
        if isinstance(tool_index, int) and 0 <= tool_index < len(self._chat_tool_order):
            return self._chat_tool_order[tool_index]
        return None

    def _inspect_chat_event(self, event: Any) -> None:
        for choice in _items(event, "choices"):
            for delta in _values(choice, "delta"):
                for tool_call in _items(delta, "tool_calls"):
                    call_id = self._chat_call_id(tool_call)
                    for function in _values(tool_call, "function"):
                        arguments = _values(function, "arguments")
                        if (
                            arguments
                            and isinstance(arguments[-1], str)
                            and call_id is not None
                        ):
                            self._append(("chat", "call_id", call_id), arguments[-1])
