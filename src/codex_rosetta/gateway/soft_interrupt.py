"""Codex hard-interrupt stream draining and thread-owned response handoff."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from codex_rosetta.observability.persistence import SoftInterruptCapacityError

logger = logging.getLogger("codex-rosetta-gateway")

SOFT_INTERRUPT_TTL = timedelta(hours=24)
SOFT_INTERRUPT_CANCELLED_RESULT = "Client cancelled, did not execute"
_QUEUE_SIZE = 64
_MAX_ID_CHARS = 256
_TURN_ABORTED_OPEN = "<turn_aborted>"
_TURN_ABORTED_CLOSE = "</turn_aborted>"
_TURN_ABORTED_USER_GUIDANCE = (
    "The user interrupted the previous turn on purpose. Any running unified exec "
    "processes may still be running in the background. If any tools/commands were "
    "aborted, they may have partially executed."
)
_TURN_ABORTED_DEVELOPER_GUIDANCE = (
    "The previous turn was interrupted on purpose. Any running unified exec processes "
    "may still be running in the background. If any tools/commands were aborted, they "
    "may have partially executed."
)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _message_hashes(target_body: dict[str, Any]) -> list[str] | None:
    messages = target_body.get("messages")
    if not isinstance(messages, list) or not all(
        isinstance(item, dict) for item in messages
    ):
        return None
    return [_sha256(item) for item in messages]


def _request_shape_sha256(body: dict[str, Any]) -> str:
    return _sha256(
        {
            key: value
            for key, value in body.items()
            if key not in {"input", "client_metadata", "stream"}
        }
    )


def _input_items(body: dict[str, Any]) -> list[Any] | None:
    value = body.get("input")
    return value if isinstance(value, list) else None


def _item_texts(value: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(value, str):
        texts.append(value)
    elif isinstance(value, list):
        for item in value:
            texts.extend(_item_texts(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"text", "content"}:
                texts.extend(_item_texts(item))
    return texts


def _is_turn_aborted_item(item: Any) -> bool:
    if not isinstance(item, dict) or item.get("type") != "message":
        return False
    role = item.get("role")
    if role not in {"user", "developer"}:
        return False
    text = "\n".join(_item_texts(item.get("content"))).strip()
    if not text.startswith(_TURN_ABORTED_OPEN) or not text.endswith(
        _TURN_ABORTED_CLOSE
    ):
        return False
    guidance = text.removeprefix(_TURN_ABORTED_OPEN).removesuffix(_TURN_ABORTED_CLOSE)
    expected = (
        _TURN_ABORTED_USER_GUIDANCE
        if role == "user"
        else _TURN_ABORTED_DEVELOPER_GUIDANCE
    )
    return guidance.strip() == expected


def _turn_aborted_index(items: list[Any], start: int) -> int | None:
    for index in range(start, len(items)):
        if _is_turn_aborted_item(items[index]):
            return index
    return None


def _valid_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized and len(normalized) <= _MAX_ID_CHARS else None


@dataclass(frozen=True, slots=True)
class CodexTurnMetadata:
    """Bounded identity fields from Codex's canonical turn metadata."""

    session_id: str
    thread_id: str
    turn_id: str
    window_id: str | None
    forked_from_thread_id: str | None


def parse_codex_turn_metadata(body: dict[str, Any]) -> CodexTurnMetadata | None:
    """Parse a normal Codex turn without accepting loose identity fallbacks."""

    client_metadata = body.get("client_metadata")
    if not isinstance(client_metadata, dict):
        return None
    raw = client_metadata.get("x-codex-turn-metadata")
    if not isinstance(raw, str) or len(raw) > 16 * 1024:
        return None
    try:
        value = json.loads(raw)
    except TypeError, ValueError:
        return None
    if not isinstance(value, dict) or value.get("request_kind") != "turn":
        return None
    session_id = _valid_id(value.get("session_id"))
    thread_id = _valid_id(value.get("thread_id"))
    turn_id = _valid_id(value.get("turn_id"))
    if session_id is None or thread_id is None or turn_id is None:
        return None
    window_id = _valid_id(value.get("window_id"))
    forked_from = _valid_id(value.get("forked_from_thread_id"))
    return CodexTurnMetadata(
        session_id=session_id,
        thread_id=thread_id,
        turn_id=turn_id,
        window_id=window_id,
        forked_from_thread_id=forked_from,
    )


