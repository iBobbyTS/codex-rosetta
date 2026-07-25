"""Model-path credential boundary regression tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest

from codex_rosetta._vendor.httpserver import StreamingResponse
from codex_rosetta.auto_detect import ProviderType
from codex_rosetta.gateway.model_protocol_credentials import (
    MODEL_RESPONSE_AUTH_FIELD_PATHS,
)
from codex_rosetta.gateway.proxy import handle_non_streaming, handle_streaming
from codex_rosetta.gateway.stream_trace import StreamTraceConfig, StreamTraceState
from codex_rosetta.gateway.transport._base import (
    UpstreamResponse,
    UpstreamStream,
)
from codex_rosetta.gateway.transport.provider_info import ProviderInfo, openai_auth
from codex_rosetta.routing import ResolvedRoute


def _provider(token: str) -> ProviderInfo:
    return ProviderInfo(
        "test-provider",
        api_key=token,
        base_url="https://upstream.example/v1",
        auth_header_fn=openai_auth,
        url_template="{base_url}/responses",
    )


def _passthrough_route() -> ResolvedRoute:
    return ResolvedRoute(
        source_provider="openai_responses",
        target_provider="openai_responses",
        provider_name="test-provider",
        upstream_model="test-model",
    )


def _converted_route(target_provider: ProviderType = "openai_chat") -> ResolvedRoute:
    return ResolvedRoute(
        source_provider="openai_responses",
        target_provider=target_provider,
        provider_name="test-provider",
        upstream_model="test-model",
    )


class _StaticTransport:
    def __init__(
        self,
        *,
        response: UpstreamResponse | None = None,
        stream: UpstreamStream | None = None,
    ) -> None:
        self.response = response
        self.stream = stream

    async def send_request(self, *args: Any, **kwargs: Any) -> UpstreamResponse:
        del args, kwargs
        assert self.response is not None
        return self.response

    async def send_streaming(self, *args: Any, **kwargs: Any) -> UpstreamStream:
        del args, kwargs
        assert self.stream is not None
        return self.stream

    async def send_passthrough(
        self,
        provider_info: ProviderInfo,
        url: str,
        body: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> UpstreamResponse:
        del provider_info, url, body, extra_headers
        assert self.response is not None
        return self.response

    async def close(self) -> None:
        return None


class _StaticStream(UpstreamStream):
    def __init__(
        self,
        *,
        status_code: int = 200,
        events: list[dict[str, Any]] | None = None,
        raw_chunks: list[bytes] | None = None,
        error: str = "",
    ) -> None:
        self.status_code = status_code
        self.events = events or []
        self.raw_chunks = raw_chunks
        self.error = error
        self.closed = False
        self.headers = {
            "authorization": "Bearer upstream-secret",
            "set-cookie": "session=upstream-secret",
            "www-authenticate": "Bearer realm=upstream",
        }

    async def read_error(self) -> str:
        return self.error

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        for event in self.events:
            yield event

    def aiter_raw_bytes(self) -> AsyncIterator[bytes] | None:
        if self.raw_chunks is None:
            return None

        async def chunks() -> AsyncIterator[bytes]:
            for chunk in self.raw_chunks or []:
                yield chunk

        return chunks()

    async def close(self) -> None:
        self.closed = True


def _responses_output_text(document: dict[str, Any]) -> str:
    return "".join(
        part.get("text", "")
        for item in document.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )


@pytest.mark.parametrize("status_code", [200, 401])
def test_responses_passthrough_preserves_ordinary_provider_token_text(
    status_code: int,
) -> None:
    token = "passthrough-provider-secret"
    payload = {
        "id": "resp_test",
        "object": "response",
        "status": "completed" if status_code == 200 else "failed",
        "output": [],
        "message": f"before {token} after",
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()

    response, _profile = asyncio.run(
        handle_non_streaming(
            _passthrough_route(),
            _provider(token),
            {"model": "test-model", "input": "hello"},
            transport=_StaticTransport(
                response=UpstreamResponse(
                    status_code=status_code,
                    body=payload if status_code < 400 else None,
                    raw_content=raw,
                )
            ),
        )
    )

    assert response.status_code == status_code
    if status_code < 400:
        assert response.body == raw
    else:
        returned = json.loads(response.body)
        assert returned["message"] == f"Upstream: before {token} after"


@pytest.mark.parametrize(
    ("target_provider", "upstream"),
    [
        (
            "openai_chat",
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 123,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "before configured-provider-secret after",
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        ),
        (
            "anthropic",
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": [
                    {
                        "type": "text",
                        "text": "before configured-provider-secret after",
                    }
                ],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 2},
            },
        ),
        (
            "google",
            {
                "candidates": [
                    {
                        "index": 0,
                        "content": {
                            "role": "model",
                            "parts": [
                                {"text": ("before configured-provider-secret after")}
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 1,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 3,
                },
            },
        ),
    ],
)
def test_converted_responses_preserve_ordinary_provider_token_text(
    target_provider: ProviderType,
    upstream: dict[str, Any],
) -> None:
    response, _profile = asyncio.run(
        handle_non_streaming(
            _converted_route(target_provider),
            _provider("configured-provider-secret"),
            {"model": "test-model", "input": "hello"},
            transport=_StaticTransport(
                response=UpstreamResponse(
                    status_code=200,
                    body=upstream,
                    raw_content=json.dumps(upstream).encode(),
                )
            ),
        )
    )

    assert response.status_code == 200
    assert _responses_output_text(json.loads(response.body)) == (
        "before configured-provider-secret after"
    )


def test_passthrough_stream_over_fragment_limit_is_byte_identical_and_completes(
    tmp_path: Path,
) -> None:
    token = "configured-provider-secret"
    trace_path = tmp_path / "over-fragment-limit.jsonl"
    trace_state = StreamTraceState(
        StreamTraceConfig(enabled=True, path=str(trace_path)),
        token_values={token},
    )
    frames = [
        (
            'data: {"type":"response.output_text.delta",'
            f'"delta":"{token if index == 2048 else "x"}"}}\n\n'
        ).encode()
        for index in range(4097)
    ]
    frames.append(b'data: {"type":"response.completed","response":{}}\n\n')

    async def run() -> tuple[bytes, StreamingResponse]:
        response, _profile = await handle_streaming(
            _passthrough_route(),
            _provider(token),
            {"model": "test-model", "input": "hello", "stream": True},
            transport=_StaticTransport(stream=_StaticStream(raw_chunks=frames)),
            extra_headers={"x-request-id": "req-over-fragment-limit"},
            entry_id="log-over-fragment-limit",
            stream_trace_state=trace_state,
        )
        assert isinstance(response, StreamingResponse)
        emitted = b"".join([cast(bytes, chunk) async for chunk in response._generator])
        return emitted, response

    emitted, response = asyncio.run(run())

    assert emitted == b"".join(frames)
    assert b"response.completed" in emitted
    assert not any(
        name.lower() in {"authorization", "set-cookie", "www-authenticate"}
        for name in response.headers
    )
    trace_records = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert trace_records[-1]["stage"] == "stream_complete"
    assert trace_records[-1]["data"]["stream_outcome"] == "completed"


def test_converted_stream_preserves_provider_token_text() -> None:
    token = "converted-stream-secret"
    events = [
        {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 123,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": token},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 123,
            "model": "test-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]

    async def run() -> str:
        response, _profile = await handle_streaming(
            _converted_route(),
            _provider(token),
            {"model": "test-model", "input": "hello", "stream": True},
            transport=_StaticTransport(stream=_StaticStream(events=events)),
        )
        assert isinstance(response, StreamingResponse)
        return "".join([cast(str, chunk) async for chunk in response._generator])

    emitted = asyncio.run(run())

    assert token in emitted
    assert "response.completed" in emitted


def test_current_model_protocols_declare_no_response_auth_fields() -> None:
    assert MODEL_RESPONSE_AUTH_FIELD_PATHS == {
        "openai_chat": (),
        "openai_responses": (),
        "open_responses": (),
        "anthropic": (),
        "google": (),
    }
