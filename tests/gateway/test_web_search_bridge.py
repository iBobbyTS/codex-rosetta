"""Tests for the Codex web_search bridge on Responses-to-Chat routes."""

from __future__ import annotations

import asyncio
import json
import traceback
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest

import codex_rosetta.gateway.web_search as web_search_module
from codex_rosetta._vendor.httpserver import StreamingResponse
from codex_rosetta.gateway.proxy import handle_streaming
from codex_rosetta.gateway.tool_profiles import tool_profile_contract
from codex_rosetta.gateway.transport._base import (
    UpstreamContentEncodingError,
    UpstreamCredentialCollisionError,
    UpstreamResponseContractError,
    UpstreamResponseTooLargeError,
    UpstreamStream,
)
from codex_rosetta.gateway.transport.http.transport import BoundedHttpResponse
from codex_rosetta.gateway.web_search import (
    WEB_SEARCH_PROFILE_ITEM_ID,
    PendingWebSearchCall,
    TavilyCredentialCollisionError,
    TavilyHTTPClient,
    TavilyRequestError,
    WebSearchRuntime,
    WebSearchSettings,
    profile_search_config,
)
from codex_rosetta.routing import ResolvedRoute


@pytest.mark.parametrize(
    ("status_code", "content", "category"),
    [
        (302, b'{"private":"redirect body"}', "http_error"),
        (432, b'{"private":"quota body"}', "http_error"),
        (433, b'{"private":"quota body"}', "http_error"),
        (400, b'{"private":"request body"}', "http_error"),
        (422, b'{"private":"request body"}', "http_error"),
        (503, b'{"private":"server body"}', "http_error"),
        (200, b"not-json", "invalid_json"),
        (200, b"[]", "invalid_shape"),
        (200, b"{}", "invalid_shape"),
    ],
)
def test_tavily_typed_failures_are_bounded_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    content: bytes,
    category: str,
) -> None:
    token = "secret-" + "key"

    async def fake_request(*args: Any, **kwargs: Any) -> BoundedHttpResponse:
        del args, kwargs
        return BoundedHttpResponse(status_code, {}, content)

    monkeypatch.setattr(web_search_module, "request_bounded_response", fake_request)
    with pytest.raises(TavilyRequestError) as caught:
        asyncio.run(
            TavilyHTTPClient(token).search("query", settings=WebSearchSettings())
        )

    assert caught.value.category == category
    assert caught.value.status_code == (status_code if status_code != 200 else None)
    rendered = "".join(traceback.format_exception(caught.value))
    assert content.decode() not in rendered
    assert token not in rendered
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_tavily_accepts_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_request(*args: Any, **kwargs: Any) -> BoundedHttpResponse:
        del args, kwargs
        return BoundedHttpResponse(200, {}, b'{"results":[]}')

    monkeypatch.setattr(web_search_module, "request_bounded_response", fake_request)
    result = asyncio.run(
        TavilyHTTPClient("secret-key").search("query", settings=WebSearchSettings())
    )
    assert result == {"results": []}


