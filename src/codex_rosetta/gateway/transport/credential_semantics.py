"""Bounded provider-schema checks for credentials hidden in JSON strings."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    StreamingSecretDetector,
)

_RESPONSES_TYPES = {"openai_responses", "open_responses"}

# Keep this inventory explicit: these provider text consumers concatenate
# deltas by wire identity, while unknown Responses strings remain opaque.
_RESPONSES_TEXT_DELTA_FIELDS: dict[
    str,
    tuple[str, tuple[str, ...], tuple[str, ...]],
] = {
    "response.refusal.delta": (
        "refusal",
        ("item_id", "output_index", "content_index"),
        (),
    ),
    "response.code_interpreter_call_code.delta": (
        "code_interpreter_code",
        ("item_id", "output_index"),
        (),
    ),
}

# Codex binds these deltas to its current output item after discarding all other
# wire metadata. Only the listed event-specific indices survive parsing.
_CODEX_RESPONSES_TEXT_DELTA_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    ResponsesEventType.OUTPUT_TEXT_DELTA: ("text", ()),
    ResponsesEventType.REASONING_SUMMARY_TEXT_DELTA: (
        "reasoning_summary",
        ("summary_index",),
    ),
    "response.reasoning_text.delta": ("reasoning_text", ("content_index",)),
}
_CODEX_RESPONSES_TEXT_FIELDS = frozenset(
    field_name for field_name, _ in _CODEX_RESPONSES_TEXT_DELTA_FIELDS.values()
)


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
    started: bool = False
    in_string: bool = False
    escaped: bool = False
    stack: list[str] = field(default_factory=list)
    scalar: bool = False
    complete: bool = False

    def feed(self, fragment: str) -> bool:
        """Track whether one top-level JSON value closes in this fragment."""
        completed_now = False
        for character in fragment:
            if self.complete:
                continue
            if not self.started:
                self._start(character)
                continue
            if self.scalar:
                if character.isspace():
                    self.complete = True
                    completed_now = True
                continue
            if self.in_string:
                completed_now |= self._feed_string(character)
                continue
            completed_now |= self._feed_structure(character)
        return completed_now

    def _start(self, character: str) -> None:
        if character.isspace():
            return
        self.started = True
        if character == '"':
            self.in_string = True
        elif character in "{[":
            self.stack.append(character)
        else:
            self.scalar = True

    def _feed_string(self, character: str) -> bool:
        if self.escaped:
            self.escaped = False
        elif character == "\\":
            self.escaped = True
        elif character == '"':
            self.in_string = False
            if not self.stack:
                self.complete = True
                return True
        return False

    def _feed_structure(self, character: str) -> bool:
        if character == '"':
            self.in_string = True
            return False
        if character in "{[":
            self.stack.append(character)
            return False
        if character not in "}]":
            return False
        expected = "{" if character == "}" else "["
        if not self.stack or self.stack[-1] != expected:
            return False
        self.stack.pop()
        if self.stack:
            return False
        self.complete = True
        return True


class ProviderResponseContractError(ValueError):
    """Raised when consumer-visible provider response semantics are invalid."""


class ProviderCredentialSemanticGate:
    """Inspect provider fields using bounded consumer-specific stream state.

    Ordinary text uses rolling overlap windows. Only documented embedded JSON
    arguments retain complete values while their top-level value is unfinished.
    """

    def __init__(
        self,
        redactor: SecretRedactor,
        target_provider: ProviderType | None,
        *,
        max_argument_bytes: int = 1_048_576,
        max_argument_identities: int = 4096,
        max_text_windows: int = 4096,
    ) -> None:
        self._redactor = redactor
        self._target_provider = target_provider
        self._max_argument_bytes = max_argument_bytes
        self._max_argument_identities = max_argument_identities
        self._max_text_windows = max_text_windows
        self._buffers: dict[tuple[Any, ...], _ArgumentBuffer] = {}
        self._argument_detectors: dict[tuple[Any, ...], StreamingSecretDetector] = {}
        self._completed_arguments: set[tuple[Any, ...]] = set()
        self._text_windows: dict[tuple[Any, ...], StreamingSecretDetector] = {}
        self._responses_item_to_call: dict[str, str] = {}
        self._responses_mcp_item_to_index: dict[str, int] = {}
        self._responses_mcp_index_to_item: dict[int, str] = {}
        self._responses_text_identities: set[tuple[Any, ...]] = set()
        self._responses_text_identity_modes: dict[tuple[Any, ...], tuple[str, ...]] = {}
        self._responses_active_item_generation = 0
        self._chat_index_to_call: dict[int, str] = {}
        self._chat_call_to_index: dict[str, int] = {}
        self._chat_call_ids: set[str] = set()
        self._chat_choice_call_ids: dict[int, set[str]] = {}
        self._live_bytes = 0

    def inspect_document(self, value: Any) -> None:
        """Inspect one complete response using the provider consumer semantics."""
        self._clear_all()
        try:
            if self._target_provider in _RESPONSES_TYPES:
                self._inspect_responses_document(value)
            elif self._target_provider == "openai_chat":
                self._inspect_chat_document(value)
        finally:
            self._clear_all()

    def inspect_stream_event(self, event: Any) -> None:
        """Inspect one parsed stream event before its frame is released."""
        if self._target_provider in _RESPONSES_TYPES:
            self._inspect_responses_event(event)
        elif self._target_provider == "openai_chat":
            self._inspect_chat_event(event)
        elif self._target_provider == "anthropic":
            self._inspect_anthropic_event(event)
        elif self._target_provider == "google":
            self._inspect_google_event(event)

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
        self._inspect_responses_output_items(_items(value, "output"))
        for response in _values(value, "response"):
            self._inspect_responses_output_items(_items(response, "output"))

    def _inspect_responses_output_items(self, items: tuple[Any, ...]) -> None:
        for item in items:
            self._inspect_tool_item(item)
            if _only(item, "type") != "message":
                continue
            for part in _items(item, "content"):
                if _only(part, "type") != "output_text":
                    continue
                self._append_text(
                    ("responses", "document", "output_text"),
                    _only(part, "text"),
                )

    def _inspect_chat_document(self, value: Any) -> None:
        for choice in _items(value, "choices"):
            for container_name in ("message", "delta"):
                for container in _values(choice, container_name):
                    for tool_call in _items(container, "tool_calls"):
                        for function in _values(tool_call, "function"):
                            for arguments in _values(function, "arguments"):
                                self._inspect_argument(arguments)

    def _append(self, key: tuple[Any, ...], fragment: str) -> None:
        if key in self._completed_arguments:
            if fragment.strip():
                self._clear_all()
                raise ProviderResponseContractError(
                    "semantic argument data followed a complete JSON value"
                )
            return
        encoded_len = len(fragment.encode("utf-8"))
        buffer = self._buffers.get(key)
        if buffer is None:
            if (
                len(self._buffers) + len(self._completed_arguments)
                >= self._max_argument_identities
            ):
                self._clear_all()
                raise ProviderResponseContractError(
                    "semantic argument identity inspection capacity exceeded"
                )
            buffer = _ArgumentBuffer()
            self._buffers[key] = buffer
            self._argument_detectors[key] = self._redactor.streaming_wire_detector()
        if self._live_bytes + encoded_len > self._max_argument_bytes:
            self._clear_all()
            raise ProviderResponseContractError(
                "semantic argument inspection capacity exceeded"
            )
        detector = self._argument_detectors[key]
        if detector.feed(fragment.encode("utf-8")):
            self._clear_all()
            raise SecretCollisionError
        buffer.text += fragment
        buffer.byte_count += encoded_len
        self._live_bytes += encoded_len
        if buffer.feed(fragment):
            try:
                self._inspect_argument(buffer.text)
            except SecretCollisionError:
                self._clear_all()
                raise
            self._clear(key)
            self._completed_arguments.add(key)

    def _clear(self, key: tuple[Any, ...]) -> None:
        buffer = self._buffers.pop(key, None)
        if buffer is not None:
            self._live_bytes -= buffer.byte_count
        argument_detector = self._argument_detectors.pop(key, None)
        if argument_detector is not None:
            argument_detector.finish()
        text_window = self._text_windows.pop(key, None)
        if text_window is not None:
            text_window.finish()

    def _append_text(self, key: tuple[Any, ...], fragment: Any) -> None:
        if not isinstance(fragment, str) or not fragment:
            return
        detector = self._text_windows.get(key)
        if detector is None:
            if len(self._text_windows) >= self._max_text_windows:
                self._clear_all()
                raise ProviderResponseContractError(
                    "semantic text-window inspection capacity exceeded"
                )
            detector = self._redactor.streaming_value_detector()
            self._text_windows[key] = detector
        if detector.feed(fragment.encode("utf-8")):
            self._clear_all()
            raise SecretCollisionError

    def _finish_argument(self, key: tuple[Any, ...], *values: Any) -> None:
        try:
            for value in values:
                self._inspect_argument(value)
            buffer = self._buffers.get(key)
            if buffer is not None:
                self._inspect_argument(buffer.text)
        except SecretCollisionError:
            self._clear_all()
            raise
        self._clear(key)
        self._completed_arguments.discard(key)

    def _clear_all(self) -> None:
        for detector in self._argument_detectors.values():
            detector.finish()
        for detector in self._text_windows.values():
            detector.finish()
        self._buffers.clear()
        self._argument_detectors.clear()
        self._completed_arguments.clear()
        self._text_windows.clear()
        self._responses_item_to_call.clear()
        self._responses_mcp_item_to_index.clear()
        self._responses_mcp_index_to_item.clear()
        self._responses_text_identities.clear()
        self._responses_text_identity_modes.clear()
        self._responses_active_item_generation = 0
        self._chat_index_to_call.clear()
        self._chat_call_to_index.clear()
        self._chat_call_ids.clear()
        self._chat_choice_call_ids.clear()
        self._live_bytes = 0

    def finish(self) -> None:
        """Release all bounded identity, window, and argument state."""
        self._clear_all()

    def _identity_count(self) -> int:
        return (
            len(self._responses_item_to_call)
            + len(self._responses_mcp_item_to_index)
            + len(self._responses_text_identities)
            + len(self._chat_call_ids)
        )

    def _reserve_identity(self) -> None:
        if self._identity_count() >= self._max_argument_identities:
            self._clear_all()
            raise ProviderResponseContractError(
                "semantic identity inspection capacity exceeded"
            )

    @staticmethod
    def _mcp_identity(item_id: Any, output_index: Any) -> tuple[str, int] | None:
        if (
            isinstance(item_id, str)
            and item_id
            and isinstance(output_index, int)
            and not isinstance(output_index, bool)
            and output_index >= 0
        ):
            return item_id, output_index
        return None

    def _track_mcp_identity(
        self,
        identity: tuple[str, int],
        *,
        reserve: bool,
    ) -> tuple[str, int]:
        item_id, output_index = identity
        mapped_index = self._responses_mcp_item_to_index.get(item_id)
        mapped_item_id = self._responses_mcp_index_to_item.get(output_index)
        if (mapped_index is not None and mapped_index != output_index) or (
            mapped_item_id is not None and mapped_item_id != item_id
        ):
            self._clear_all()
            raise ProviderResponseContractError("conflicting MCP stream identity")
        if mapped_index is None and mapped_item_id is None and reserve:
            self._reserve_identity()
            self._responses_mcp_item_to_index[item_id] = output_index
            self._responses_mcp_index_to_item[output_index] = item_id
        return identity

    def _responses_mcp_identity(
        self,
        event: Any,
        *,
        reserve: bool = True,
    ) -> tuple[str, int]:
        identity = self._mcp_identity(
            _only(event, "item_id"),
            _only(event, "output_index"),
        )
        if identity is None:
            self._clear_all()
            raise ProviderResponseContractError(
                "missing or invalid MCP stream identity"
            )
        return self._track_mcp_identity(identity, reserve=reserve)

    @staticmethod
    def _responses_mcp_key(identity: tuple[str, int]) -> tuple[Any, ...]:
        return ("responses", "mcp", *identity)

    def _clear_responses_mcp(self, identity: tuple[str, int]) -> None:
        item_id, output_index = identity
        self._finish_argument(self._responses_mcp_key(identity))
        if self._responses_mcp_item_to_index.get(item_id) == output_index:
            del self._responses_mcp_item_to_index[item_id]
        if self._responses_mcp_index_to_item.get(output_index) == item_id:
            del self._responses_mcp_index_to_item[output_index]

    def _register_responses_item(
        self,
        item: Any,
        *,
        output_index: Any = None,
    ) -> None:
        item_type = _only(item, "type")
        if item_type == "mcp_call":
            identity = self._mcp_identity(_only(item, "id"), output_index)
            if identity is not None:
                self._track_mcp_identity(identity, reserve=True)
            return
        if item_type not in {"function_call", "custom_tool_call"}:
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
        self._finish_argument(self._responses_key(call_id))
        for item_id, mapped_call_id in tuple(self._responses_item_to_call.items()):
            if mapped_call_id == call_id:
                del self._responses_item_to_call[item_id]

    def _responses_text_identity_values(
        self,
        event: Any,
        field_names: tuple[str, ...],
    ) -> tuple[tuple[str, Any], ...]:
        values: list[tuple[str, Any]] = []
        for field_name in field_names:
            value = _only(event, field_name)
            valid = (
                isinstance(value, str) and bool(value)
                if field_name == "item_id"
                else isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            )
            if not valid:
                self._clear_all()
                raise ProviderResponseContractError(
                    f"missing or invalid {field_name} stream identity"
                )
            values.append((field_name, value))
        return tuple(values)

    def _responses_text_identity(
        self,
        event: Any,
        required_fields: tuple[str, ...],
        optional_fields: tuple[str, ...],
    ) -> tuple[
        tuple[tuple[str, Any], ...],
        tuple[tuple[str, Any], ...],
        tuple[str, ...],
    ]:
        required_identity = self._responses_text_identity_values(
            event,
            required_fields,
        )
        present_optional_fields = tuple(
            name for name in optional_fields if _values(event, name)
        )
        optional_identity = (
            self._responses_text_identity_values(event, present_optional_fields)
            if present_optional_fields
            else ()
        )
        return (
            optional_identity + required_identity,
            required_identity,
            present_optional_fields,
        )

    def _track_responses_text_identity(
        self,
        field_name: str,
        identity: tuple[tuple[str, Any], ...],
        required_identity: tuple[tuple[str, Any], ...],
        *,
        optional_identity_shape: tuple[str, ...],
    ) -> None:
        mode_key = (field_name, required_identity)
        existing_mode = self._responses_text_identity_modes.get(mode_key)
        if existing_mode is not None and existing_mode != optional_identity_shape:
            self._clear_all()
            raise ProviderResponseContractError("inconsistent optional stream identity")

        identity_key = (field_name, identity)
        if identity_key not in self._responses_text_identities:
            self._reserve_identity()
            self._responses_text_identities.add(identity_key)
        self._responses_text_identity_modes[mode_key] = optional_identity_shape

    def _inspect_responses_text_delta(
        self,
        event: Any,
        field_name: str,
        required_identity_fields: tuple[str, ...],
        optional_identity_fields: tuple[str, ...],
    ) -> None:
        deltas = _values(event, "delta")
        if not deltas or not isinstance(deltas[-1], str):
            return
        identity, required_identity, optional_identity_shape = (
            self._responses_text_identity(
                event,
                required_identity_fields,
                optional_identity_fields,
            )
        )
        if not deltas[-1]:
            return
        if optional_identity_fields:
            self._track_responses_text_identity(
                field_name,
                identity,
                required_identity,
                optional_identity_shape=optional_identity_shape,
            )
        self._append_text(
            ("responses", field_name, identity),
            deltas[-1],
        )

    def _inspect_codex_responses_text_delta(
        self,
        event: Any,
        field_name: str,
        retained_identity_fields: tuple[str, ...],
    ) -> None:
        deltas = _values(event, "delta")
        if not deltas or not isinstance(deltas[-1], str):
            return
        retained_identity = self._responses_text_identity_values(
            event,
            retained_identity_fields,
        )
        if not deltas[-1]:
            return
        identity = (
            ("active_item", self._responses_active_item_generation),
            *retained_identity,
        )
        self._track_responses_text_identity(
            field_name,
            identity,
            identity,
            optional_identity_shape=(),
        )
        self._append_text(("responses", field_name, identity), deltas[-1])

    def _advance_responses_active_item(self) -> None:
        for identity_key in tuple(self._responses_text_identities):
            field_name, identity = identity_key
            if field_name not in _CODEX_RESPONSES_TEXT_FIELDS:
                continue
            self._clear(("responses", field_name, identity))
            self._responses_text_identities.remove(identity_key)
        for mode_key in tuple(self._responses_text_identity_modes):
            if mode_key[0] in _CODEX_RESPONSES_TEXT_FIELDS:
                del self._responses_text_identity_modes[mode_key]
        self._responses_active_item_generation += 1

    def _inspect_responses_mcp_event(self, event: Any, event_type: Any) -> None:
        if event_type == ResponsesEventType.MCP_CALL_ARGS_DELTA:
            identity = self._responses_mcp_identity(event)
            deltas = _values(event, "delta")
            if deltas and isinstance(deltas[-1], str):
                self._append(self._responses_mcp_key(identity), deltas[-1])
            return
        identity = self._responses_mcp_identity(event, reserve=False)
        for field_value in _values(event, "arguments"):
            self._inspect_argument(field_value)
        self._clear_responses_mcp(identity)

    def _inspect_responses_output_item_event(self, event: Any, event_type: Any) -> None:
        self._advance_responses_active_item()
        for item in _values(event, "item"):
            self._inspect_tool_item(item)
            if event_type.endswith(".added"):
                self._register_responses_item(
                    item,
                    output_index=_only(event, "output_index"),
                )
        if not event_type.endswith(".done"):
            return
        item = _only(event, "item")
        if _only(item, "type") == "mcp_call":
            item_id = _only(item, "id")
            output_index = self._responses_mcp_item_to_index.get(item_id)
            if output_index is not None:
                self._clear_responses_mcp((item_id, output_index))
            return
        call_id = _only(item, "call_id")
        if not isinstance(call_id, str) or not call_id:
            item_id = _only(item, "id")
            call_id = self._responses_item_to_call.get(item_id)
        self._clear_responses_call(call_id)

    def _inspect_responses_event(self, event: Any) -> None:
        event_types = _values(event, "type")
        event_type = event_types[-1] if event_types else None
        codex_text_spec = _CODEX_RESPONSES_TEXT_DELTA_FIELDS.get(event_type)
        if codex_text_spec is not None:
            self._inspect_codex_responses_text_delta(event, *codex_text_spec)
            return
        text_spec = _RESPONSES_TEXT_DELTA_FIELDS.get(event_type)
        if text_spec is not None:
            self._inspect_responses_text_delta(event, *text_spec)
            return
        if event_type in {
            ResponsesEventType.MCP_CALL_ARGS_DELTA,
            ResponsesEventType.MCP_CALL_ARGS_DONE,
        }:
            self._inspect_responses_mcp_event(event, event_type)
            return
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
            self._inspect_responses_output_item_event(event, event_type)
            return
        if event_type == ResponsesEventType.RESPONSE_COMPLETED:
            self.inspect_document(event)

    def _chat_call_id(self, tool_call: Any, choice_index: int) -> str:
        call_id = _only(tool_call, "id")
        tool_index = _only(tool_call, "index")
        has_index = (
            isinstance(tool_index, int)
            and not isinstance(tool_index, bool)
            and tool_index >= 0
        )

        if isinstance(call_id, str) and call_id:
            if call_id not in self._chat_call_ids:
                self._reserve_identity()
                self._chat_call_ids.add(call_id)
            self._chat_choice_call_ids.setdefault(choice_index, set()).add(call_id)
            if has_index:
                mapped_call_id = self._chat_index_to_call.get(tool_index)
                if mapped_call_id is not None and mapped_call_id != call_id:
                    self._clear_all()
                    raise ProviderResponseContractError(
                        "conflicting Chat tool-call identity"
                    )
                mapped_index = self._chat_call_to_index.get(call_id)
                if mapped_index is not None and mapped_index != tool_index:
                    self._clear_all()
                    raise ProviderResponseContractError(
                        "conflicting Chat tool-call identity"
                    )
                self._chat_index_to_call[tool_index] = call_id
                self._chat_call_to_index[call_id] = tool_index
            return call_id
        if has_index:
            mapped_call_id = self._chat_index_to_call.get(tool_index)
            if mapped_call_id is not None:
                self._chat_choice_call_ids.setdefault(choice_index, set()).add(
                    mapped_call_id
                )
                return mapped_call_id
        self._clear_all()
        raise ProviderResponseContractError("missing Chat tool-call identity")

    def _clear_chat_choice(self, choice_index: int) -> None:
        for field_name in ("content", "reasoning_content", "refusal"):
            self._clear(("chat", field_name, ("choice_index", choice_index)))
        for call_id in self._chat_choice_call_ids.pop(choice_index, set()):
            self._finish_argument(("chat", "call_id", call_id))
            self._chat_call_ids.discard(call_id)
            tool_index = self._chat_call_to_index.pop(call_id, None)
            if (
                tool_index is not None
                and self._chat_index_to_call.get(tool_index) == call_id
            ):
                del self._chat_index_to_call[tool_index]

    @staticmethod
    def _chat_choice_index(choice: Any) -> int:
        value = _only(choice, "index")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return 0

    def _inspect_chat_delta(self, delta: Any, choice_index: int) -> None:
        for field_name in ("content", "reasoning_content", "refusal"):
            values = _values(delta, field_name)
            if values and isinstance(values[-1], str):
                self._append_text(
                    ("chat", field_name, ("choice_index", choice_index)),
                    values[-1],
                )
        for tool_call in _items(delta, "tool_calls"):
            call_id = self._chat_call_id(tool_call, choice_index)
            for function in _values(tool_call, "function"):
                arguments = _values(function, "arguments")
                if arguments and isinstance(arguments[-1], str):
                    self._append(("chat", "call_id", call_id), arguments[-1])

    def _inspect_chat_event(self, event: Any) -> None:
        for choice in _items(event, "choices"):
            choice_index = self._chat_choice_index(choice)
            for delta in _values(choice, "delta"):
                self._inspect_chat_delta(delta, choice_index)
            if _only(choice, "finish_reason") is not None:
                self._clear_chat_choice(choice_index)

    def _inspect_anthropic_event(self, event: Any) -> None:
        event_type = _only(event, "type")
        block_index = _only(event, "index") or 0
        if event_type == "content_block_stop":
            self._finish_argument(
                ("anthropic", "partial_json", ("block_index", block_index))
            )
            for field_name in ("text", "thinking", "signature"):
                self._clear(("anthropic", field_name, ("block_index", block_index)))
            return
        if event_type == "message_stop":
            self._clear_all()
            return
        if event_type != "content_block_delta":
            return
        delta = _only(event, "delta")
        delta_type = _only(delta, "type")
        field_names = {
            "text_delta": "text",
            "thinking_delta": "thinking",
            "signature_delta": "signature",
            "input_json_delta": "partial_json",
        }
        field_name = field_names.get(delta_type)
        if field_name is None:
            return
        values = _values(delta, field_name)
        if values and isinstance(values[-1], str):
            key = (
                "anthropic",
                field_name,
                ("block_index", block_index),
            )
            if delta_type == "input_json_delta":
                self._append(key, values[-1])
            else:
                self._append_text(key, values[-1])

    def _inspect_google_event(self, event: Any) -> None:
        for candidate in _items(event, "candidates"):
            choice_index = _only(candidate, "index") or 0
            content = _only(candidate, "content")
            for part_index, part in enumerate(_items(content, "parts")):
                values = _values(part, "text")
                if not values or not isinstance(values[-1], str):
                    continue
                field_name = "reasoning" if _only(part, "thought") else "text"
                self._append_text(
                    (
                        "google",
                        field_name,
                        ("choice_index", choice_index),
                        ("part_index", part_index),
                    ),
                    values[-1],
                )
            if _only(candidate, "finishReason") is not None:
                for key in tuple(self._text_windows):
                    if (
                        len(key) >= 3
                        and key[0] == "google"
                        and (
                            "choice_index",
                            choice_index,
                        )
                        in key
                    ):
                        self._clear(key)