@dataclass(slots=True)
class SoftInterruptReplay:
    """A validated persisted candidate awaiting target-prefix confirmation."""

    principal_id: str
    metadata: CodexTurnMetadata
    original_body: dict[str, Any]
    replay_body: dict[str, Any]
    target_message_hashes: list[str]
    replayed_items: int
    payload_bytes: int


@dataclass(slots=True)
class SoftInterruptPreparation:
    """Request-local soft-interrupt metadata and optional replay candidate."""

    metadata: CodexTurnMetadata | None
    body: dict[str, Any]
    replay: SoftInterruptReplay | None = None
    profile: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SoftInterruptCapture:
    """Structured source events and request fingerprints for one upstream stream."""

    principal_id: str
    metadata: CodexTurnMetadata
    provider_name: str
    model: str
    prompt_cache_key: str
    source_input: list[Any]
    request_shape_sha256: str
    target_message_hashes: list[str]
    entry_id: str | None
    request_log: Any | None
    output_items: list[dict[str, Any]] = field(default_factory=list)
    completed: bool = False
    terminal_failure: str | None = None
    detached: asyncio.Event = field(default_factory=asyncio.Event)

    def observe(self, event: dict[str, Any]) -> None:
        """Capture completed source items and a successful terminal event."""

        event_type = event.get("type")
        if event_type == "response.output_item.done":
            item = event.get("item")
            if isinstance(item, dict):
                self.output_items.append(copy.deepcopy(item))
        elif event_type == "response.completed":
            self.completed = True
        elif event_type in {"response.failed", "response.incomplete"}:
            self.completed = False
            self.terminal_failure = event_type

    def update_profile(self, values: dict[str, Any]) -> None:
        if self.request_log is None or self.entry_id is None:
            return
        try:
            self.request_log.update_profile(self.entry_id, values)
        except Exception:
            logger.debug("Failed to update soft-interrupt profile", exc_info=True)


@dataclass(frozen=True, slots=True)
class _StreamError:
    error: BaseException


_END = object()