@pytest.mark.parametrize("failure_site", ["request", "client_exit", "response_json"])
def test_tavily_request_boundary_propagates_memory_error(
    monkeypatch: pytest.MonkeyPatch,
    failure_site: str,
) -> None:
    failure = MemoryError(f"memory failure in {failure_site}")

    class FakeAsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: Any) -> None:
            del args
            if failure_site == "client_exit":
                raise failure

    async def fake_request(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        if failure_site == "request":
            raise failure
        if failure_site == "response_json":

            class MemoryResponse:
                status_code = 200
                content = b'{"results":[]}'

                def json(self):
                    raise failure

            return MemoryResponse()
        return BoundedHttpResponse(200, {}, b'{"results":[]}')

    monkeypatch.setattr(web_search_module, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(web_search_module, "request_bounded_response", fake_request)

    with pytest.raises(MemoryError) as caught:
        asyncio.run(
            TavilyHTTPClient("secret-key").search("query", settings=WebSearchSettings())
        )

    assert caught.value is failure


@pytest.mark.parametrize(
    "failure",
    [
        UpstreamResponseTooLargeError("bounded response overflow"),
        UpstreamContentEncodingError("compressed response blocked"),
        UpstreamCredentialCollisionError("credential collision blocked"),
        UpstreamResponseContractError("response contract blocked"),
        MemoryError("allocation failed"),
    ],
)
def test_hosted_runtime_propagates_transport_safety_without_failed_tool_result(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    async def fake_request(*args: Any, **kwargs: Any) -> BoundedHttpResponse:
        del args, kwargs
        raise failure

    monkeypatch.setattr(web_search_module, "request_bounded_response", fake_request)
    runtime = WebSearchRuntime(
        client=TavilyHTTPClient("secret-key"),
        settings=WebSearchSettings(),
    )
    call = PendingWebSearchCall("call-1", "query", {})

    with pytest.raises(type(failure)) as caught:
        asyncio.run(runtime.execute(call))

    assert caught.value is failure


def test_hosted_runtime_propagates_tavily_credential_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "reflected-tavily-secret"

    async def fake_request(*args: Any, **kwargs: Any) -> BoundedHttpResponse:
        del args, kwargs
        return BoundedHttpResponse(
            200,
            {},
            f'{{"results":[{{"content":"{token}"}}]}}'.encode(),
        )

    monkeypatch.setattr(web_search_module, "request_bounded_response", fake_request)
    runtime = WebSearchRuntime(
        client=TavilyHTTPClient(token),
        settings=WebSearchSettings(),
    )

    with pytest.raises(TavilyCredentialCollisionError) as caught:
        asyncio.run(runtime.execute(PendingWebSearchCall("call-1", "query", {})))

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_tavily_client_exit_failure_is_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "client-exit-secret"

    class FailingAsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: Any) -> None:
            del args
            raise RuntimeError(secret)

    async def fake_request(*args: Any, **kwargs: Any) -> BoundedHttpResponse:
        del args, kwargs
        return BoundedHttpResponse(200, {}, b'{"results":[]}')

    monkeypatch.setattr(web_search_module, "AsyncClient", FailingAsyncClient)
    monkeypatch.setattr(web_search_module, "request_bounded_response", fake_request)

    with pytest.raises(TavilyRequestError) as caught:
        asyncio.run(
            TavilyHTTPClient("secret-key").search("query", settings=WebSearchSettings())
        )

    assert caught.value.category == "connection_error"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in "".join(traceback.format_exception(caught.value))


class _ChatStream(UpstreamStream):
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.status_code = 200
        self._chunks = chunks
        self.closed = False

    async def read_error(self) -> str:
        return ""

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        for chunk in self._chunks:
            yield chunk

    async def close(self) -> None:
        self.closed = True


class _FakeTavilyClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, WebSearchSettings]] = []

    async def search(
        self,
        query: str,
        *,
        settings: WebSearchSettings,
    ) -> dict[str, Any]:
        self.calls.append((query, settings))
        return {
            "answer": "Codex web search is enabled through a Responses web_search tool.",
            "request_id": "tvly-test",
            "response_time": 0.12,
            "results": [
                {
                    "title": "Codex Web Search Docs",
                    "url": "https://example.com/codex-web-search",
                    "content": "Codex can display native web search activity.",
                    "score": 0.91,
                }
            ],
        }


def _route(*, search_token: str = "tvly-test") -> ResolvedRoute:
    tool_profile = dict(tool_profile_contract()["builtin"])
    tool_profile["hosted.web_search"] = "modified"
    return ResolvedRoute(
        source_provider="openai_responses",
        target_provider="openai_chat",
        provider_name="test-provider",
        upstream_model="deepseek-v4-flash",
        tool_profile=tool_profile,
        tool_profile_inputs={
            "hosted.web_search": {
                "provider": "tavily",
                "token": search_token,
            }
        },
    )


def _provider_info() -> MagicMock:
    info = MagicMock()
    info.base_url = "https://api.example.test"
    return info


def test_web_search_runtime_config_comes_from_profile_card() -> None:
    assert profile_search_config(_route(), WEB_SEARCH_PROFILE_ITEM_ID) == {
        "provider": "tavily",
        "tavily_api_key": "tvly-test",
    }
    assert profile_search_config(
        _route(search_token=""), WEB_SEARCH_PROFILE_ITEM_ID
    ) == {"provider": "tavily", "tavily_api_key": ""}


def _tool_call_chunk() -> dict[str, Any]:
    return {
        "id": "chatcmpl-search",
        "object": "chat.completion.chunk",
        "created": 123,
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_web_search",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps(
                                    {"query": "Codex native web search UX"}
                                ),
                            },
                        }
                    ]
                },
                "finish_reason": None,
            }
        ],
    }


def _finish_chunk(reason: str = "tool_calls") -> dict[str, Any]:
    return {
        "id": "chatcmpl-search",
        "object": "chat.completion.chunk",
        "created": 123,
        "model": "deepseek-v4-flash",
        "choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
    }


def _answer_chunk(text: str, *, finish_reason: str | None = None) -> dict[str, Any]:
    return {
        "id": "chatcmpl-answer",
        "object": "chat.completion.chunk",
        "created": 124,
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "delta": {"content": text} if text else {},
                "finish_reason": finish_reason,
            }
        ],
    }


