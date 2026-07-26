"""Proxy integration tests for Responses-to-Chat soft interruption."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from codex_rosetta._vendor.httpserver import StreamingResponse
from codex_rosetta.gateway.proxy import handle_streaming
from codex_rosetta.gateway.soft_interrupt import (
    SoftInterruptCoordinator,
    SoftInterruptStream,
)
from codex_rosetta.gateway.transport._base import UpstreamStream
from codex_rosetta.observability.persistence import PersistenceManager
from codex_rosetta.routing import ResolvedRoute


class _ChatStream(UpstreamStream):
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.status_code = 200
        self._chunks = chunks

    async def read_error(self) -> str:
        return ""

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        for chunk in self._chunks:
            yield chunk

    async def close(self) -> None:
        return None


def _chunk(*, content: str = "", finish_reason: str | None = None) -> dict[str, Any]:
    return {
        "id": "chatcmpl-soft",
        "object": "chat.completion.chunk",
        "created": 123,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "delta": {"content": content} if content else {},
                "finish_reason": finish_reason,
            }
        ],
    }


def _route() -> ResolvedRoute:
    return ResolvedRoute(
        source_provider="openai_responses",
        target_provider="openai_chat",
        provider_name="deepseek",
        upstream_model="deepseek-chat",
    )


def _provider_info() -> MagicMock:
    info = MagicMock()
    info.base_url = "https://api.example.test"
    return info


def _body(turn_id: str, input_items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": "deepseek-chat",
        "stream": True,
        "prompt_cache_key": "cache-a",
        "input": input_items,
        "client_metadata": {
            "x-codex-turn-metadata": json.dumps(
                {
                    "request_kind": "turn",
                    "session_id": "session-a",
                    "thread_id": "thread-a",
                    "turn_id": turn_id,
                    "window_id": "window-a",
                },
                separators=(",", ":"),
            )
        },
    }


def test_detached_chat_stream_is_replayed_into_next_upstream_prefix(tmp_path):
    async def scenario() -> None:
        pm = PersistenceManager(str(tmp_path))
        coordinator = SoftInterruptCoordinator(pm)
        sent_bodies: list[dict[str, Any]] = []
        streams = [
            _ChatStream([_chunk(content="hidden"), _chunk(finish_reason="stop")]),
            _ChatStream([_chunk(content="continued"), _chunk(finish_reason="stop")]),
        ]

        async def send_streaming(
            provider_info, target_provider, body, model, *, extra_headers=None
        ):
            sent_bodies.append(body)
            return streams.pop(0)

        transport = MagicMock()
        transport.send_streaming = AsyncMock(side_effect=send_streaming)
        original_input = [{"type": "message", "role": "user", "content": "hello"}]
        first_body = _body("turn-a", original_input)
        first_preparation = await coordinator.prepare_request(
            principal_id="client-a",
            provider_name="deepseek",
            model="deepseek-chat",
            body=first_body,
        )
        first_response, _ = await handle_streaming(
            _route(),
            _provider_info(),
            first_body,
            transport=transport,
            persistence=pm,
            soft_interrupt_coordinator=coordinator,
            soft_interrupt_preparation=first_preparation,
            principal_id="client-a",
        )
        assert isinstance(first_response, StreamingResponse)
        first_generator = first_response._generator
        assert isinstance(first_generator, SoftInterruptStream)
        await anext(first_generator)
        await first_generator.aclose()

        abort = {
            "type": "message",
            "role": "user",
            "content": (
                "<turn_aborted>\n"
                "The user interrupted the previous turn on purpose. Any running unified "
                "exec processes may still be running in the background. If any "
                "tools/commands were aborted, they may have partially executed.\n"
                "</turn_aborted>"
            ),
        }
        continuation = {"type": "message", "role": "user", "content": "continue"}
        second_body = _body("turn-b", [*original_input, abort, continuation])
        second_preparation = await coordinator.prepare_request(
            principal_id="client-a",
            provider_name="deepseek",
            model="deepseek-chat",
            body=second_body,
        )
        assert second_preparation.replay is not None
        second_response, _ = await handle_streaming(
            _route(),
            _provider_info(),
            second_preparation.body,
            transport=transport,
            persistence=pm,
            soft_interrupt_coordinator=coordinator,
            soft_interrupt_preparation=second_preparation,
            principal_id="client-a",
        )
        assert isinstance(second_response, StreamingResponse)
        assert [chunk async for chunk in second_response._generator]

        assert len(sent_bodies) == 2
        replay_messages = sent_bodies[1]["messages"]
        assert replay_messages[0] == {"role": "user", "content": "hello"}
        assert replay_messages[1]["role"] == "assistant"
        assert replay_messages[1]["content"] == "hidden"
        assert replay_messages[2] == {"role": "user", "content": "continue"}
        assert all(
            message.get("content") != abort["content"] for message in replay_messages
        )
        assert pm.count_soft_interrupt_handoffs() == 0
        await coordinator.close()
        pm.close()

    asyncio.run(scenario())
