"""Tests for direct OpenAI Responses passthrough in the gateway proxy."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from codex_rosetta._vendor.httpserver import StreamingResponse
from codex_rosetta.gateway.proxy import handle_non_streaming, handle_streaming
from codex_rosetta.gateway.tool_profiles import tool_profile_contract
from codex_rosetta.gateway.transport._base import UpstreamResponse, UpstreamStream
from codex_rosetta.observability.persistence import PersistenceManager
from codex_rosetta.routing import ResolvedRoute, is_openai_responses_passthrough


def _responses_route() -> ResolvedRoute:
    profile = tool_profile_contract()["readonly"]["openai-responses-tool-mapping-only"][
        "tools"
    ]
    return ResolvedRoute(
        source_provider="openai_responses",
        target_provider="openai_responses",
        provider_name="test-provider",
        upstream_model="gpt-test",
        tool_profile_name="test-pass-through",
        tool_profile=profile,
        responses_processing="passthrough",
    )


def _provider_info() -> MagicMock:
    info = MagicMock()
    info.base_url = "https://api.example.test"
    return info


def test_responses_processing_mode_controls_same_protocol_passthrough():
    passthrough = _responses_route()
    rosetta = ResolvedRoute(
        source_provider="openai_responses",
        target_provider="openai_responses",
        provider_name="test-provider",
        responses_processing="rosetta",
    )

    assert is_openai_responses_passthrough(passthrough) is True
    assert is_openai_responses_passthrough(rosetta) is False


def test_openai_responses_non_streaming_direct_passthrough():
    """Same-protocol Responses requests should not be decoded into IR."""
    captured_body: dict[str, Any] = {}
    upstream_body = {
        "id": "resp_123",
        "object": "response",
        "model": "gpt-test",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "phase": "commentary",
                "content": [{"type": "output_text", "text": "work"}],
            }
        ],
        "custom_passthrough_field": {"kept": True},
    }
    upstream_raw = json.dumps(upstream_body, separators=(",", ":")).encode()

    async def send_request(
        provider_info, target_provider, body, model, *, extra_headers=None
    ):
        captured_body.update(body)
        return UpstreamResponse(
            status_code=200,
            body=upstream_body,
            raw_content=upstream_raw,
        )

    transport = MagicMock()
    transport.send_request = AsyncMock(side_effect=send_request)
    body = {
        "model": "gpt-test",
        "input": [{"type": "message", "role": "user", "content": "hello"}],
        "tool_choice": {"mode": "auto", "tool_name": ""},
        "parallel_tool_calls": False,
        "phase": "not-a-real-top-level-field-but-preserved",
    }

    async def run():
        return await handle_non_streaming(
            _responses_route(),
            _provider_info(),
            body,
            transport=transport,
            extra_headers={"User-Agent": "codex-test"},
        )

    response, profile = asyncio.run(run())

    assert response.status_code == 200
    assert response.body == upstream_raw
    assert json.loads(response.body) == upstream_body
    assert captured_body == body
    assert profile["passthrough"] is True
    assert "request_conversion_ms" not in profile


def test_remote_compaction_native_reason_is_byte_passthrough_without_mapping(tmp_path):
    captured_body: dict[str, Any] = {}
    native = {
        "id": "resp_native",
        "object": "response",
        "model": "gpt-test",
        "status": "completed",
        "output": [{"type": "compaction", "encrypted_content": "upstream-token"}],
    }
    raw = json.dumps(native, separators=(",", ":")).encode()

    async def send_request(
        provider_info, target_provider, body, model, *, extra_headers=None
    ):
        captured_body.update(body)
        return UpstreamResponse(status_code=200, body=native, raw_content=raw)

    transport = MagicMock()
    transport.send_request = AsyncMock(side_effect=send_request)
    body = {
        "model": "gpt-test",
        "input": [{"type": "compaction_trigger"}],
        "client_metadata": {
            "x-codex-turn-metadata": json.dumps(
                {"compaction": {"reason": "context_limit"}}
            )
        },
    }
    persistence = PersistenceManager(str(tmp_path))

    response, profile = asyncio.run(
        handle_non_streaming(
            _responses_route(),
            _provider_info(),
            body,
            transport=transport,
            persistence=persistence,
        )
    )

    assert response.body == raw
    assert captured_body == body
    assert profile["compaction_mode"] == "native"
    assert persistence.count_codex_compaction_mappings() == 0
    persistence.close()


def test_model_switch_compaction_uses_rosetta_summary_even_on_passthrough_route(
    tmp_path,
):
    captured: list[dict[str, Any]] = []
    summary = {
        "id": "resp_summary",
        "object": "response",
        "model": "gpt-test",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Orchid summary"}],
            }
        ],
    }

    async def send_request(
        provider_info, target_provider, body, model, *, extra_headers=None
    ):
        captured.append(body)
        return UpstreamResponse(
            status_code=200,
            body=summary,
            raw_content=json.dumps(summary).encode(),
        )

    transport = MagicMock()
    transport.send_request = AsyncMock(side_effect=send_request)
    body = {
        "model": "gpt-test",
        "input": [
            {"type": "message", "role": "user", "content": "history"},
            {"type": "compaction_trigger"},
        ],
        "tools": [{"type": "function", "name": "not-forwarded"}],
        "client_metadata": {
            "x-codex-turn-metadata": json.dumps(
                {"compaction": {"reason": "comp_hash_changed"}}
            )
        },
    }
    persistence = PersistenceManager(str(tmp_path))

    response, profile = asyncio.run(
        handle_non_streaming(
            _responses_route(),
            _provider_info(),
            body,
            transport=transport,
            persistence=persistence,
        )
    )

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert profile["compaction_mode"] == "rosetta"
    assert len(captured) == 1
    assert captured[0]["input"][-1]["content"][0]["text"].startswith(
        "You are performing a CONTEXT CHECKPOINT COMPACTION"
    )
    assert "tools" not in captured[0]
    assert "client_metadata" not in captured[0]
    assert payload["output"][0]["encrypted_content"].startswith("rskc_v1_")
    assert persistence.count_codex_compaction_mappings() == 1
    persistence.close()


def test_internal_call_can_retain_persistence_without_writing_error_dump():
    async def send_request(
        provider_info, target_provider, body, model, *, extra_headers=None
    ):
        return UpstreamResponse(
            status_code=500,
            body={"error": "summary failed"},
            raw_content=b'{"error":"summary failed"}',
        )

    transport = MagicMock()
    transport.send_request = AsyncMock(side_effect=send_request)
    persistence = MagicMock()

    response, _ = asyncio.run(
        handle_non_streaming(
            _responses_route(),
            _provider_info(),
            {"model": "gpt-test", "input": []},
            transport=transport,
            persistence=persistence,
            disable_error_dump=True,
        )
    )

    assert response.status_code == 500
    persistence.insert_error_dump.assert_not_called()
    persistence.insert_dump_body.assert_not_called()


def test_direct_passthrough_preserves_image_generation_tools():
    """Responses passthrough bypasses every Chat-only tool adaptation."""
    captured_body: dict[str, Any] = {}
    upstream_body = {
        "id": "resp_123",
        "object": "response",
        "model": "gpt-test",
        "status": "completed",
        "output": [],
    }

    async def send_request(
        provider_info, target_provider, body, model, *, extra_headers=None
    ):
        captured_body.update(body)
        return UpstreamResponse(
            status_code=200,
            body=upstream_body,
            raw_content=json.dumps(upstream_body).encode(),
        )

    transport = MagicMock()
    transport.send_request = AsyncMock(side_effect=send_request)
    body = {
        "model": "gpt-test",
        "input": "hello",
        "tools": [
            {"type": "web_search_preview"},
            {"type": "image_generation"},
            {
                "type": "function",
                "function": {"name": "image_generation", "parameters": {}},
            },
            {"type": "function", "name": "apply_patch", "parameters": {}},
        ],
        "tool_choice": {"mode": "tool", "tool_name": "image_generation"},
        "tool_config": {"disable_parallel": True},
    }

    async def run():
        return await handle_non_streaming(
            _responses_route(),
            _provider_info(),
            body,
            transport=transport,
        )

    response, profile = asyncio.run(run())

    assert response.status_code == 200
    assert profile["passthrough"] is True
    assert captured_body == body
    assert captured_body["tool_config"] == {"disable_parallel": True}
    assert body["tools"][1] == {"type": "image_generation"}


def test_direct_passthrough_preserves_responses_lite_tools():
    """Responses Lite embedded tools also pass through unchanged."""
    captured_body: dict[str, Any] = {}

    async def send_request(
        provider_info, target_provider, body, model, *, extra_headers=None
    ):
        captured_body.update(body)
        response_body = {"id": "resp_123", "status": "completed", "output": []}
        return UpstreamResponse(
            status_code=200,
            body=response_body,
            raw_content=json.dumps(response_body).encode(),
        )

    transport = MagicMock()
    transport.send_request = AsyncMock(side_effect=send_request)
    body = {
        "model": "gpt-test",
        "input": [
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": [
                    {
                        "type": "namespace",
                        "name": "image_gen",
                        "tools": [
                            {
                                "type": "function",
                                "name": "imagegen",
                                "parameters": {},
                            }
                        ],
                    },
                    {
                        "type": "function",
                        "name": "exec_command",
                        "parameters": {},
                    },
                    {
                        "type": "function",
                        "name": "image_gen__imagegen",
                        "parameters": {},
                    },
                ],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            },
        ],
        "tool_choice": {"type": "image_gen"},
        "tool_config": {"disable_parallel": True},
    }

    async def run():
        return await handle_non_streaming(
            _responses_route(),
            _provider_info(),
            body,
            transport=transport,
        )

    response, _ = asyncio.run(run())

    assert response.status_code == 200
    assert captured_body == body


class _RawStream(UpstreamStream):
    def __init__(self, chunks: list[bytes], *, status_code: int = 200) -> None:
        self.status_code = status_code
        self._chunks = chunks
        self.closed = False

    async def read_error(self) -> str:
        return b"".join(self._chunks).decode()

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        async def gen() -> AsyncIterator[dict[str, Any]]:
            raise AssertionError("Responses passthrough must not parse stream chunks")
            yield {}

        return gen()

    def aiter_raw_bytes(self) -> AsyncIterator[bytes]:
        async def gen() -> AsyncIterator[bytes]:
            for chunk in self._chunks:
                yield chunk

        return gen()

    async def close(self) -> None:
        self.closed = True


def test_openai_responses_streaming_direct_raw_passthrough():
    """Same-protocol Responses streams should forward filtered raw SSE bytes."""
    raw_chunks = [
        b'event: response.created\ndata: {"type":"response.created"}\n\n',
        b'event: response.output_item.added\ndata: {"type":"response.output_item.added","item":{"type":"message","phase":"commentary"}}\n\n',
    ]
    stream = _RawStream(raw_chunks)
    captured_body: dict[str, Any] = {}

    async def send_streaming(
        provider_info, target_provider, body, model, *, extra_headers=None
    ):
        captured_body.update(body)
        return stream

    transport = MagicMock()
    transport.send_streaming = AsyncMock(side_effect=send_streaming)
    body = {
        "model": "gpt-test",
        "input": [
            {
                "type": "additional_tools",
                "tools": [
                    {"type": "image_generation"},
                    {"type": "web_search_preview"},
                ],
            },
            {"type": "message", "role": "user", "content": "hello"},
        ],
        "stream": True,
    }

    async def run():
        response, profile = await handle_streaming(
            _responses_route(),
            _provider_info(),
            body,
            transport=transport,
            extra_headers={"x-request-id": "req-123"},
        )
        assert isinstance(response, StreamingResponse)
        chunks: list[bytes] = []
        async for chunk in response._generator:
            assert isinstance(chunk, bytes)
            chunks.append(chunk)
        return response, profile, chunks

    response, profile, chunks = asyncio.run(run())

    assert response.status_code == 200
    assert response.content_type == "text/event-stream"
    assert chunks == raw_chunks
    assert captured_body == body
    assert profile["passthrough"] is True
    assert "request_conversion_ms" not in profile