def _events(chunks: list[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for chunk in chunks:
        data: dict[str, Any] | None = None
        for line in chunk.splitlines():
            if line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        if data is not None:
            events.append(data)
    return events


def test_responses_chat_web_search_executes_tavily_and_continues_chat_stream():
    captured_bodies: list[dict[str, Any]] = []
    streams = [
        _ChatStream([_tool_call_chunk(), _finish_chunk()]),
        _ChatStream(
            [
                _answer_chunk("The search result says native UX is available."),
                _answer_chunk("", finish_reason="stop"),
            ]
        ),
    ]

    async def send_streaming(
        provider_info, target_provider, body, model, *, extra_headers=None
    ):
        assert target_provider == "openai_chat"
        captured_bodies.append(body)
        return streams.pop(0)

    transport = MagicMock()
    transport.send_streaming.side_effect = send_streaming
    fake_tavily = _FakeTavilyClient()
    body = {
        "model": "deepseek-v4-flash",
        "input": [{"role": "user", "content": "Search for Codex web search UX."}],
        "stream": True,
        "tools": [
            {
                "type": "web_search",
                "external_web_access": True,
                "search_context_size": "high",
            }
        ],
    }

    async def run() -> list[str]:
        response, profile = await handle_streaming(
            _route(),
            _provider_info(),
            body,
            transport=transport,
            web_search_client=fake_tavily,
        )
        assert response.status_code == 200
        assert isinstance(response, StreamingResponse)
        assert "request_conversion_ms" in profile
        emitted: list[str] = []
        async for chunk in response._generator:
            assert isinstance(chunk, str)
            emitted.append(chunk)
        return emitted

    emitted = asyncio.run(run())
    events = _events(emitted)

    assert len(captured_bodies) == 2
    web_tool = captured_bodies[0]["tools"][0]["function"]
    assert web_tool["name"] == "web_search"
    assert web_tool["parameters"]["required"] == ["query"]
    assert fake_tavily.calls == [
        (
            "Codex native web search UX",
            WebSearchSettings(max_results=8, search_depth="advanced"),
        )
    ]

    followup_messages = captured_bodies[1]["messages"]
    assert followup_messages[-2]["role"] == "assistant"
    assert followup_messages[-2]["tool_calls"][0]["id"] == "call_web_search"
    assert followup_messages[-1]["role"] == "tool"
    assert followup_messages[-1]["tool_call_id"] == "call_web_search"
    assert "Codex Web Search Docs" in followup_messages[-1]["content"]
    assert "https://example.com/codex-web-search" in followup_messages[-1]["content"]

    web_added = [
        event
        for event in events
        if event.get("type") == "response.output_item.added"
        and event.get("item", {}).get("type") == "web_search_call"
    ]
    web_done = [
        event
        for event in events
        if event.get("type") == "response.output_item.done"
        and event.get("item", {}).get("type") == "web_search_call"
    ]
    completed = [event for event in events if event.get("type") == "response.completed"]

    assert len(web_added) == 1
    assert len(web_done) == 1
    assert web_done[0]["item"]["status"] == "completed"
    assert web_done[0]["item"]["action"] == {
        "type": "search",
        "query": "Codex native web search UX",
    }
    assert len(completed) == 1
    output = completed[0]["response"]["output"]
    assert output[0]["type"] == "web_search_call"
    assert output[1]["type"] == "message"
    assert output[1]["content"][0]["text"] == (
        "The search result says native UX is available."
    )


def test_responses_chat_without_tavily_key_does_not_expose_web_search_tool():
    captured_bodies: list[dict[str, Any]] = []
    stream = _ChatStream(
        [
            _answer_chunk("Search is unavailable."),
            _answer_chunk("", finish_reason="stop"),
        ]
    )

    async def send_streaming(
        provider_info, target_provider, body, model, *, extra_headers=None
    ):
        assert target_provider == "openai_chat"
        captured_bodies.append(body)
        return stream

    transport = MagicMock()
    transport.send_streaming.side_effect = send_streaming
    body = {
        "model": "deepseek-v4-flash",
        "input": [{"role": "user", "content": "Search for Codex web search UX."}],
        "stream": True,
        "tools": [{"type": "web_search", "external_web_access": True}],
        "tool_choice": "web_search",
    }

    async def run() -> list[str]:
        response, _profile = await handle_streaming(
            _route(search_token=""),
            _provider_info(),
            body,
            transport=transport,
        )
        assert isinstance(response, StreamingResponse)
        emitted: list[str] = []
        async for chunk in response._generator:
            assert isinstance(chunk, str)
            emitted.append(chunk)
        return emitted

    emitted = asyncio.run(run())
    events = _events(emitted)

    assert len(captured_bodies) == 1
    assert captured_bodies[0].get("tools") in (None, [])
    assert captured_bodies[0].get("tool_choice") != "web_search"
    assert not [
        event
        for event in events
        if event.get("type") == "response.output_item.added"
        and event.get("item", {}).get("type") == "web_search_call"
    ]
    completed = [event for event in events if event.get("type") == "response.completed"]
    assert completed[0]["response"]["output"][0]["content"][0]["text"] == (
        "Search is unavailable."
    )