class SoftInterruptStream:
    """Client-facing iterator backed by an independently draining pump."""

    def __init__(
        self,
        coordinator: SoftInterruptCoordinator,
        source: AsyncIterator[bytes | str],
        capture: SoftInterruptCapture,
    ) -> None:
        self._coordinator = coordinator
        self._source = source
        self.capture = capture
        self._queue: asyncio.Queue[bytes | str | _StreamError | object] = asyncio.Queue(
            maxsize=_QUEUE_SIZE
        )
        self._pump_done = asyncio.Event()
        self._persist_lock = asyncio.Lock()
        self._persisted = False
        self._released = False
        self._drain_callbacks: list[Callable[[], None]] = []
        self._task = asyncio.create_task(self._pump())

    def __aiter__(self) -> SoftInterruptStream:
        return self

    async def __anext__(self) -> bytes | str:
        item = await self._queue.get()
        if item is _END:
            await self._release()
            raise StopAsyncIteration
        if isinstance(item, _StreamError):
            await self._release()
            raise item.error
        assert isinstance(item, (bytes, str))
        return item

    async def aclose(self) -> None:
        """Detach the downstream without cancelling the upstream pump."""

        await self.detach()

    async def detach(self) -> None:
        if self.capture.detached.is_set():
            return
        self.capture.detached.set()
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.capture.update_profile({"soft_interrupt_detached": True})
        if self._pump_done.is_set():
            await self._persist_if_ready()
            await self._release()

    async def detach_and_wait(self) -> None:
        await self.detach()
        await self._task

    def add_drain_callback(self, callback: Callable[[], None]) -> None:
        """Run request-local cleanup after the independently owned pump ends."""

        if self._pump_done.is_set():
            callback()
            return
        self._drain_callbacks.append(callback)

    async def cancel(self) -> None:
        self.capture.detached.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        await self._release()

    async def _offer(self, item: bytes | str | _StreamError | object) -> None:
        if self.capture.detached.is_set():
            return
        put_task = asyncio.create_task(self._queue.put(item))
        detached_task = asyncio.create_task(self.capture.detached.wait())
        done, pending = await asyncio.wait(
            {put_task, detached_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if detached_task in done and self.capture.detached.is_set():
            put_task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _pump(self) -> None:
        try:
            async for chunk in self._source:
                await self._offer(chunk)
        except asyncio.CancelledError:
            if self.capture.detached.is_set():
                self.capture.update_profile(
                    {"soft_interrupt_drain_outcome": "cancelled"}
                )
            raise
        except BaseException as exc:
            if self.capture.detached.is_set():
                self.capture.update_profile(
                    {
                        "soft_interrupt_drain_outcome": (
                            "timeout" if isinstance(exc, TimeoutError) else "error"
                        )
                    }
                )
            await self._offer(_StreamError(exc))
        else:
            if self.capture.detached.is_set() and not self.capture.completed:
                self.capture.update_profile(
                    {
                        "soft_interrupt_drain_outcome": (
                            self.capture.terminal_failure or "incomplete"
                        )
                    }
                )
            await self._offer(_END)
        finally:
            self._pump_done.set()
            if self.capture.detached.is_set():
                await self._persist_if_ready()
                await self._release()
            callbacks, self._drain_callbacks = self._drain_callbacks, []
            for callback in callbacks:
                try:
                    callback()
                except Exception:
                    logger.debug(
                        "Failed to run soft-interrupt drain callback", exc_info=True
                    )

    async def _persist_if_ready(self) -> None:
        async with self._persist_lock:
            if self._persisted or not self.capture.completed:
                return
            self._persisted = True
            if not self.capture.output_items:
                self.capture.update_profile(
                    {"soft_interrupt_drain_outcome": "completed_no_output"}
                )
                return
            await self._coordinator._persist_capture(self.capture)

    async def _release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._coordinator._release(self)


class SoftInterruptCoordinator:
    """Own active drain tasks and durable replay for exact Codex threads."""

    def __init__(self, persistence: Any | None) -> None:
        self._persistence = persistence
        self._active: dict[tuple[str, str], SoftInterruptStream] = {}
        self._lock = asyncio.Lock()

    async def prepare_request(
        self,
        *,
        principal_id: str,
        provider_name: str,
        model: str,
        body: dict[str, Any],
    ) -> SoftInterruptPreparation:
        """Wait for an interrupted predecessor and prepare a one-shot replay."""

        metadata = parse_codex_turn_metadata(body)
        profile: dict[str, Any] = {
            "soft_interrupt_enabled": True,
            "soft_interrupt_metadata_valid": metadata is not None,
        }
        if metadata is None or self._persistence is None:
            profile["soft_interrupt_skip_reason"] = "invalid_metadata"
            return SoftInterruptPreparation(metadata, body, profile=profile)
        input_items = _input_items(body)
        prompt_cache_key = body.get("prompt_cache_key")
        if input_items is None or not isinstance(prompt_cache_key, str):
            profile["soft_interrupt_skip_reason"] = "invalid_request_shape"
            return SoftInterruptPreparation(metadata, body, profile=profile)

        aborted_index = _turn_aborted_index(input_items, 0)
        key = (principal_id, metadata.thread_id)
        active: SoftInterruptStream | None
        async with self._lock:
            active = self._active.get(key)
        if (
            active is not None
            and active.capture.metadata.turn_id != metadata.turn_id
            and aborted_index is not None
        ):
            started = time.monotonic()
            await active.detach_and_wait()
            profile["soft_interrupt_wait_ms"] = round(
                (time.monotonic() - started) * 1000, 2
            )
        elif active is not None:
            await active.cancel()
            profile["soft_interrupt_skip_reason"] = "active_not_hard_interrupt"

        now = datetime.now(timezone.utc).isoformat()
        record = self._persistence.get_soft_interrupt_handoff(
            principal_id=principal_id,
            thread_id=metadata.thread_id,
            now=now,
        )
        if record is None:
            profile.setdefault("soft_interrupt_skip_reason", "no_handoff")
            return SoftInterruptPreparation(metadata, body, profile=profile)
        if aborted_index is None or record["turn_id"] == metadata.turn_id:
            self._persistence.delete_soft_interrupt_handoff(
                principal_id=principal_id, thread_id=metadata.thread_id
            )
            profile["soft_interrupt_skip_reason"] = "not_hard_interrupt"
            return SoftInterruptPreparation(metadata, body, profile=profile)

        expected_count = int(record["source_input_count"])
        if (
            record["provider_name"] != provider_name
            or record["model"] != model
            or record["prompt_cache_key"] != prompt_cache_key
            or record["request_shape_sha256"] != _request_shape_sha256(body)
            or len(input_items) < expected_count
            or _sha256(input_items[:expected_count]) != record["source_input_sha256"]
        ):
            self._persistence.delete_soft_interrupt_handoff(
                principal_id=principal_id, thread_id=metadata.thread_id
            )
            profile["soft_interrupt_skip_reason"] = "identity_or_prefix_mismatch"
            return SoftInterruptPreparation(metadata, body, profile=profile)

        abort_index = _turn_aborted_index(input_items, expected_count)
        output_items = record.get("output_items")
        if abort_index is None or not isinstance(output_items, list):
            self._persistence.delete_soft_interrupt_handoff(
                principal_id=principal_id, thread_id=metadata.thread_id
            )
            profile["soft_interrupt_skip_reason"] = "missing_abort_boundary"
            return SoftInterruptPreparation(metadata, body, profile=profile)
        observed = input_items[expected_count:abort_index]
        if len(observed) > len(output_items) or any(
            _sha256(observed[index]) != _sha256(output_items[index])
            for index in range(len(observed))
        ):
            self._persistence.delete_soft_interrupt_handoff(
                principal_id=principal_id, thread_id=metadata.thread_id
            )
            profile["soft_interrupt_skip_reason"] = "observed_suffix_mismatch"
            return SoftInterruptPreparation(metadata, body, profile=profile)

        missing = copy.deepcopy(output_items[len(observed) :])
        result_ids = {
            item.get("call_id")
            for item in input_items
            if isinstance(item, dict)
            and item.get("type") in {"function_call_output", "custom_tool_call_output"}
            and isinstance(item.get("call_id"), str)
        }
        synthetic: list[dict[str, Any]] = []
        for item in output_items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            call_id = item.get("call_id")
            if (
                item_type not in {"function_call", "custom_tool_call"}
                or not isinstance(call_id, str)
                or call_id in result_ids
            ):
                continue
            synthetic.append(
                {
                    "type": f"{item_type}_output",
                    "call_id": call_id,
                    "output": SOFT_INTERRUPT_CANCELLED_RESULT,
                }
            )
            result_ids.add(call_id)

        replay_body = copy.deepcopy(body)
        # Keep the marker for local validation, but do not forward this Codex
        # control item upstream.  A hard-interrupt continuation should have the
        # same provider-visible shape as a steer: replay the missing output and
        # send the user's continuation as the next input without a synthetic
        # cancellation message that would invalidate the cached prefix.
        replay_body["input"] = [
            *input_items[:abort_index],
            *missing,
            *synthetic,
            *input_items[abort_index + 1 :],
        ]
        replay = SoftInterruptReplay(
            principal_id=principal_id,
            metadata=metadata,
            original_body=body,
            replay_body=replay_body,
            target_message_hashes=list(record["target_message_hashes"]),
            replayed_items=len(missing) + len(synthetic),
            payload_bytes=int(record["payload_bytes"]),
        )
        profile["soft_interrupt_replayed_items"] = replay.replayed_items
        profile["soft_interrupt_payload_bytes"] = replay.payload_bytes
        profile["soft_interrupt_replay_mode"] = "steer_continuation"
        profile["soft_interrupt_aborted_marker_removed"] = True
        return SoftInterruptPreparation(metadata, replay_body, replay, profile)

    def target_prefix_matches(
        self, replay: SoftInterruptReplay, target_body: dict[str, Any]
    ) -> bool:
        """Require the prior upstream Chat messages as an exact prefix."""

        hashes = _message_hashes(target_body)
        expected = replay.target_message_hashes
        return hashes is not None and hashes[: len(expected)] == expected

    async def finish_replay(
        self, replay: SoftInterruptReplay, *, accepted: bool
    ) -> None:
        """Consume a replay candidate after target-prefix validation."""

        if self._persistence is None:
            return
        self._persistence.delete_soft_interrupt_handoff(
            principal_id=replay.principal_id,
            thread_id=replay.metadata.thread_id,
        )
        if not accepted:
            logger.warning(
                "Soft-interrupt target prefix mismatch for thread %s",
                replay.metadata.thread_id,
            )

    def create_capture(
        self,
        *,
        preparation: SoftInterruptPreparation,
        principal_id: str,
        provider_name: str,
        model: str,
        source_body: dict[str, Any],
        target_body: dict[str, Any],
        entry_id: str | None,
        request_log: Any | None,
    ) -> SoftInterruptCapture | None:
        """Create a capture only for fully fingerprintable Codex Chat traffic."""

        metadata = preparation.metadata
        source_input = _input_items(source_body)
        prompt_cache_key = source_body.get("prompt_cache_key")
        target_hashes = _message_hashes(target_body)
        if (
            metadata is None
            or source_input is None
            or not isinstance(prompt_cache_key, str)
            or target_hashes is None
        ):
            return None
        return SoftInterruptCapture(
            principal_id=principal_id,
            metadata=metadata,
            provider_name=provider_name,
            model=model,
            prompt_cache_key=prompt_cache_key,
            source_input=copy.deepcopy(source_input),
            request_shape_sha256=_request_shape_sha256(source_body),
            target_message_hashes=target_hashes,
            entry_id=entry_id,
            request_log=request_log,
        )

    async def wrap(
        self,
        source: AsyncIterator[bytes | str],
        capture: SoftInterruptCapture,
    ) -> SoftInterruptStream:
        """Register and start one independently draining stream."""

        stream = SoftInterruptStream(self, source, capture)
        key = (capture.principal_id, capture.metadata.thread_id)
        conflict = False
        async with self._lock:
            existing = self._active.get(key)
            if existing is not None:
                conflict = True
            else:
                self._active[key] = stream
        if conflict:
            await stream.cancel()
            raise RuntimeError("soft-interrupt thread already has an active stream")
        return stream

    async def _persist_capture(self, capture: SoftInterruptCapture) -> None:
        if self._persistence is None:
            return
        now = datetime.now(timezone.utc)
        try:
            payload_bytes = self._persistence.store_soft_interrupt_handoff(
                principal_id=capture.principal_id,
                thread_id=capture.metadata.thread_id,
                session_id=capture.metadata.session_id,
                turn_id=capture.metadata.turn_id,
                window_id=capture.metadata.window_id,
                forked_from_thread_id=capture.metadata.forked_from_thread_id,
                provider_name=capture.provider_name,
                model=capture.model,
                prompt_cache_key=capture.prompt_cache_key,
                source_input_count=len(capture.source_input),
                source_input_sha256=_sha256(capture.source_input),
                target_message_hashes=capture.target_message_hashes,
                request_shape_sha256=capture.request_shape_sha256,
                output_items=capture.output_items,
                created_at=now.isoformat(),
                expires_at=(now + SOFT_INTERRUPT_TTL).isoformat(),
            )
        except SoftInterruptCapacityError:
            capture.update_profile(
                {
                    "soft_interrupt_drain_outcome": "capacity_skipped",
                    "soft_interrupt_skip_reason": "capacity",
                }
            )
            return
        except Exception:
            logger.exception("Failed to persist soft-interrupt handoff")
            capture.update_profile(
                {"soft_interrupt_drain_outcome": "persistence_failed"}
            )
            return
        capture.update_profile(
            {
                "soft_interrupt_drain_outcome": "completed",
                "soft_interrupt_payload_bytes": payload_bytes,
            }
        )

    async def _release(self, stream: SoftInterruptStream) -> None:
        key = (stream.capture.principal_id, stream.capture.metadata.thread_id)
        async with self._lock:
            if self._active.get(key) is stream:
                self._active.pop(key, None)

    async def close(self) -> None:
        """Cancel and await every app-owned upstream pump before DB shutdown."""

        async with self._lock:
            streams = list(self._active.values())
        for stream in streams:
            await stream.cancel()
