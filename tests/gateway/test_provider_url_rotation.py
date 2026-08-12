"""Focused tests for configured Provider base-URL rotation."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from types import SimpleNamespace
from typing import Any, cast

import pytest

from codex_rosetta.gateway.app import _bind_provider_current_recorders
from codex_rosetta.gateway.config import GatewayConfig
from codex_rosetta.gateway.search_provider_candidates import (
    ConfiguredResponsesSearchProviderCandidate,
    SelfHostedSearchProviderCandidate,
)
from codex_rosetta.gateway.search_provider_chain import (
    SearchProviderChainCoordinator,
    SearchProviderRequestBudget,
)
from codex_rosetta.gateway.search_provider_executor import (
    SearchProviderExecutor,
    SearchRequest,
)
from codex_rosetta.gateway.transport import ProviderInfo, UpstreamProtocolError
from codex_rosetta.gateway.transport.http import transport as transport_module
from codex_rosetta.gateway.transport.http.transport import HttpTransport


_CDN_502_HTML = (
    "<html><head><title>网站请求超时</title></head>"
    "<body><p>回源请求被中断</p><p>502</p></body></html>"
).encode()


class _FakeStreamingResponse:
    def __init__(
        self,
        status_code: int,
        body: bytes,
        *,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.headers.update(headers or {})
        self._body = body
        self.closed = False

    async def aiter_bytes(self, chunk_size: int = 4096):
        del chunk_size
        yield self._body

    async def aiter_lines(self, max_line_bytes: int | None = None):
        del max_line_bytes
        for line in self._body.decode(errors="replace").splitlines():
            yield line

    async def aclose(self) -> None:
        self.closed = True


class _RoutingClient:
    def __init__(self) -> None:
        self.responses: dict[str, deque[_FakeStreamingResponse]] = defaultdict(deque)
        self.calls: list[str] = []
        self.before_response: dict[str, Any] = {}

    def add(self, url: str, *responses: _FakeStreamingResponse) -> None:
        self.responses[url].extend(responses)

    async def post(self, url: str, **kwargs: Any) -> _FakeStreamingResponse:
        del kwargs
        self.calls.append(url)
        hook = self.before_response.get(url)
        if hook is not None:
            await hook()
        return self.responses[url].popleft()


def _provider(
    row_id: str,
    *base_urls: str,
    current: str | None = None,
) -> tuple[ProviderInfo, list[tuple[str, str]]]:
    writes: list[tuple[str, str]] = []
    provider = ProviderInfo(
        "openai_responses",
        configured_id=row_id,
        api_key="provider-key",
        base_urls=base_urls,
        current_base_url=current or base_urls[0],
        auth_header_fn=lambda key: {"Authorization": f"Bearer {key}"},
        url_template="{base_url}/responses",
    )

    async def record(configured_id: str, base_url: str) -> None:
        writes.append((configured_id, base_url))

    provider.bind_current_base_url_recorder(record)
    return provider, writes


def _transport(
    monkeypatch: pytest.MonkeyPatch,
    client: _RoutingClient,
) -> HttpTransport:
    monkeypatch.setattr(
        transport_module,
        "HttpStreamingResponse",
        _FakeStreamingResponse,
    )
    transport = HttpTransport()
    transport._pool = cast(
        Any,
        SimpleNamespace(get=lambda _proxy=None, allow_redirects=False: client),
    )
    return transport


def _json_response(status: int, payload: dict[str, Any]) -> _FakeStreamingResponse:
    return _FakeStreamingResponse(status, json.dumps(payload).encode())


def test_nonstream_rotates_real_502_and_persists_new_current(monkeypatch) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider("row-a", first, second)
        client = _RoutingClient()
        client.add(f"{first}/responses", _json_response(502, {"error": "bad"}))
        client.add(f"{second}/responses", _json_response(200, {"ok": True}))

        result = await _transport(monkeypatch, client).send_request(
            provider, "openai_responses", {}, "model"
        )

        assert result.status_code == 200
        assert result.body == {"ok": True}
        assert client.calls == [f"{first}/responses", f"{second}/responses"]
        assert provider.base_url == second
        assert writes == [("row-a", second)]

    asyncio.run(scenario())


def test_nonstream_status_502_rotates_before_oversized_content_length(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider("row-a", first, second)
        client = _RoutingClient()
        client.add(
            f"{first}/responses",
            _FakeStreamingResponse(
                502,
                b"unread",
                headers={
                    "content-length": str(
                        transport_module.MAX_UPSTREAM_ERROR_BODY_BYTES + 1
                    )
                },
            ),
        )
        client.add(f"{second}/responses", _json_response(200, {"ok": True}))

        result = await _transport(monkeypatch, client).send_request(
            provider, "openai_responses", {}, "model"
        )

        assert result.status_code == 200
        assert client.calls == [f"{first}/responses", f"{second}/responses"]
        assert writes == [("row-a", second)]

    asyncio.run(scenario())


def test_streaming_status_502_rotates_before_content_encoding_validation(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider("row-a", first, second)
        client = _RoutingClient()
        client.add(
            f"{first}/responses",
            _FakeStreamingResponse(
                502,
                b"unread",
                headers={"content-encoding": "gzip"},
            ),
        )
        client.add(
            f"{second}/responses",
            _FakeStreamingResponse(
                200,
                b'data: {"ok":true}\n\n',
                content_type="text/event-stream",
            ),
        )

        result = await _transport(monkeypatch, client).send_streaming(
            provider, "openai_responses", {}, "model"
        )

        assert result.status_code == 200
        assert client.calls == [f"{first}/responses", f"{second}/responses"]
        assert writes == [("row-a", second)]

    asyncio.run(scenario())


def test_app_bound_recorder_persists_only_the_selected_configured_row(
    tmp_path,
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        other = "https://other.example/v1"
        document = {
            "providers": {
                "row-a": {
                    "provider": "openai",
                    "api_type": "responses",
                    "api_key": "row-a-key",
                    "base_urls": [first, second],
                    "current_base_url": first,
                },
                "row-b": {
                    "provider": "openai",
                    "api_type": "responses",
                    "api_key": "row-b-key",
                    "base_urls": [other],
                    "current_base_url": other,
                },
            },
            "model_groups": {
                "models": {
                    "provider": "row-a",
                    "type": "llm",
                    "models": {"gpt-5.6-terra": {}},
                }
            },
            "server": {
                "admin_password": "test-admin-password",
                "api_keys": [{"id": "test", "label": "Test", "key": "test-key"}],
            },
        }
        config_path = tmp_path / "config.jsonc"
        config_path.write_text(json.dumps(document))
        config = GatewayConfig(document)
        _bind_provider_current_recorders(config, str(config_path))

        await config.providers["row-a"].select_base_url(second)

        saved = json.loads(config_path.read_text())
        assert saved["providers"]["row-a"]["current_base_url"] == second
        assert saved["providers"]["row-b"]["current_base_url"] == other

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
def test_sanitized_cdn_html_rotates_with_misleading_success_status(
    monkeypatch, streaming: bool
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider("row-a", first, second)
        client = _RoutingClient()
        client.add(
            f"{first}/responses",
            _FakeStreamingResponse(200, _CDN_502_HTML, content_type="text/html"),
        )
        client.add(
            f"{second}/responses",
            _FakeStreamingResponse(
                200,
                b'data: {"ok":true}\n\n' if streaming else b'{"ok":true}',
                content_type="text/event-stream" if streaming else "application/json",
            ),
        )
        transport = _transport(monkeypatch, client)

        if streaming:
            result = await transport.send_streaming(
                provider, "openai_responses", {}, "model"
            )
            assert result.status_code == 200
        else:
            result = await transport.send_request(
                provider, "openai_responses", {}, "model"
            )
            assert result.status_code == 200
            assert result.body == {"ok": True}

        assert client.calls == [f"{first}/responses", f"{second}/responses"]
        assert writes == [("row-a", second)]

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
def test_http_503_is_not_a_rotation_trigger(monkeypatch, streaming: bool) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider("row-a", first, second)
        client = _RoutingClient()
        client.add(f"{first}/responses", _json_response(503, {"error": "busy"}))
        transport = _transport(monkeypatch, client)

        result = (
            await transport.send_streaming(provider, "openai_responses", {}, "model")
            if streaming
            else await transport.send_request(provider, "openai_responses", {}, "model")
        )

        assert result.status_code == 503
        assert client.calls == [f"{first}/responses"]
        assert provider.base_url == first
        assert writes == []

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
def test_unrelated_html_is_not_a_rotation_trigger(monkeypatch, streaming: bool) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider("row-a", first, second)
        client = _RoutingClient()
        client.add(
            f"{first}/responses",
            _FakeStreamingResponse(
                200,
                b"<html><title>Maintenance</title></html>",
                content_type="text/html",
            ),
        )
        transport = _transport(monkeypatch, client)

        if streaming:
            stream = await transport.send_streaming(
                provider, "openai_responses", {}, "model"
            )
            raw = stream.aiter_raw_bytes()
            assert raw is not None
            assert b"".join([chunk async for chunk in raw]).startswith(b"<html>")
        else:
            with pytest.raises((json.JSONDecodeError, UpstreamProtocolError)):
                await transport.send_request(provider, "openai_responses", {}, "model")

        assert client.calls == [f"{first}/responses"]
        assert provider.base_url == first
        assert writes == []

    asyncio.run(scenario())


def test_full_ring_returns_static_502_and_all_cooling_skips_upstream(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider("row-a", first, second)
        client = _RoutingClient()
        client.add(f"{first}/responses", _json_response(502, {"secret": first}))
        client.add(f"{second}/responses", _json_response(502, {"secret": second}))
        transport = _transport(monkeypatch, client)

        result = await transport.send_request(provider, "openai_responses", {}, "model")
        calls_after_first_ring = list(client.calls)
        cooling_result = await transport.send_request(
            provider, "openai_responses", {}, "model"
        )

        expected = b"All 2 domains responded with HTTP 502"
        assert result.status_code == cooling_result.status_code == 502
        assert expected in result.raw_content
        assert first.encode() not in result.raw_content
        assert second.encode() not in result.raw_content
        assert client.calls == calls_after_first_ring
        assert writes == [("row-a", second)]

    asyncio.run(scenario())


def test_different_provider_request_is_not_blocked_or_persisted_by_rotation(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        a1 = "https://a-one.example/v1"
        a2 = "https://a-two.example/v1"
        b1 = "https://b-one.example/v1"
        provider_a, writes_a = _provider("row-a", a1, a2)
        provider_b, writes_b = _provider("row-b", b1)
        client = _RoutingClient()
        release_a = asyncio.Event()
        a_started = asyncio.Event()

        async def block_a() -> None:
            a_started.set()
            await release_a.wait()

        client.before_response[f"{a1}/responses"] = block_a
        client.add(f"{a1}/responses", _json_response(502, {"error": "bad"}))
        client.add(f"{a2}/responses", _json_response(200, {"provider": "a"}))
        client.add(f"{b1}/responses", _json_response(200, {"provider": "b"}))
        transport = _transport(monkeypatch, client)

        rotating = asyncio.create_task(
            transport.send_request(provider_a, "openai_responses", {}, "model")
        )
        await a_started.wait()
        healthy = await asyncio.wait_for(
            transport.send_request(provider_b, "openai_responses", {}, "model"),
            timeout=0.2,
        )
        release_a.set()
        rotated = await rotating

        assert healthy.body == {"provider": "b"}
        assert rotated.body == {"provider": "a"}
        assert writes_a == [("row-a", a2)]
        assert writes_b == []

    asyncio.run(scenario())


def test_same_provider_concurrent_failures_publish_one_current_change(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider("row-a", first, second)
        client = _RoutingClient()
        both_started = asyncio.Event()
        started = 0

        async def synchronize_failures() -> None:
            nonlocal started
            started += 1
            if started == 2:
                both_started.set()
            await both_started.wait()

        client.before_response[f"{first}/responses"] = synchronize_failures
        client.add(
            f"{first}/responses",
            _json_response(502, {"error": "bad"}),
            _json_response(502, {"error": "bad"}),
        )
        client.add(
            f"{second}/responses",
            _json_response(200, {"ok": 1}),
            _json_response(200, {"ok": 2}),
        )
        transport = _transport(monkeypatch, client)

        first_result, second_result = await asyncio.gather(
            transport.send_request(provider, "openai_responses", {}, "model"),
            transport.send_request(provider, "openai_responses", {}, "model"),
        )

        assert first_result.status_code == second_result.status_code == 200
        assert writes == [("row-a", second)]
        assert client.calls.count(f"{first}/responses") == 2
        assert client.calls.count(f"{second}/responses") == 2

    asyncio.run(scenario())


def test_passthrough_rotates_the_same_path_and_preserves_one_request_budget_charge(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider("row-a", first, second)
        client = _RoutingClient()
        client.add(
            f"{first}/alpha/search",
            _json_response(502, {"error": "bad"}),
        )
        client.add(
            f"{second}/alpha/search",
            _json_response(200, {"output": "ok", "results": []}),
        )
        budget = SearchProviderRequestBudget(max_external_calls=1)
        candidate = ConfiguredResponsesSearchProviderCandidate(
            row_id="responses",
            responses_provider="row-a",
            responses_model="search-model",
            provider_info=provider,
            identity="responses-identity",
        )

        result = await SearchProviderExecutor(
            responses_transport=_transport(monkeypatch, client)
        ).execute(candidate, SearchRequest.from_body({}), request_budget=budget)

        assert result == {"output": "ok", "results": []}
        assert budget.external_calls == 1
        assert client.calls == [
            f"{first}/alpha/search",
            f"{second}/alpha/search",
        ]
        assert writes == [("row-a", second)]

    asyncio.run(scenario())


def test_search_chain_advances_provider_only_after_url_ring_exhaustion(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider("row-a", first, second)
        client = _RoutingClient()
        client.add(
            f"{first}/alpha/search",
            _json_response(502, {"error": "bad"}),
        )
        client.add(
            f"{second}/alpha/search",
            _json_response(502, {"error": "bad"}),
        )
        responses = ConfiguredResponsesSearchProviderCandidate(
            row_id="responses",
            responses_provider="row-a",
            responses_model="search-model",
            provider_info=provider,
            identity="responses-identity",
        )
        fallback = SelfHostedSearchProviderCandidate(
            row_id="fallback",
            provider="self_hosted_google",
            identity="fallback-identity",
        )
        executor = SearchProviderExecutor(
            responses_transport=_transport(monkeypatch, client)
        )
        attempted: list[str] = []

        async def run_candidate(candidate):
            attempted.append(candidate.row_id)
            if candidate is fallback:
                return {"output": "fallback", "results": []}
            return await executor.execute(candidate, SearchRequest.from_body({}))

        result = await SearchProviderChainCoordinator().run(
            (responses, fallback), run_candidate
        )

        assert result == {"output": "fallback", "results": []}
        assert attempted == ["responses", "fallback"]
        assert client.calls == [
            f"{first}/alpha/search",
            f"{second}/alpha/search",
        ]
        assert writes == [("row-a", second)]

    asyncio.run(scenario())
