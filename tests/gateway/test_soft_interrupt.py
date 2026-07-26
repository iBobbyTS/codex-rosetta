"""Tests for Codex hard-interrupt draining and thread-owned replay."""

import asyncio
import json

from codex_rosetta.gateway.soft_interrupt import (
    SOFT_INTERRUPT_CANCELLED_RESULT,
    SoftInterruptCoordinator,
    parse_codex_turn_metadata,
)
from codex_rosetta.observability.persistence import PersistenceManager


def _body(
    *,
    thread: str = "thread-a",
    turn: str = "turn-a",
    session: str = "session-a",
    input_items: list[dict] | None = None,
    forked_from: str | None = None,
) -> dict:
    metadata = {
        "request_kind": "turn",
        "session_id": session,
        "thread_id": thread,
        "turn_id": turn,
        "window_id": "window-a",
    }
    if forked_from is not None:
        metadata["forked_from_thread_id"] = forked_from
    return {
        "model": "deepseek-chat",
        "stream": True,
        "prompt_cache_key": "cache-a",
        "input": input_items
        if input_items is not None
        else [{"type": "message", "role": "user", "content": "hello"}],
        "client_metadata": {
            "x-codex-turn-metadata": json.dumps(metadata, separators=(",", ":"))
        },
    }


def _abort_item() -> dict:
    return {
        "type": "message",
        "role": "user",
        "content": [
            {
                "type": "input_text",
                "text": (
                    "<turn_aborted>\n"
                    "The user interrupted the previous turn on purpose. Any running "
                    "unified exec processes may still be running in the background. "
                    "If any tools/commands were aborted, they may have partially "
                    "executed.\n</turn_aborted>"
                ),
            }
        ],
    }


def _target() -> dict:
    return {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "hello"}],
    }


def _done(item: dict) -> dict:
    return {"type": "response.output_item.done", "item": item}


async def _capture_stream(
    coordinator: SoftInterruptCoordinator,
    pm: PersistenceManager,
    *,
    items: list[dict],
    complete: bool = True,
    detach: bool = True,
) -> None:
    body = _body()
    preparation = await coordinator.prepare_request(
        principal_id="client-a",
        provider_name="deepseek",
        model="deepseek-chat",
        body=body,
    )
    capture = coordinator.create_capture(
        preparation=preparation,
        principal_id="client-a",
        provider_name="deepseek",
        model="deepseek-chat",
        source_body=body,
        target_body=_target(),
        entry_id=None,
        request_log=None,
    )
    assert capture is not None

    async def source():
        for item in items:
            capture.observe(_done(item))
            yield b"data"
        if complete:
            capture.observe({"type": "response.completed"})
            yield b"done"

    stream = await coordinator.wrap(source(), capture)
    if detach:
        await stream.detach_and_wait()
    else:
        assert [chunk async for chunk in stream]
    assert pm.count_soft_interrupt_handoffs() == (1 if detach and complete else 0)


def test_metadata_requires_canonical_turn_identity():
    valid = parse_codex_turn_metadata(_body())
    assert valid is not None
    assert (valid.session_id, valid.thread_id, valid.turn_id) == (
        "session-a",
        "thread-a",
        "turn-a",
    )
    body = _body()
    body["client_metadata"]["x-codex-turn-metadata"] = json.dumps(
        {"request_kind": "steer", "session_id": "s", "thread_id": "t", "turn_id": "x"}
    )
    assert parse_codex_turn_metadata(body) is None


def test_normal_completion_and_incomplete_detach_do_not_persist(tmp_path):
    async def scenario():
        pm = PersistenceManager(str(tmp_path))
        coordinator = SoftInterruptCoordinator(pm)
        item = {"type": "message", "role": "assistant", "content": "visible"}
        await _capture_stream(coordinator, pm, items=[item], detach=False)
        await _capture_stream(coordinator, pm, items=[item], complete=False)
        await coordinator.close()
        pm.close()

    asyncio.run(scenario())


