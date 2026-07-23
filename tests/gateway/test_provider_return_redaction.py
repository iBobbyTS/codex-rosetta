"""Gateway provider-return credential redaction regression tests."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codex_rosetta.gateway.app as app_module
from codex_rosetta._vendor.httpserver import Response, StreamingResponse
from codex_rosetta.auto_detect import ProviderType
from codex_rosetta.converters.openai_responses import OpenAIResponsesConverter
from codex_rosetta.gateway.proxy import (
    _StreamTerminalState,
    _finalize_response_stream,
    _stream_event_generator,
    _stream_terminal_recovery,
    handle_non_streaming,
    handle_streaming,
)
from codex_rosetta.gateway.logging import BodyLogState, UpstreamErrorLogState
from codex_rosetta.gateway.stream_trace import StreamTraceConfig, StreamTraceState
from codex_rosetta.gateway.transport._base import (
    UpstreamConnectionError,
    UpstreamCredentialCollisionError,
    UpstreamResponse,
    UpstreamResponseContractError,
    UpstreamStream,
)
from codex_rosetta.gateway.transport.credential_redaction import (
    ProviderCredentialOutputGate,
)
from codex_rosetta.gateway.transport.provider_info import ProviderInfo, openai_auth
from codex_rosetta.observability import (
    MetricsCollector,
    PersistenceManager,
    RequestLog,
)
from codex_rosetta.observability.redaction import SecretRedactor
from codex_rosetta.routing import ResolvedRoute
from codex_rosetta.types.ir.stream import ReasoningDeltaEvent


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


def test_output_gate_reports_missing_reasoning_identity_as_contract_error() -> None:
    gate = ProviderCredentialOutputGate(
        _provider("configured-provider-secret"),
        "openai_responses",
    )

    with pytest.raises(UpstreamResponseContractError) as caught:
        gate.inspect_stream_event(
            {
                "type": "response.reasoning_summary_text.delta",
                "delta": "",
                "sequence_number": 2,
            }
        )

    message = str(caught.value)
    assert "missing or invalid summary_index stream identity" in message
    assert "credential" not in message


def test_converter_reasoning_delta_satisfies_output_gate_contract() -> None:
    converter = OpenAIResponsesConverter()
    event = cast(
        dict[str, Any],
        converter.stream_response_to_provider(
            cast(
                ReasoningDeltaEvent,
                {"type": "reasoning_delta", "reasoning": "thinking..."},
            )
        ),
    )
    gate = ProviderCredentialOutputGate(
        _provider("configured-provider-secret"),
        "openai_responses",
    )

    gate.inspect_stream_event(event)

    assert event["summary_index"] == 0


def test_stream_contract_error_is_reported_without_credential_claim() -> None:
    message = (
        "Upstream response violates the required consumer contract: "
        "missing or invalid summary_index stream identity; response blocked"
    )
    terminal_state = _StreamTerminalState()

    event = _stream_terminal_recovery(
        UpstreamResponseContractError(message),
        "openai_responses",
        terminal_state,
        None,
    )

    assert isinstance(event, str)
    assert message in event
    assert "contains a configured credential" not in event
    assert terminal_state.outcome == "error"
    assert terminal_state.error == message


class _StaticTransport:
    def __init__(
        self,
        *,
        response: UpstreamResponse | None = None,
        stream: UpstreamStream | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.response = response
        self.stream = stream
        self.failure = failure

    async def send_request(self, *args: Any, **kwargs: Any) -> UpstreamResponse:
        if self.failure is not None:
            raise self.failure
        assert self.response is not None
        return self.response

    async def send_streaming(self, *args: Any, **kwargs: Any) -> UpstreamStream:
        if self.failure is not None:
            raise self.failure
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
        if self.failure is not None:
            raise self.failure
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


@pytest.mark.parametrize("status_code", [200, 401])
def test_responses_passthrough_blocks_credential_collision(status_code: int) -> None:
    token = "passthrough-provider-secret"
    payload = {
        "id": "resp_test",
        "object": "response",
        "status": "completed" if status_code == 200 else "failed",
        "output": [],
        "nested": {
            token: "ordinary-value-under-secret-key",
            "message": f"before {token} after",
        },
    }
    response, _profile = asyncio.run(
        handle_non_streaming(
            _passthrough_route(),
            _provider(token),
            {"model": "test-model", "input": "hello"},
            transport=_StaticTransport(
                response=UpstreamResponse(
                    status_code=status_code,
                    body=payload if status_code < 400 else None,
                    raw_content=json.dumps(payload, separators=(",", ":")).encode(),
                )
            ),
        )
    )

    assert response.status_code == 502
    assert token.encode() not in response.body
    assert b"response blocked" in response.body


@pytest.mark.parametrize("status_code", [200, 429])
def test_converted_response_blocks_credential_collision(status_code: int) -> None:
    token = "converted-provider-secret"
    upstream = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 123,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": f"before {token} after",
                },
                "finish_reason": "stop",
            }
        ],
    }
    if status_code >= 400:
        upstream = {"error": {"message": f"failed with {token}"}}

    response, _profile = asyncio.run(
        handle_non_streaming(
            _converted_route(),
            _provider(token),
            {"model": "test-model", "input": "hello"},
            transport=_StaticTransport(
                response=UpstreamResponse(
                    status_code=status_code,
                    body=upstream if status_code < 400 else None,
                    raw_content=json.dumps(upstream, separators=(",", ":")).encode(),
                )
            ),
        )
    )

    assert response.status_code == 502
    assert token.encode() not in response.body
    assert b"response blocked" in response.body


def _responses_output_text(document: dict[str, Any]) -> str:
    return "".join(
        part.get("text", "")
        for item in document.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )


@pytest.mark.parametrize(
    ("target_provider", "upstream"),
    [
        (
            "openai_chat",
            {
                "id": "chatcmpl-cross-document",
                "object": "chat.completion",
                "created": 123,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "BETA",
                        },
                        "finish_reason": "stop",
                    },
                    {
                        "index": 1,
                        "message": {
                            "role": "assistant",
                            "content": "CANARY-ALPHA-",
                        },
                        "finish_reason": "stop",
                    },
                ],
            },
        ),
        (
            "anthropic",
            {
                "id": "msg_cross_document",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": [
                    {"type": "text", "text": "CANARY-ALPHA-"},
                    {"type": "text", "text": "BETA"},
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
                                {"text": "CANARY-ALPHA-"},
                                {"text": "BETA"},
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
def test_converted_document_blocks_source_consumer_reconstruction_before_body_log(
    target_provider: ProviderType,
    upstream: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = "CANARY-ALPHA-BETA"
    body_log_state = BodyLogState(enabled=True)

    safe_response, _profile = asyncio.run(
        handle_non_streaming(
            _converted_route(target_provider),
            _provider("unrelated-provider-credential"),
            {"model": "test-model", "input": "hello"},
            transport=_StaticTransport(
                response=UpstreamResponse(
                    status_code=200,
                    body=upstream,
                    raw_content=json.dumps(upstream, separators=(",", ":")).encode(),
                )
            ),
        )
    )
    assert safe_response.status_code == 200
    assert _responses_output_text(json.loads(safe_response.body)) == token

    with caplog.at_level(logging.DEBUG, logger="codex-rosetta-gateway.body"):
        response, _profile = asyncio.run(
            handle_non_streaming(
                _converted_route(target_provider),
                _provider(token),
                {"model": "test-model", "input": "hello"},
                transport=_StaticTransport(
                    response=UpstreamResponse(
                        status_code=200,
                        body=upstream,
                        raw_content=json.dumps(
                            upstream, separators=(",", ":")
                        ).encode(),
                    )
                ),
                body_log_state=body_log_state,
            )
        )

    assert response.status_code == 502
    assert token.encode() not in response.body
    assert b"response blocked" in response.body
    assert not [
        record
        for record in caplog.records
        if record.name == "codex-rosetta-gateway.body"
        and record.getMessage().startswith("[UPSTREAM RESPONSE]")
    ]


def test_converted_document_preserves_credential_free_output_and_body_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    upstream = {
        "id": "chatcmpl-safe-document",
        "object": "chat.completion",
        "created": 123,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ordinary "},
                "finish_reason": "stop",
            },
            {
                "index": 1,
                "message": {"role": "assistant", "content": "answer"},
                "finish_reason": "stop",
            },
        ],
    }

    with caplog.at_level(logging.DEBUG, logger="codex-rosetta-gateway.body"):
        response, _profile = asyncio.run(
            handle_non_streaming(
                _converted_route(),
                _provider("CANARY-ALPHA-BETA"),
                {"model": "test-model", "input": "hello"},
                transport=_StaticTransport(
                    response=UpstreamResponse(
                        status_code=200,
                        body=upstream,
                        raw_content=json.dumps(
                            upstream, separators=(",", ":")
                        ).encode(),
                    )
                ),
                body_log_state=BodyLogState(enabled=True),
            )
        )

    document = json.loads(response.body)
    assert response.status_code == 200
    assert _responses_output_text(document) == "answerordinary "
    assert any(
        record.name == "codex-rosetta-gateway.body"
        and record.getMessage().startswith("[UPSTREAM RESPONSE]")
        for record in caplog.records
    )


def test_converted_document_drops_reconstructable_upstream_body_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    upstream = {
        "id": "chatcmpl-safe-output-unsafe-diagnostics",
        "object": "chat.completion",
        "created": 123,
        "model": "test-model",
        "diagnostic_fragments": ["CANARY-ALPHA-", "BETA"],
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ordinary answer"},
                "finish_reason": "stop",
            }
        ],
    }

    with caplog.at_level(logging.DEBUG, logger="codex-rosetta-gateway.body"):
        response, _profile = asyncio.run(
            handle_non_streaming(
                _converted_route(),
                _provider("CANARY-ALPHA-BETA"),
                {"model": "test-model", "input": "hello"},
                transport=_StaticTransport(
                    response=UpstreamResponse(
                        status_code=200,
                        body=upstream,
                        raw_content=json.dumps(
                            upstream, separators=(",", ":")
                        ).encode(),
                    )
                ),
                body_log_state=BodyLogState(enabled=True),
            )
        )

    assert response.status_code == 200
    assert _responses_output_text(json.loads(response.body)) == "ordinary answer"
    assert not [
        record
        for record in caplog.records
        if record.name == "codex-rosetta-gateway.body"
        and record.getMessage().startswith("[UPSTREAM RESPONSE]")
    ]


def test_passthrough_document_drops_reconstructable_body_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    upstream = {
        "id": "resp-safe-output-unsafe-diagnostics",
        "object": "response",
        "status": "completed",
        "output": [],
        "diagnostic_fragments": ["CANARY-ALPHA-", "BETA"],
    }

    with caplog.at_level(logging.DEBUG, logger="codex-rosetta-gateway.body"):
        response, _profile = asyncio.run(
            handle_non_streaming(
                _passthrough_route(),
                _provider("CANARY-ALPHA-BETA"),
                {"model": "test-model", "input": "hello"},
                transport=_StaticTransport(
                    response=UpstreamResponse(
                        status_code=200,
                        body=upstream,
                        raw_content=json.dumps(
                            upstream, separators=(",", ":")
                        ).encode(),
                    )
                ),
                body_log_state=BodyLogState(enabled=True),
            )
        )

    assert response.status_code == 200
    assert json.loads(response.body) == upstream
    assert not [
        record
        for record in caplog.records
        if record.name == "codex-rosetta-gateway.body"
        and record.getMessage().startswith("[UPSTREAM RESPONSE]")
    ]


def test_passthrough_document_preserves_safe_body_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    upstream = {
        "id": "resp-safe-diagnostics",
        "object": "response",
        "status": "completed",
        "output": [],
        "diagnostic": "ordinary detail",
    }

    with caplog.at_level(logging.DEBUG, logger="codex-rosetta-gateway.body"):
        response, _profile = asyncio.run(
            handle_non_streaming(
                _passthrough_route(),
                _provider("CANARY-ALPHA-BETA"),
                {"model": "test-model", "input": "hello"},
                transport=_StaticTransport(
                    response=UpstreamResponse(
                        status_code=200,
                        body=upstream,
                        raw_content=json.dumps(
                            upstream, separators=(",", ":")
                        ).encode(),
                    )
                ),
                body_log_state=BodyLogState(enabled=True),
            )
        )

    assert response.status_code == 200
    assert any(
        record.name == "codex-rosetta-gateway.body"
        and record.getMessage().startswith("[UPSTREAM RESPONSE]")
        for record in caplog.records
    )


def test_converted_document_uses_global_body_log_token_inventory(
    caplog: pytest.LogCaptureFixture,
) -> None:
    upstream = {
        "id": "chatcmpl-global-diagnostic",
        "object": "chat.completion",
        "created": 123,
        "model": "test-model",
        "diagnostic_fragments": ["GLOBAL-ALPHA-", "BETA"],
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ordinary answer"},
                "finish_reason": "stop",
            }
        ],
    }

    with caplog.at_level(logging.DEBUG, logger="codex-rosetta-gateway.body"):
        response, _profile = asyncio.run(
            handle_non_streaming(
                _converted_route(),
                _provider("ACTIVE-PROVIDER-TOKEN"),
                {"model": "test-model", "input": "hello"},
                transport=_StaticTransport(
                    response=UpstreamResponse(
                        status_code=200,
                        body=upstream,
                        raw_content=json.dumps(
                            upstream, separators=(",", ":")
                        ).encode(),
                    )
                ),
                body_log_state=BodyLogState(
                    enabled=True,
                    token_values={"GLOBAL-ALPHA-BETA"},
                ),
            )
        )

    assert response.status_code == 200
    assert _responses_output_text(json.loads(response.body)) == "ordinary answer"
    assert not [
        record
        for record in caplog.records
        if record.name == "codex-rosetta-gateway.body"
        and record.getMessage().startswith("[UPSTREAM RESPONSE]")
    ]


def test_passthrough_raw_stream_drops_reconstructable_response_trace(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "raw-diagnostic-collision.jsonl"
    trace_state = StreamTraceState(
        StreamTraceConfig(enabled=True, path=str(trace_path)),
        token_values={"CANARY-ALPHA-BETA"},
    )
    frames = [
        b'data: {"type":"response.created","diagnostic":"CANARY-ALPHA-"}\n\n',
        b'data: {"type":"response.completed","diagnostic":"BETA"}\n\n',
    ]

    async def run() -> bytes:
        response, _profile = await handle_streaming(
            _passthrough_route(),
            _provider("ACTIVE-PROVIDER-TOKEN"),
            {"model": "test-model", "input": "hello", "stream": True},
            transport=_StaticTransport(stream=_StaticStream(raw_chunks=frames)),
            extra_headers={"x-request-id": "req-raw-diagnostic"},
            entry_id="log-raw-diagnostic",
            stream_trace_state=trace_state,
        )
        assert isinstance(response, StreamingResponse)
        return b"".join([cast(bytes, chunk) async for chunk in response._generator])

    emitted = asyncio.run(run())
    records = _trace_records(trace_path)

    assert emitted == b"".join(frames)
    assert [record["stage"] for record in records] == [
        "stream_start",
        "raw_passthrough_request",
        "stream_complete",
    ]


def test_passthrough_raw_stream_preserves_safe_response_trace(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "raw-safe-diagnostics.jsonl"
    trace_state = StreamTraceState(
        StreamTraceConfig(enabled=True, path=str(trace_path)),
        token_values={"CANARY-ALPHA-BETA"},
    )
    frames = [
        b'data: {"type":"response.created","diagnostic":"ordinary"}\n\n',
        b'data: {"type":"response.completed","diagnostic":"detail"}\n\n',
    ]

    async def run() -> bytes:
        response, _profile = await handle_streaming(
            _passthrough_route(),
            _provider("CANARY-ALPHA-BETA"),
            {"model": "test-model", "input": "hello", "stream": True},
            transport=_StaticTransport(stream=_StaticStream(raw_chunks=frames)),
            extra_headers={"x-request-id": "req-raw-safe-diagnostic"},
            entry_id="log-raw-safe-diagnostic",
            stream_trace_state=trace_state,
        )
        assert isinstance(response, StreamingResponse)
        return b"".join([cast(bytes, chunk) async for chunk in response._generator])

    emitted = asyncio.run(run())
    records = _trace_records(trace_path)

    assert emitted == b"".join(frames)
    assert [record["stage"] for record in records] == [
        "stream_start",
        "raw_passthrough_request",
        "raw_passthrough_chunk",
        "raw_passthrough_chunk",
        "stream_complete",
    ]


def test_passthrough_raw_stream_blocks_cross_chunk_collision_and_trace(
    tmp_path,
) -> None:
    token = "raw-passthrough-secret"
    payload = (
        b'event: response.output_text.delta\ndata: {"type":"response.output_text.delta",'
        b'"delta":"before ' + token.encode() + b' after"}\n\n'
    )
    start = payload.index(token.encode()) + 5
    trace_path = tmp_path / "raw-trace.jsonl"
    trace_state = StreamTraceState(
        StreamTraceConfig(enabled=True, path=str(trace_path)), token_values=()
    )

    async def run() -> bytes:
        response, _profile = await handle_streaming(
            _passthrough_route(),
            _provider(token),
            {"model": "test-model", "input": "hello", "stream": True},
            transport=_StaticTransport(
                stream=_StaticStream(raw_chunks=[payload[:start], payload[start:]])
            ),
            extra_headers={"x-request-id": "req-redaction"},
            entry_id="log-redaction",
            stream_trace_state=trace_state,
        )
        assert isinstance(response, StreamingResponse)
        chunks: list[bytes] = []
        async for chunk in response._generator:
            assert isinstance(chunk, bytes)
            chunks.append(chunk)
        return b"".join(chunks)

    emitted = asyncio.run(run())

    assert token.encode() not in emitted
    assert b"[REDACTED]" not in emitted
    assert emitted.startswith(b"event: error\n")
    assert b"response blocked" in emitted
    assert token not in trace_path.read_text(encoding="utf-8")


def test_converted_stream_blocks_model_output_before_sse_and_trace(tmp_path) -> None:
    token = "converted-stream-secret"
    trace_path = tmp_path / "converted-trace.jsonl"
    trace_state = StreamTraceState(
        StreamTraceConfig(enabled=True, path=str(trace_path)), token_values=()
    )
    events = [
        {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 123,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": f"before {token} after",
                    },
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
            extra_headers={"x-request-id": "req-converted-redaction"},
            entry_id="log-converted-redaction",
            stream_trace_state=trace_state,
        )
        assert isinstance(response, StreamingResponse)
        chunks: list[str] = []
        async for chunk in response._generator:
            assert isinstance(chunk, str)
            chunks.append(chunk)
        return "".join(chunks)

    emitted = asyncio.run(run())

    assert token not in emitted
    assert "[REDACTED]" not in emitted
    assert emitted.startswith("event: error\n")
    assert "response blocked" in emitted
    assert token not in trace_path.read_text(encoding="utf-8")


def _trace_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _joined_trace_fragments(
    records: list[dict[str, Any]],
    *,
    stages: set[str],
) -> str:
    fragments: list[str] = []
    for record in records:
        if record.get("stage") not in stages:
            continue
        encoded = json.dumps(record.get("data"), ensure_ascii=False)
        for fragment in ("CANARY-ALPHA-", "BETA"):
            if fragment in encoded:
                fragments.append(fragment)
    return "".join(fragments)


def test_converted_stream_discards_all_unproven_response_diagnostics(
    tmp_path: Path,
) -> None:
    token = "CANARY-ALPHA-BETA"
    trace_path = tmp_path / "deferred-collision.jsonl"
    trace_state = StreamTraceState(
        StreamTraceConfig(enabled=True, path=str(trace_path)), token_values=()
    )
    events = [
        {"choices": [{"index": 0, "delta": {"content": "CANARY-ALPHA-"}}]},
        {"choices": [{"index": 1, "delta": {"content": "BETA"}}]},
    ]

    async def run() -> str:
        response, _profile = await handle_streaming(
            _converted_route(),
            _provider(token),
            {"model": "test-model", "input": "hello", "stream": True},
            transport=_StaticTransport(stream=_StaticStream(events=events)),
            extra_headers={"x-request-id": "req-deferred-collision"},
            entry_id="log-deferred-collision",
            stream_trace_state=trace_state,
        )
        assert isinstance(response, StreamingResponse)
        return "".join([cast(str, chunk) async for chunk in response._generator])

    emitted = asyncio.run(run())
    records = _trace_records(trace_path)
    response_stages = {
        "upstream_chunk",
        "ir_event",
        "source_event",
        "downstream_sse",
    }

    assert token not in emitted
    assert _joined_trace_fragments(records, stages=response_stages) == ""
    assert not response_stages.intersection(record["stage"] for record in records)
    assert records[-1]["stage"] == "stream_complete"
    assert records[-1]["data"]["stream_outcome"] == "error"


def test_converted_stream_releases_safe_response_diagnostics_in_order(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "deferred-safe.jsonl"
    trace_state = StreamTraceState(
        StreamTraceConfig(enabled=True, path=str(trace_path)), token_values=()
    )
    events = [
        {"choices": [{"index": 0, "delta": {"content": "ordinary "}}]},
        {"choices": [{"index": 0, "delta": {"content": "answer"}}]},
    ]

    async def run() -> None:
        response, _profile = await handle_streaming(
            _converted_route(),
            _provider("CANARY-ALPHA-BETA"),
            {"model": "test-model", "input": "hello", "stream": True},
            transport=_StaticTransport(stream=_StaticStream(events=events)),
            extra_headers={"x-request-id": "req-deferred-safe"},
            entry_id="log-deferred-safe",
            stream_trace_state=trace_state,
        )
        assert isinstance(response, StreamingResponse)
        _ = [chunk async for chunk in response._generator]

    asyncio.run(run())
    records = _trace_records(trace_path)
    stages = [record["stage"] for record in records]

    assert stages[:3] == ["stream_start", "source_request", "target_request"]
    assert stages.count("upstream_chunk") == 2
    assert stages.count("source_event") >= 2
    assert stages.count("downstream_sse") >= 2
    assert stages[-1] == "stream_complete"
    assert stages.index("upstream_chunk") < stages.index("source_event")


def test_converted_stream_drops_target_only_reconstructable_diagnostics(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "target-only-diagnostic-collision.jsonl"
    trace_state = StreamTraceState(
        StreamTraceConfig(enabled=True, path=str(trace_path)), token_values=()
    )
    events = [
        {
            "diagnostic": "CANARY-ALPHA-",
            "choices": [{"index": 0, "delta": {"content": "ordinary "}}],
        },
        {
            "diagnostic": "BETA",
            "choices": [{"index": 0, "delta": {"content": "answer"}}],
        },
    ]

    async def run() -> str:
        response, _profile = await handle_streaming(
            _converted_route(),
            _provider("CANARY-ALPHA-BETA"),
            {"model": "test-model", "input": "hello", "stream": True},
            transport=_StaticTransport(stream=_StaticStream(events=events)),
            extra_headers={"x-request-id": "req-target-only-diagnostic"},
            entry_id="log-target-only-diagnostic",
            stream_trace_state=trace_state,
        )
        assert isinstance(response, StreamingResponse)
        return "".join([cast(str, chunk) async for chunk in response._generator])

    emitted = asyncio.run(run())
    records = _trace_records(trace_path)
    response_stages = {
        "upstream_chunk",
        "ir_event",
        "source_event",
        "downstream_sse",
    }

    assert "ordinary answer" == "".join(
        event.get("delta", "")
        for line in emitted.splitlines()
        if line.startswith("data: {")
        for event in [json.loads(line[6:])]
        if event.get("type") == "response.output_text.delta"
    )
    assert not response_stages.intersection(record["stage"] for record in records)
    assert records[-1]["stage"] == "stream_complete"
    assert records[-1]["data"]["stream_outcome"] == "completed"


@pytest.mark.parametrize(
    ("target_provider", "events"),
    [
        (
            "openai_chat",
            [
                {
                    "id": "chatcmpl-cross-format",
                    "object": "chat.completion.chunk",
                    "created": 123,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": "CANARY-ALPHA-",
                            },
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chatcmpl-cross-format",
                    "object": "chat.completion.chunk",
                    "created": 123,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 1,
                            "delta": {"content": "BETA"},
                            "finish_reason": None,
                        }
                    ],
                },
            ],
        ),
        (
            "anthropic",
            [
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_cross_format",
                        "type": "message",
                        "role": "assistant",
                        "model": "test-model",
                        "content": [],
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "CANARY-ALPHA-"},
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "text_delta", "text": "BETA"},
                },
            ],
        ),
        (
            "google",
            [
                {
                    "response_id": "response_cross_format",
                    "model_version": "test-model",
                    "candidates": [
                        {
                            "index": 0,
                            "content": {
                                "role": "model",
                                "parts": [
                                    {"text": "CANARY-ALPHA-"},
                                    {"text": "BETA"},
                                ],
                            },
                        }
                    ],
                }
            ],
        ),
    ],
)
def test_converted_stream_blocks_cross_format_consumer_reconstruction(
    target_provider: ProviderType,
    events: list[dict[str, Any]],
) -> None:
    token = "CANARY-ALPHA-BETA"

    async def run() -> str:
        response, _profile = await handle_streaming(
            _converted_route(target_provider),
            _provider(token),
            {"model": "test-model", "input": "hello", "stream": True},
            transport=_StaticTransport(stream=_StaticStream(events=events)),
        )
        assert isinstance(response, StreamingResponse)
        chunks: list[str] = []
        async for chunk in response._generator:
            assert isinstance(chunk, str)
            chunks.append(chunk)
        return "".join(chunks)

    emitted = asyncio.run(run())
    downstream_text = "".join(
        event.get("delta", "")
        for line in emitted.splitlines()
        if line.startswith("data: {")
        for event in [json.loads(line[6:])]
        if event.get("type") == "response.output_text.delta"
    )

    assert token not in downstream_text
    assert "[REDACTED]" not in emitted
    assert "event: error\n" in emitted
    assert "response blocked" in emitted


@pytest.mark.parametrize(
    ("target_provider", "events"),
    [
        (
            "openai_chat",
            [
                {
                    "choices": [
                        {"index": 0, "delta": {"reasoning_content": "CANARY-ALPHA-"}}
                    ]
                },
                {"choices": [{"index": 1, "delta": {"reasoning_content": "BETA"}}]},
            ],
        ),
        (
            "anthropic",
            [
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "thinking_delta", "thinking": "CANARY-ALPHA-"},
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "thinking_delta", "thinking": "BETA"},
                },
            ],
        ),
        (
            "google",
            [
                {
                    "candidates": [
                        {
                            "index": 0,
                            "content": {
                                "parts": [
                                    {"text": "CANARY-ALPHA-", "thought": True},
                                    {"text": "BETA", "thought": True},
                                ]
                            },
                        }
                    ]
                }
            ],
        ),
    ],
)
def test_converted_stream_blocks_cross_format_reasoning_reconstruction(
    target_provider: ProviderType,
    events: list[dict[str, Any]],
) -> None:
    token = "CANARY-ALPHA-BETA"

    async def run() -> str:
        response, _profile = await handle_streaming(
            _converted_route(target_provider),
            _provider(token),
            {"model": "test-model", "input": "hello", "stream": True},
            transport=_StaticTransport(stream=_StaticStream(events=events)),
        )
        assert isinstance(response, StreamingResponse)
        chunks: list[str] = []
        async for chunk in response._generator:
            assert isinstance(chunk, str)
            chunks.append(chunk)
        return "".join(chunks)

    emitted = asyncio.run(run())
    downstream_reasoning = "".join(
        event.get("delta", "")
        for line in emitted.splitlines()
        if line.startswith("data: {")
        for event in [json.loads(line[6:])]
        if event.get("type")
        in {
            "response.reasoning_summary_text.delta",
            "response.reasoning_text.delta",
        }
    )

    assert token not in downstream_reasoning
    assert "[REDACTED]" not in emitted
    assert "event: error\n" in emitted
    assert "response blocked" in emitted


class _RecordingOutputGate:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.finish_count = 0

    def inspect_stream_event(self, event: dict[str, Any]) -> None:
        del event
        if self.fail:
            raise RuntimeError("output gate test failure")

    def diagnostics_are_safe(self, values: tuple[Any, ...]) -> bool:
        del values
        return True

    def finish(self) -> None:
        self.finish_count += 1


class _RecordingRequestLog:
    def __init__(self) -> None:
        self.profile_updates: list[tuple[str, dict[str, Any]]] = []

    def update_profile(self, entry_id: str, profile: dict[str, Any]) -> None:
        self.profile_updates.append((entry_id, profile))


class _ExplodingDiagnosticRedactor:
    def redact(self, value: Any) -> Any:
        return value

    def contains_ordered_fragments(self, values: tuple[Any, ...]) -> bool:
        del values
        raise RuntimeError("diagnostic matcher failed")


class _IdentityStreamProcessor:
    def process_chunk(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        return [chunk]


class _FailingStreamProcessor:
    def __init__(self, message: str = "conversion failed") -> None:
        self.message = message

    def process_chunk(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        del chunk
        raise RuntimeError(self.message)


def _instrumented_terminal_failure(
    tmp_path: Path,
    *,
    error_text: str,
    active_token: str,
    global_tokens: set[str],
    sqlite: bool,
) -> tuple[
    Exception,
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
]:
    persistence = (
        PersistenceManager(
            str(tmp_path / "persistence"),
            token_values=global_tokens,
        )
        if sqlite
        else None
    )
    try:
        request_log = RequestLog(persistence=persistence)
        metrics = MetricsCollector()
        metrics.update_token_values(global_tokens)
        metrics.active_streams = 1
        request = SimpleNamespace(
            app=SimpleNamespace(metrics=metrics, request_log=request_log),
            client_addr=("127.0.0.1", 12345),
        )
        trace_path = tmp_path / "terminal-diagnostics.jsonl"
        trace_state = StreamTraceState(
            StreamTraceConfig(enabled=True, path=str(trace_path)),
            token_values=global_tokens,
        )
        trace = trace_state.create_logger(
            request_id="req-terminal-diagnostics",
            request_log_id="entry-terminal-diagnostics",
            model="test-model",
            source_provider="openai_responses",
            target_provider="openai_chat",
            provider_name="test-provider",
        )
        assert trace is not None
        trace.log("stream_start", {"test": "terminal diagnostics"})
        trace.defer_response_diagnostics()
        global_state = UpstreamErrorLogState(global_tokens)
        gate = ProviderCredentialOutputGate(
            _provider(active_token),
            "openai_responses",
            global_diagnostic_safety_check=global_state.diagnostics_are_safe,
        )
        response = StreamingResponse(
            _stream_event_generator(
                source_provider="openai_responses",
                stream=_StaticStream(
                    events=[{"type": "response.created", "response": {}}]
                ),
                processor=_FailingStreamProcessor(error_text),
                model="test-model",
                format_sse=lambda event: json.dumps(event),
                entry_id="entry-terminal-diagnostics",
                request_log=request_log,
                trace=trace,
                credential_output_gate=gate,
            ),
            content_type="text/event-stream",
        )
        app_module._instrument_stream_response(
            request,
            response,
            entry_id="entry-terminal-diagnostics",
            request_id="req-terminal-diagnostics",
            model="test-model",
            source_provider="openai_responses",
            target_provider="openai_chat",
            provider_name="test-provider",
            profile={"stream_connect_ms": 1.0},
            profiler=None,
            started_at=time.monotonic(),
        )

        async def consume() -> Exception:
            try:
                await response._generator.__anext__()
            except Exception as exc:
                return exc
            raise AssertionError("expected stream failure")

        caught = asyncio.run(consume())
        records = _trace_records(trace_path)
        entry = request_log.get_entry("entry-terminal-diagnostics")
        assert entry is not None
        health = metrics.provider_health_snapshot()["test-provider"]
        return caught, records, entry, health
    finally:
        if persistence is not None:
            persistence.close()


@pytest.mark.parametrize("sqlite", [False, True], ids=["memory", "sqlite"])
@pytest.mark.parametrize(
    ("active_token", "global_tokens"),
    [
        (
            "CANARY-ALPHA-BETA",
            {"CANARY-ALPHA-BETA"},
        ),
        (
            "ACTIVE-PROVIDER-CREDENTIAL",
            {"ACTIVE-PROVIDER-CREDENTIAL", "CANARY-ALPHA-BETA"},
        ),
    ],
    ids=["active-provider", "inactive-global-sibling"],
)
def test_unsafe_terminal_error_is_stable_across_all_persisted_sinks(
    tmp_path: Path,
    sqlite: bool,
    active_token: str,
    global_tokens: set[str],
) -> None:
    token = "CANARY-ALPHA-BETA"
    raw_error = '{"first":"CANARY-ALPHA-","second":"BETA"}'
    caught, records, entry, health = _instrumented_terminal_failure(
        tmp_path,
        error_text=raw_error,
        active_token=active_token,
        global_tokens=global_tokens,
        sqlite=sqlite,
    )

    stable_error = "Upstream stream failed; unsafe error details blocked"
    assert isinstance(caught, UpstreamCredentialCollisionError)
    assert str(caught) == stable_error
    assert caught.__cause__ is None
    assert caught.__context__ is None
    assert [record["stage"] for record in records] == [
        "stream_start",
        "stream_complete",
    ]
    assert records[-1]["data"]["stream_complete"] is False
    assert records[-1]["data"]["stream_error"] == stable_error
    assert entry["status_code"] == 502
    assert entry["error_detail"] == stable_error
    assert entry["profile"]["stream_complete"] is False
    assert entry["profile"]["stream_error"] == stable_error
    assert health["last_error"] == stable_error

    persisted_values = (records, entry, health)
    assert not SecretRedactor({token}).contains_ordered_fragments(persisted_values)
    assert raw_error not in json.dumps(persisted_values, ensure_ascii=False)


def test_ordinary_terminal_error_detail_remains_available(tmp_path: Path) -> None:
    ordinary_error = "ordinary conversion failure"
    caught, records, entry, health = _instrumented_terminal_failure(
        tmp_path,
        error_text=ordinary_error,
        active_token="CANARY-ALPHA-BETA",
        global_tokens={"CANARY-ALPHA-BETA"},
        sqlite=False,
    )

    assert type(caught) is RuntimeError
    assert str(caught) == ordinary_error
    assert records[-1]["data"]["stream_error"] == ordinary_error
    assert entry["error_detail"] == ordinary_error
    assert entry["profile"]["stream_error"] == ordinary_error
    assert health["last_error"] == ordinary_error


@pytest.mark.parametrize("outcome", ["complete", "failure", "aclose"])
def test_final_output_gate_finishes_for_every_stream_terminal_path(
    outcome: str,
) -> None:
    gate = _RecordingOutputGate(fail=outcome == "failure")
    stream = _StaticStream(events=[{"type": "response.created", "response": {}}])

    async def run() -> None:
        generator = cast(
            AsyncGenerator[str],
            _stream_event_generator(
                source_provider="openai_responses",
                stream=stream,
                processor=_IdentityStreamProcessor(),
                model="test-model",
                format_sse=lambda event: json.dumps(event),
                credential_output_gate=cast(ProviderCredentialOutputGate, gate),
            ),
        )
        if outcome == "aclose":
            await generator.__anext__()
            await generator.aclose()
            return
        if outcome == "failure":
            with pytest.raises(RuntimeError, match="output gate test failure"):
                _ = [chunk async for chunk in generator]
            return
        _ = [chunk async for chunk in generator]

    asyncio.run(run())

    assert gate.finish_count == 1


def test_finalizer_cleans_gate_and_pending_trace_when_diagnostic_finish_fails(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "diagnostic-finish-failure.jsonl"
    trace_state = StreamTraceState(
        StreamTraceConfig(enabled=True, path=str(trace_path)), token_values=()
    )
    trace = trace_state.create_logger(
        request_id="req-diagnostic-failure",
        request_log_id="log-diagnostic-failure",
        model="test-model",
        source_provider="openai_responses",
        target_provider="openai_chat",
        provider_name="test-provider",
    )
    assert trace is not None
    trace.defer_response_diagnostics()
    trace.log("upstream_chunk", {"content": "unproven response"})
    trace._redactor = cast(Any, _ExplodingDiagnosticRedactor())
    gate = _RecordingOutputGate()
    request_log = _RecordingRequestLog()

    with pytest.raises(RuntimeError, match="diagnostic matcher failed"):
        _finalize_response_stream(
            trace=trace,
            credential_output_gate=cast(ProviderCredentialOutputGate, gate),
            entry_id="entry-diagnostic-failure",
            request_log=request_log,
            t0=0.0,
            chunk_count=1,
            terminal_state=_StreamTerminalState(outcome="completed", error=None),
            ttfb_ms=1.0,
        )

    assert gate.finish_count == 1
    assert trace._defer_response is False
    assert trace._pending_response_lines == []
    assert trace._pending_response_values == []
    assert request_log.profile_updates[0][0] == "entry-diagnostic-failure"
    assert request_log.profile_updates[0][1]["stream_complete"] is True
    records = _trace_records(trace_path)
    assert [record["stage"] for record in records] == ["stream_complete"]


@pytest.mark.parametrize("outcome", ["conversion_error", "aclose"])
def test_unproven_stream_diagnostics_are_discarded_on_abnormal_terminal_path(
    tmp_path: Path,
    outcome: str,
) -> None:
    trace_path = tmp_path / f"abnormal-{outcome}.jsonl"
    trace_state = StreamTraceState(
        StreamTraceConfig(enabled=True, path=str(trace_path)), token_values=()
    )
    trace = trace_state.create_logger(
        request_id="req-abnormal",
        request_log_id="log-abnormal",
        model="test-model",
        source_provider="openai_responses",
        target_provider="openai_chat",
        provider_name="test-provider",
    )
    assert trace is not None
    trace.log("stream_start", {"outcome": outcome})
    trace.defer_response_diagnostics()
    processor: Any = (
        _FailingStreamProcessor()
        if outcome == "conversion_error"
        else _IdentityStreamProcessor()
    )

    async def run() -> None:
        generator = cast(
            AsyncGenerator[str],
            _stream_event_generator(
                source_provider="openai_responses",
                stream=_StaticStream(
                    events=[
                        {
                            "type": "response.output_text.delta",
                            "delta": "unproven response fragment",
                        }
                    ]
                ),
                processor=processor,
                model="test-model",
                format_sse=lambda event: json.dumps(event),
                trace=trace,
                credential_output_gate=ProviderCredentialOutputGate(
                    _provider("CANARY-ALPHA-BETA"),
                    "openai_responses",
                ),
            ),
        )
        if outcome == "conversion_error":
            with pytest.raises(RuntimeError, match="conversion failed"):
                _ = [chunk async for chunk in generator]
            return
        await generator.__anext__()
        await generator.aclose()

    asyncio.run(run())

    records = _trace_records(trace_path)
    assert [record["stage"] for record in records] == [
        "stream_start",
        "stream_complete",
    ]
    assert records[-1]["data"]["stream_outcome"] in {"error", "cancelled"}


@pytest.mark.parametrize("converted", [False, True])
def test_streaming_http_error_collision_is_blocked_for_passthrough_and_conversion(
    tmp_path,
    converted: bool,
) -> None:
    token = "streaming-http-error-secret"
    trace_path = tmp_path / f"http-error-{converted}.jsonl"
    trace_state = StreamTraceState(
        StreamTraceConfig(enabled=True, path=str(trace_path)), token_values=()
    )
    route = _converted_route() if converted else _passthrough_route()

    response, _profile = asyncio.run(
        handle_streaming(
            route,
            _provider(token),
            {"model": "test-model", "input": "hello", "stream": True},
            transport=_StaticTransport(
                stream=_StaticStream(
                    status_code=401,
                    error=f'{{"error":{{"message":"failed with {token}"}}}}',
                )
            ),
            extra_headers={"x-request-id": f"req-http-error-{converted}"},
            entry_id=f"log-http-error-{converted}",
            stream_trace_state=trace_state,
        )
    )

    assert isinstance(response, Response)
    assert response.status_code == 401
    assert token.encode() not in response.body
    assert b"response blocked" in response.body
    if trace_path.exists():
        assert token not in trace_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("streaming", [False, True])
def test_proxy_redacts_transport_failure_before_client_and_diagnostics(
    tmp_path,
    streaming: bool,
) -> None:
    token = "provider-transport-exception-secret"
    failure = UpstreamConnectionError(f"connection reflected {token}")
    trace_path = tmp_path / f"failure-{streaming}.jsonl"
    trace_state = StreamTraceState(
        StreamTraceConfig(enabled=True, path=str(trace_path)), token_values=()
    )

    if streaming:
        response, _profile = asyncio.run(
            handle_streaming(
                _passthrough_route(),
                _provider(token),
                {"model": "test-model", "input": "hello", "stream": True},
                transport=_StaticTransport(failure=failure),
                extra_headers={"x-request-id": "req-failure"},
                entry_id="log-failure",
                stream_trace_state=trace_state,
            )
        )
    else:
        response, _profile = asyncio.run(
            handle_non_streaming(
                _passthrough_route(),
                _provider(token),
                {"model": "test-model", "input": "hello"},
                transport=_StaticTransport(failure=failure),
            )
        )

    assert isinstance(response, Response)
    assert response.status_code == 502
    assert token.encode() not in response.body
    if trace_path.exists():
        assert token not in trace_path.read_text(encoding="utf-8")