def test_detached_completed_stream_persists_and_replays_missing_suffix(tmp_path):
    async def scenario():
        pm = PersistenceManager(str(tmp_path))
        coordinator = SoftInterruptCoordinator(pm)
        reasoning = {"type": "reasoning", "id": "r1", "summary": []}
        function_call = {
            "type": "function_call",
            "id": "fc1",
            "call_id": "call-1",
            "name": "exec",
            "arguments": "{}",
        }
        custom_call = {
            "type": "custom_tool_call",
            "id": "cc1",
            "call_id": "call-2",
            "name": "exec",
            "input": "pwd",
        }
        await _capture_stream(
            coordinator,
            pm,
            items=[reasoning, function_call, custom_call],
        )

        next_body = _body(
            turn="turn-b",
            input_items=[
                *_body()["input"],
                reasoning,
                _abort_item(),
                {"type": "message", "role": "user", "content": "continue"},
            ],
        )
        preparation = await coordinator.prepare_request(
            principal_id="client-a",
            provider_name="deepseek",
            model="deepseek-chat",
            body=next_body,
        )
        assert preparation.replay is not None
        replay_input = preparation.body["input"]
        assert replay_input[1:6] == [
            reasoning,
            function_call,
            custom_call,
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": SOFT_INTERRUPT_CANCELLED_RESULT,
            },
            {
                "type": "custom_tool_call_output",
                "call_id": "call-2",
                "output": SOFT_INTERRUPT_CANCELLED_RESULT,
            },
        ]
        assert replay_input[6] == {
            "type": "message",
            "role": "user",
            "content": "continue",
        }
        assert not any(item == _abort_item() for item in replay_input)
        assert preparation.profile["soft_interrupt_replay_mode"] == (
            "steer_continuation"
        )
        assert preparation.profile["soft_interrupt_aborted_marker_removed"] is True
        assert coordinator.target_prefix_matches(
            preparation.replay,
            {
                "messages": [
                    *_target()["messages"],
                    {"role": "assistant", "content": "hidden"},
                ]
            },
        )
        await coordinator.finish_replay(preparation.replay, accepted=True)
        assert pm.count_soft_interrupt_handoffs() == 0
        await coordinator.close()
        pm.close()

    asyncio.run(scenario())


def test_fork_and_principal_never_consume_parent_handoff(tmp_path):
    async def scenario():
        pm = PersistenceManager(str(tmp_path))
        coordinator = SoftInterruptCoordinator(pm)
        await _capture_stream(
            coordinator,
            pm,
            items=[{"type": "message", "role": "assistant", "content": "hidden"}],
        )
        for principal, thread in (
            ("client-a", "fork-one"),
            ("client-a", "fork-two"),
            ("client-b", "thread-a"),
        ):
            preparation = await coordinator.prepare_request(
                principal_id=principal,
                provider_name="deepseek",
                model="deepseek-chat",
                body=_body(
                    thread=thread,
                    turn="turn-b",
                    session="session-a",
                    input_items=[*_body()["input"], _abort_item()],
                    forked_from="thread-a",
                ),
            )
            assert preparation.replay is None
        assert pm.count_soft_interrupt_handoffs() == 1
        await coordinator.close()
        pm.close()

    asyncio.run(scenario())


def test_target_prefix_mismatch_discards_candidate(tmp_path):
    async def scenario():
        pm = PersistenceManager(str(tmp_path))
        coordinator = SoftInterruptCoordinator(pm)
        await _capture_stream(
            coordinator,
            pm,
            items=[{"type": "message", "role": "assistant", "content": "hidden"}],
        )
        preparation = await coordinator.prepare_request(
            principal_id="client-a",
            provider_name="deepseek",
            model="deepseek-chat",
            body=_body(
                turn="turn-b",
                input_items=[*_body()["input"], _abort_item()],
            ),
        )
        assert preparation.replay is not None
        assert not coordinator.target_prefix_matches(
            preparation.replay,
            {"messages": [{"role": "user", "content": "changed"}]},
        )
        await coordinator.finish_replay(preparation.replay, accepted=False)
        assert pm.count_soft_interrupt_handoffs() == 0
        await coordinator.close()
        pm.close()

    asyncio.run(scenario())


def test_drain_callback_waits_for_upstream_and_error_does_not_persist(tmp_path):
    class RequestLog:
        def __init__(self):
            self.profiles = []

        def update_profile(self, entry_id, values):
            self.profiles.append((entry_id, values))

    async def scenario():
        pm = PersistenceManager(str(tmp_path))
        coordinator = SoftInterruptCoordinator(pm)
        preparation = await coordinator.prepare_request(
            principal_id="client-a",
            provider_name="deepseek",
            model="deepseek-chat",
            body=_body(),
        )
        request_log = RequestLog()
        capture = coordinator.create_capture(
            preparation=preparation,
            principal_id="client-a",
            provider_name="deepseek",
            model="deepseek-chat",
            source_body=_body(),
            target_body=_target(),
            entry_id="entry-a",
            request_log=request_log,
        )
        assert capture is not None
        release = asyncio.Event()
        callback_called = asyncio.Event()

        async def source():
            capture.observe(
                _done({"type": "message", "role": "assistant", "content": "partial"})
            )
            yield b"partial"
            await release.wait()
            raise TimeoutError("upstream timeout")

        stream = await coordinator.wrap(source(), capture)
        stream.add_drain_callback(callback_called.set)
        assert await anext(stream) == b"partial"
        await stream.detach()
        assert not callback_called.is_set()
        release.set()
        await stream.detach_and_wait()
        assert callback_called.is_set()
        assert pm.count_soft_interrupt_handoffs() == 0
        assert ("entry-a", {"soft_interrupt_drain_outcome": "timeout"}) in (
            request_log.profiles
        )
        await coordinator.close()
        pm.close()

    asyncio.run(scenario())


def test_coordinator_close_cancels_active_drain_without_persisting(tmp_path):
    async def scenario():
        pm = PersistenceManager(str(tmp_path))
        coordinator = SoftInterruptCoordinator(pm)
        preparation = await coordinator.prepare_request(
            principal_id="client-a",
            provider_name="deepseek",
            model="deepseek-chat",
            body=_body(),
        )
        capture = coordinator.create_capture(
            preparation=preparation,
            principal_id="client-a",
            provider_name="deepseek",
            model="deepseek-chat",
            source_body=_body(),
            target_body=_target(),
            entry_id=None,
            request_log=None,
        )
        assert capture is not None
        started = asyncio.Event()

        async def source():
            started.set()
            await asyncio.Event().wait()
            yield b"unreachable"

        await coordinator.wrap(source(), capture)
        await started.wait()
        await coordinator.close()
        assert pm.count_soft_interrupt_handoffs() == 0
        pm.close()

    asyncio.run(scenario())


def test_same_turn_steer_cancels_instead_of_waiting_for_safe_drain(tmp_path):
    async def scenario():
        pm = PersistenceManager(str(tmp_path))
        coordinator = SoftInterruptCoordinator(pm)
        first = await coordinator.prepare_request(
            principal_id="client-a",
            provider_name="deepseek",
            model="deepseek-chat",
            body=_body(),
        )
        capture = coordinator.create_capture(
            preparation=first,
            principal_id="client-a",
            provider_name="deepseek",
            model="deepseek-chat",
            source_body=_body(),
            target_body=_target(),
            entry_id=None,
            request_log=None,
        )
        assert capture is not None
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def source():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            yield b"unreachable"

        await coordinator.wrap(source(), capture)
        await started.wait()
        steer = await coordinator.prepare_request(
            principal_id="client-a",
            provider_name="deepseek",
            model="deepseek-chat",
            body=_body(
                turn="turn-a",
                input_items=[
                    *_body()["input"],
                    {"type": "message", "role": "user", "content": "steer"},
                ],
            ),
        )
        assert cancelled.is_set()
        assert steer.replay is None
        assert (
            steer.profile["soft_interrupt_skip_reason"] == "active_not_hard_interrupt"
        )
        assert pm.count_soft_interrupt_handoffs() == 0
        await coordinator.close()
        pm.close()

    asyncio.run(scenario())


def test_only_source_defined_abort_marker_replays_and_mismatch_discards(tmp_path):
    async def scenario():
        pm = PersistenceManager(str(tmp_path))
        coordinator = SoftInterruptCoordinator(pm)
        hidden = {"type": "message", "role": "assistant", "content": "hidden"}
        await _capture_stream(coordinator, pm, items=[hidden])
        fake_abort = {
            "type": "message",
            "role": "user",
            "content": "<turn_aborted>esc</turn_aborted>",
        }
        fake = await coordinator.prepare_request(
            principal_id="client-a",
            provider_name="deepseek",
            model="deepseek-chat",
            body=_body(turn="turn-b", input_items=[*_body()["input"], fake_abort]),
        )
        assert fake.replay is None
        assert fake.profile["soft_interrupt_skip_reason"] == "not_hard_interrupt"
        assert pm.count_soft_interrupt_handoffs() == 0

        await _capture_stream(coordinator, pm, items=[hidden])
        developer_abort = {
            "type": "message",
            "role": "developer",
            "content": (
                "<turn_aborted>\n"
                "The previous turn was interrupted on purpose. Any running unified exec "
                "processes may still be running in the background. If any tools/commands "
                "were aborted, they may have partially executed.\n</turn_aborted>"
            ),
        }
        developer = await coordinator.prepare_request(
            principal_id="client-a",
            provider_name="deepseek",
            model="deepseek-chat",
            body=_body(turn="turn-c", input_items=[*_body()["input"], developer_abort]),
        )
        assert developer.replay is not None
        await coordinator.finish_replay(developer.replay, accepted=True)

        await _capture_stream(coordinator, pm, items=[hidden])
        mismatch = await coordinator.prepare_request(
            principal_id="client-a",
            provider_name="another-provider",
            model="deepseek-chat",
            body=_body(turn="turn-d", input_items=[*_body()["input"], _abort_item()]),
        )
        assert mismatch.replay is None
        assert (
            mismatch.profile["soft_interrupt_skip_reason"]
            == "identity_or_prefix_mismatch"
        )
        assert pm.count_soft_interrupt_handoffs() == 0
        await coordinator.close()
        pm.close()

    asyncio.run(scenario())
