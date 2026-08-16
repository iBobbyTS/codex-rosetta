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
from codex_rosetta.gateway.transport._retry import _RetryPolicy
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
        self.headers: list[dict[str, str]] = []
        self.before_response: dict[str, Any] = {}

    def add(self, url: str, *responses: _FakeStreamingResponse) -> None:
        self.responses[url].extend(responses)

    async def post(self, url: str, **kwargs: Any) -> _FakeStreamingResponse:
        self.calls.append(url)
        self.headers.append(dict(kwargs.get("headers", {})))
        response = self.responses[url].popleft()
        hook = self.before_response.get(url)
        if hook is not None:
            await hook()
        return response


def _provider(
    row_id: str,
    *base_urls: str,
    current: str | None = None,
    credentials: tuple[tuple[str, str], ...] = (("primary", "provider-key"),),
    current_credential: str | None = None,
) -> tuple[ProviderInfo, list[tuple[str, str]]]:
    writes: list[tuple[str, str]] = []
    provider = ProviderInfo(
        "openai_responses",
        configured_id=row_id,
        api_keys=credentials,
        current_api_key=current_credential,
        base_urls=base_urls,
        current_base_url=current or base_urls[0],
        auth_header_fn=lambda key: {"Authorization": f"Bearer {key}"},
        url_template="{base_url}/responses",
        request_encoding="passthrough",
    )

    async def record(configured_id: str, base_url: str) -> None:
        writes.append((configured_id, base_url))

    provider.bind_current_base_url_recorder(record)
    return provider, writes


def _auth_key(provider: ProviderInfo) -> str:
    return provider.auth_headers()["Authorization"].removeprefix("Bearer ")


def test_provider_success_does_not_round_robin_credentials() -> None:
    provider, _ = _provider(
        "row-a",
        "https://first.example/v1",
        credentials=(("first", "key-first"), ("second", "key-second")),
    )
    assert [_auth_key(provider), _auth_key(provider)] == ["key-first", "key-first"]


def test_provider_manual_credential_selection_uses_selected_secret() -> None:
    async def scenario() -> None:
        provider, _ = _provider(
            "row-a",
            "https://first.example/v1",
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        writes: list[tuple[str, str]] = []

        async def record_credential(configured_id: str, credential_id: str) -> None:
            writes.append((configured_id, credential_id))

        provider.bind_current_credential_recorder(record_credential)
        provider.mark_credential_failed("first")
        provider.mark_credential_failed("second")
        await provider.manually_select_credential("second")
        assert provider.current_credential_id == "second"
        assert _auth_key(provider) == "key-second"
        assert provider.credential_statuses() == (
            ("first", "cooling"),
            ("second", "available"),
        )
        assert writes == [("row-a", "second")]

    asyncio.run(scenario())


def test_nonstream_503_rotates_only_credential(monkeypatch) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider(
            "row-a",
            first,
            second,
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        credential_writes: list[tuple[str, str]] = []

        async def record_credential(configured_id: str, credential_id: str) -> None:
            credential_writes.append((configured_id, credential_id))

        provider.bind_current_credential_recorder(record_credential)
        client = _RoutingClient()
        client.add(f"{first}/responses", _json_response(503, {"error": "busy"}))
        client.add(f"{first}/responses", _json_response(200, {"ok": True}))

        result = await _transport(monkeypatch, client).send_request(
            provider, "openai_responses", {}, "model"
        )

        assert result.status_code == 200
        assert provider.base_url == first
        assert provider.current_credential_id == "second"
        assert writes == []
        assert credential_writes == [("row-a", "second")]

    asyncio.run(scenario())


def test_nonstream_alternating_502_then_503_rotates_independent_rings(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider(
            "row-a",
            first,
            second,
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        credential_writes: list[tuple[str, str]] = []

        async def record_credential(configured_id: str, credential_id: str) -> None:
            credential_writes.append((configured_id, credential_id))

        provider.bind_current_credential_recorder(record_credential)
        client = _RoutingClient()
        client.add(
            f"{first}/responses",
            _json_response(502, {"error": "url"}),
            _json_response(503, {"error": "key"}),
            _json_response(200, {"ok": True}),
        )

        result = await _transport(monkeypatch, client).send_request(
            provider, "openai_responses", {}, "model"
        )

        assert result.status_code == 200
        assert provider.base_url == first
        assert provider.current_credential_id == "second"
        assert writes == []
        assert credential_writes == [("row-a", "second")]
        assert [item["Authorization"] for item in client.headers] == [
            "Bearer key-first",
            "Bearer key-first",
            "Bearer key-second",
        ]

    asyncio.run(scenario())


def test_nonstream_alternating_503_then_502_rotates_independent_rings(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider(
            "row-a",
            first,
            second,
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        credential_writes: list[tuple[str, str]] = []

        async def record_credential(configured_id: str, credential_id: str) -> None:
            credential_writes.append((configured_id, credential_id))

        provider.bind_current_credential_recorder(record_credential)
        client = _RoutingClient()
        client.add(f"{first}/responses", _json_response(503, {"error": "key"}))
        client.add(f"{first}/responses", *_literal_502s())
        client.add(f"{second}/responses", _json_response(200, {"ok": True}))

        result = await _transport(monkeypatch, client).send_request(
            provider, "openai_responses", {}, "model"
        )

        assert result.status_code == 200
        assert provider.base_url == second
        assert provider.current_credential_id == "second"
        assert writes == [("row-a", second)]
        assert credential_writes == [("row-a", "second")]

    asyncio.run(scenario())


@pytest.mark.parametrize("path_kind", ["request", "streaming", "passthrough"])
@pytest.mark.parametrize(
    "failure_order", ["url-then-credential", "credential-then-url"]
)
def test_three_url_alternating_failures_preserve_independent_rings(
    monkeypatch,
    path_kind: str,
    failure_order: str,
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        third = "https://third.example/v1"
        provider, url_writes = _provider(
            "row-a",
            first,
            second,
            third,
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        credential_writes: list[tuple[str, str]] = []

        async def record_credential(configured_id: str, credential_id: str) -> None:
            credential_writes.append((configured_id, credential_id))

        provider.bind_current_credential_recorder(record_credential)
        client = _RoutingClient()
        suffix = "models" if path_kind == "passthrough" else "responses"
        first_url = f"{first}/{suffix}"
        second_url = f"{second}/{suffix}"
        success = (
            _FakeStreamingResponse(
                200,
                b'data: {"ok":true}\n\n',
                content_type="text/event-stream",
            )
            if path_kind == "streaming"
            else _json_response(200, {"ok": True})
        )
        url_failures = (
            (_json_response(502, {"error": "url"}),)
            if path_kind == "passthrough"
            else _literal_502s()
        )
        if failure_order == "url-then-credential":
            client.add(first_url, *url_failures)
            client.add(
                second_url,
                _json_response(503, {"error": "credential"}),
                success,
            )
            expected_calls = [first_url] * len(url_failures) + [
                second_url,
                second_url,
            ]
            expected_headers = ["Bearer key-first"] * (len(url_failures) + 1) + [
                "Bearer key-second"
            ]
        else:
            client.add(
                first_url,
                _json_response(503, {"error": "credential"}),
                *url_failures,
            )
            client.add(second_url, success)
            expected_calls = [first_url] * (len(url_failures) + 1) + [second_url]
            expected_headers = ["Bearer key-first"] + ["Bearer key-second"] * (
                len(url_failures) + 1
            )

        transport = _transport(monkeypatch, client)
        if path_kind == "request":
            result = await transport.send_request(
                provider, "openai_responses", {}, "model"
            )
        elif path_kind == "streaming":
            result = await transport.send_streaming(
                provider, "openai_responses", {}, "model"
            )
        else:
            result = await transport.send_passthrough(
                provider, first_url, {}, method="POST"
            )

        assert result.status_code == 200
        assert client.calls == expected_calls
        assert [headers["Authorization"] for headers in client.headers] == (
            expected_headers
        )
        assert provider.base_url == second
        assert provider.current_credential_id == "second"
        assert url_writes == [("row-a", second)]
        assert credential_writes == [("row-a", "second")]

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [400, 401, 429, 500, 504])
def test_nonstream_non503_does_not_rotate_credential(monkeypatch, status: int) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        provider, _ = _provider(
            "row-a",
            first,
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        client = _RoutingClient()
        client.add(f"{first}/responses", _json_response(status, {"error": "x"}))
        result = await _transport(monkeypatch, client).send_request(
            provider, "openai_responses", {}, "model"
        )
        assert result.status_code == status
        assert provider.current_credential_id == "first"
        assert client.calls == [f"{first}/responses"]

    asyncio.run(scenario())


def test_nonstream_503_exhaustion_is_count_only_and_bounded(monkeypatch) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        provider, _ = _provider(
            "row-a",
            first,
            credentials=(("first", "secret-one"), ("second", "secret-two")),
        )
        client = _RoutingClient()
        client.add(
            f"{first}/responses",
            _json_response(503, {"error": "first"}),
            _json_response(503, {"error": "second"}),
        )
        result = await _transport(monkeypatch, client).send_request(
            provider, "openai_responses", {}, "model"
        )
        calls_after_exhaustion = list(client.calls)
        cooling_result = await _transport(monkeypatch, client).send_request(
            provider, "openai_responses", {}, "model"
        )
        assert result.status_code == 503
        assert cooling_result.status_code == 503
        assert result.raw_content == (
            b'{"error":{"message":"All 2 credentials responded with HTTP 503",'
            b'"type":"upstream_error"}}'
        )
        assert b"secret" not in result.raw_content
        assert client.calls == calls_after_exhaustion
        assert len(client.calls) == 2

    asyncio.run(scenario())


def test_503_with_cdn_marker_does_not_rotate_url(monkeypatch) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, _ = _provider(
            "row-a",
            first,
            second,
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        client = _RoutingClient()
        client.add(
            f"{first}/responses",
            _FakeStreamingResponse(
                503,
                _CDN_502_HTML,
                content_type="text/html",
            ),
            _json_response(200, {"ok": True}),
        )
        result = await _transport(monkeypatch, client).send_request(
            provider, "openai_responses", {}, "model"
        )
        assert result.status_code == 200
        assert provider.base_url == first
        assert provider.current_credential_id == "second"
        assert client.calls == [f"{first}/responses", f"{first}/responses"]

    asyncio.run(scenario())


def test_streaming_503_rotates_credential_before_output(monkeypatch) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        provider, _ = _provider(
            "row-a",
            first,
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        client = _RoutingClient()
        client.add(
            f"{first}/responses",
            _json_response(503, {"error": "busy"}),
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
        assert provider.base_url == first
        assert provider.current_credential_id == "second"
        assert [item["Authorization"] for item in client.headers] == [
            "Bearer key-first",
            "Bearer key-second",
        ]

    asyncio.run(scenario())


def test_passthrough_503_rotates_credential_on_same_url(monkeypatch) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        provider, _ = _provider(
            "row-a",
            first,
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        client = _RoutingClient()
        client.add(
            f"{first}/models",
            _json_response(503, {"error": "busy"}),
            _json_response(200, {"data": []}),
        )
        result = await _transport(monkeypatch, client).send_passthrough(
            provider, f"{first}/models", {}, method="POST"
        )
        assert result.status_code == 200
        assert provider.base_url == first
        assert provider.current_credential_id == "second"

    asyncio.run(scenario())


def test_search_passthrough_exhausts_credential_ring_before_provider_failure(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        origin = "https://first.example/v1"
        provider, _ = _provider(
            "row-a",
            origin,
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        client = _RoutingClient()
        client.add(
            f"{origin}/alpha/search",
            _json_response(503, {"error": "first"}),
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
        assert provider.current_credential_id == "second"
        assert client.calls == [
            f"{origin}/alpha/search",
            f"{origin}/alpha/search",
        ]

    asyncio.run(scenario())


def test_nonstream_status_503_rotates_before_oversized_content_length(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        origin = "https://first.example/v1"
        provider, _ = _provider(
            "row-a",
            origin,
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        client = _RoutingClient()
        client.add(
            f"{origin}/responses",
            _FakeStreamingResponse(
                503,
                b"unread",
                headers={
                    "content-length": str(
                        transport_module.MAX_UPSTREAM_ERROR_BODY_BYTES + 1
                    )
                },
            ),
            _json_response(200, {"ok": True}),
        )

        result = await _transport(monkeypatch, client).send_request(
            provider, "openai_responses", {}, "model"
        )

        assert result.status_code == 200
        assert provider.current_credential_id == "second"
        assert len(client.calls) == 2

    asyncio.run(scenario())


def test_streaming_status_503_rotates_before_content_encoding_validation(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        origin = "https://first.example/v1"
        provider, _ = _provider(
            "row-a",
            origin,
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        client = _RoutingClient()
        client.add(
            f"{origin}/responses",
            _FakeStreamingResponse(
                503,
                b"unread",
                headers={"content-encoding": "gzip"},
            ),
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
        assert provider.current_credential_id == "second"
        assert len(client.calls) == 2

    asyncio.run(scenario())


def _transport(
    monkeypatch: pytest.MonkeyPatch,
    client: _RoutingClient,
    *,
    retry_sleep: Any = None,
) -> HttpTransport:
    monkeypatch.setattr(
        transport_module,
        "HttpStreamingResponse",
        _FakeStreamingResponse,
    )
    if retry_sleep is None:

        async def retry_sleep(_delay: float) -> None:
            return None

    transport = HttpTransport(retry_sleep=retry_sleep)
    transport._pool = cast(
        Any,
        SimpleNamespace(get=lambda _proxy=None, allow_redirects=False: client),
    )
    return transport


def _json_response(status: int, payload: dict[str, Any]) -> _FakeStreamingResponse:
    return _FakeStreamingResponse(status, json.dumps(payload).encode())


def _literal_502s(count: int = 6) -> tuple[_FakeStreamingResponse, ...]:
    return tuple(_json_response(502, {"error": "bad"}) for _ in range(count))


def test_retry_policy_is_status_neutral_and_stops_on_caller_result() -> None:
    async def scenario() -> None:
        results = deque(["retry", "done"])
        sleeps: list[float] = []

        async def operation() -> str:
            return results.popleft()

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        result = await _RetryPolicy((1.0, 2.0, 4.0)).run(
            "retry",
            operation,
            lambda item: item == "retry",
            sleep=fake_sleep,
        )

        assert result == "done"
        assert sleeps == [1.0, 2.0]
        assert not results

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("failures_before_success", range(1, 6))
def test_literal_502_succeeds_at_each_retry_position_with_exact_delays(
    monkeypatch,
    streaming: bool,
    failures_before_success: int,
) -> None:
    async def scenario() -> None:
        origin = "https://first.example/v1"
        provider, writes = _provider("row-a", origin)
        client = _RoutingClient()
        success = _FakeStreamingResponse(
            200,
            b'data: {"ok":true}\n\n' if streaming else b'{"ok":true}',
            content_type=("text/event-stream" if streaming else "application/json"),
        )
        client.add(
            f"{origin}/responses",
            *_literal_502s(failures_before_success),
            success,
        )
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        transport = _transport(monkeypatch, client, retry_sleep=fake_sleep)
        result = (
            await transport.send_streaming(provider, "openai_responses", {}, "model")
            if streaming
            else await transport.send_request(provider, "openai_responses", {}, "model")
        )

        assert result.status_code == 200
        assert client.calls == [f"{origin}/responses"] * (failures_before_success + 1)
        assert sleeps == [1.0, 2.0, 4.0, 8.0, 16.0][:failures_before_success]
        assert writes == []

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
def test_each_url_receives_a_fresh_six_attempt_budget(
    monkeypatch, streaming: bool
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider("row-a", first, second)
        client = _RoutingClient()
        client.add(f"{first}/responses", *_literal_502s())
        client.add(
            f"{second}/responses",
            *_literal_502s(5),
            _FakeStreamingResponse(
                200,
                b'data: {"ok":true}\n\n' if streaming else b'{"ok":true}',
                content_type=("text/event-stream" if streaming else "application/json"),
            ),
        )
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        transport = _transport(monkeypatch, client, retry_sleep=fake_sleep)
        result = (
            await transport.send_streaming(provider, "openai_responses", {}, "model")
            if streaming
            else await transport.send_request(provider, "openai_responses", {}, "model")
        )

        assert result.status_code == 200
        assert client.calls == [f"{first}/responses"] * 6 + [f"{second}/responses"] * 6
        assert sleeps == [1.0, 2.0, 4.0, 8.0, 16.0] * 2
        assert provider.base_url == second
        assert writes == [("row-a", second)]

    asyncio.run(scenario())


def test_streaming_allow_failover_false_does_not_retry_literal_502(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        origin = "https://first.example/v1"
        provider, _ = _provider("row-a", origin)
        client = _RoutingClient()
        client.add(f"{origin}/responses", *_literal_502s(1))
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        result = await _transport(
            monkeypatch, client, retry_sleep=fake_sleep
        ).send_streaming(
            provider,
            "openai_responses",
            {},
            "model",
            allow_failover=False,
        )

        assert result.status_code == 502
        assert client.calls == [f"{origin}/responses"]
        assert sleeps == []

    asyncio.run(scenario())


def test_nonstream_rotates_real_502_and_persists_new_current(monkeypatch) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider("row-a", first, second)
        client = _RoutingClient()
        client.add(f"{first}/responses", *_literal_502s())
        client.add(f"{second}/responses", _json_response(200, {"ok": True}))

        result = await _transport(monkeypatch, client).send_request(
            provider, "openai_responses", {}, "model"
        )

        assert result.status_code == 200
        assert result.body == {"ok": True}
        assert client.calls == [f"{first}/responses"] * 6 + [f"{second}/responses"]
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
            *_literal_502s(5),
        )
        client.add(f"{second}/responses", _json_response(200, {"ok": True}))

        result = await _transport(monkeypatch, client).send_request(
            provider, "openai_responses", {}, "model"
        )

        assert result.status_code == 200
        assert client.calls == [f"{first}/responses"] * 6 + [f"{second}/responses"]
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
            *_literal_502s(5),
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
        assert client.calls == [f"{first}/responses"] * 6 + [f"{second}/responses"]
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
                    "request_encoding": "passthrough",
                    "api_keys": [
                        {"id": "primary", "key": "row-a-key"},
                        {"id": "secondary", "key": "row-a-key-2"},
                    ],
                    "current_api_key": "primary",
                    "base_urls": [first, second],
                    "current_base_url": first,
                },
                "row-b": {
                    "provider": "openai",
                    "api_type": "responses",
                    "request_encoding": "passthrough",
                    "api_keys": [{"id": "primary", "key": "row-b-key"}],
                    "current_api_key": "primary",
                    "base_urls": [other],
                    "current_base_url": other,
                },
            },
            "model_groups": {
                "models": {
                    "provider": ["row-a"],
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

        provider = config.providers["row-a"]
        await provider.select_base_url(second)
        await provider.select_credential("secondary")

        saved = json.loads(config_path.read_text())
        assert saved["providers"]["row-a"]["current_base_url"] == second
        assert saved["providers"]["row-a"]["current_api_key"] == "secondary"
        assert saved["providers"]["row-b"]["current_base_url"] == other
        assert saved["providers"]["row-b"]["current_api_key"] == "primary"

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
        client.add(f"{first}/responses", *_literal_502s())
        client.add(f"{second}/responses", *_literal_502s())
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
        client.add(f"{a1}/responses", *_literal_502s())
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


@pytest.mark.parametrize("streaming", [False, True])
def test_claim_waiter_discards_stale_502_before_fresh_same_url_attempt(
    monkeypatch, streaming: bool
) -> None:
    async def scenario() -> None:
        origin = "https://first.example/v1"
        provider, writes = _provider("row-a", origin)
        client = _RoutingClient()
        both_started = asyncio.Event()
        started = 0

        async def synchronize_initial_failures() -> None:
            nonlocal started
            started += 1
            if started == 2:
                both_started.set()
            await both_started.wait()

        client.before_response[f"{origin}/responses"] = synchronize_initial_failures
        success_body = b'data: {"ok":true}\n\n' if streaming else b'{"ok":true}'
        content_type = "text/event-stream" if streaming else "application/json"
        client.add(
            f"{origin}/responses",
            *_literal_502s(2),
            _FakeStreamingResponse(200, success_body, content_type=content_type),
            _FakeStreamingResponse(200, success_body, content_type=content_type),
        )
        retry_started = asyncio.Event()
        release_retry = asyncio.Event()
        sleeps: list[float] = []

        async def blocking_sleep(delay: float) -> None:
            sleeps.append(delay)
            retry_started.set()
            await release_retry.wait()

        transport = _transport(monkeypatch, client, retry_sleep=blocking_sleep)

        async def send():
            if streaming:
                return await transport.send_streaming(
                    provider, "openai_responses", {}, "model"
                )
            return await transport.send_request(
                provider, "openai_responses", {}, "model"
            )

        first_task = asyncio.create_task(send())
        second_task = asyncio.create_task(send())
        await retry_started.wait()
        for _ in range(3):
            await asyncio.sleep(0)
        release_retry.set()
        first_result, second_result = await asyncio.gather(first_task, second_task)

        assert first_result.status_code == second_result.status_code == 200
        assert client.calls == [f"{origin}/responses"] * 4
        assert sleeps == [1.0]
        assert writes == []

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
def test_delayed_initial_502_after_publish_uses_one_fresh_attempt(
    monkeypatch, streaming: bool
) -> None:
    async def scenario() -> None:
        origin = "https://first.example/v1"
        provider, writes = _provider("row-a", origin)
        client = _RoutingClient()
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        release_second = asyncio.Event()
        attempt = 0

        async def delay_second_initial_response() -> None:
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                first_started.set()
                await second_started.wait()
            elif attempt == 2:
                second_started.set()
                await release_second.wait()

        client.before_response[f"{origin}/responses"] = delay_second_initial_response
        success_body = b'data: {"ok":true}\n\n' if streaming else b'{"ok":true}'
        content_type = "text/event-stream" if streaming else "application/json"
        client.add(
            f"{origin}/responses",
            *_literal_502s(2),
            _FakeStreamingResponse(200, success_body, content_type=content_type),
            _FakeStreamingResponse(200, success_body, content_type=content_type),
        )
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        transport = _transport(monkeypatch, client, retry_sleep=fake_sleep)

        async def send():
            if streaming:
                return await transport.send_streaming(
                    provider, "openai_responses", {}, "model"
                )
            return await transport.send_request(
                provider, "openai_responses", {}, "model"
            )

        leader = asyncio.create_task(send())
        await first_started.wait()
        delayed = asyncio.create_task(send())
        await second_started.wait()

        leader_result = await leader
        release_second.set()
        delayed_result = await delayed

        assert leader_result.status_code == delayed_result.status_code == 200
        assert client.calls == [f"{origin}/responses"] * 4
        assert sleeps == [1.0]
        assert writes == []

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
def test_entry_waiter_makes_one_request_after_retry_leader(
    monkeypatch, streaming: bool
) -> None:
    async def scenario() -> None:
        origin = "https://first.example/v1"
        provider, _ = _provider("row-a", origin)
        client = _RoutingClient()
        success_body = b'data: {"ok":true}\n\n' if streaming else b'{"ok":true}'
        content_type = "text/event-stream" if streaming else "application/json"
        client.add(
            f"{origin}/responses",
            *_literal_502s(1),
            _FakeStreamingResponse(200, success_body, content_type=content_type),
            *_literal_502s(1),
        )
        retry_started = asyncio.Event()
        release_retry = asyncio.Event()
        sleeps: list[float] = []

        async def blocking_sleep(delay: float) -> None:
            sleeps.append(delay)
            retry_started.set()
            await release_retry.wait()

        transport = _transport(monkeypatch, client, retry_sleep=blocking_sleep)

        async def send():
            if streaming:
                return await transport.send_streaming(
                    provider, "openai_responses", {}, "model"
                )
            return await transport.send_request(
                provider, "openai_responses", {}, "model"
            )

        leader = asyncio.create_task(send())
        await retry_started.wait()
        follower = asyncio.create_task(send())
        await asyncio.sleep(0)
        release_retry.set()
        leader_result, follower_result = await asyncio.gather(leader, follower)

        assert leader_result.status_code == 200
        assert follower_result.status_code == 502
        assert client.calls == [f"{origin}/responses"] * 3
        assert sleeps == [1.0]
        assert provider.base_url == origin

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
def test_entry_waiter_cdn_rotation_does_not_retry_next_url_literal_502(
    monkeypatch, streaming: bool
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, writes = _provider("row-a", first, second)
        client = _RoutingClient()
        success_body = b'data: {"ok":true}\n\n' if streaming else b'{"ok":true}'
        success_type = "text/event-stream" if streaming else "application/json"
        client.add(
            f"{first}/responses",
            *_literal_502s(1),
            _FakeStreamingResponse(200, success_body, content_type=success_type),
            _FakeStreamingResponse(200, _CDN_502_HTML, content_type="text/html"),
        )
        client.add(f"{second}/responses", *_literal_502s(1))
        retry_started = asyncio.Event()
        release_retry = asyncio.Event()
        sleeps: list[float] = []

        async def blocking_sleep(delay: float) -> None:
            sleeps.append(delay)
            retry_started.set()
            await release_retry.wait()

        transport = _transport(monkeypatch, client, retry_sleep=blocking_sleep)

        async def send():
            if streaming:
                return await transport.send_streaming(
                    provider, "openai_responses", {}, "model"
                )
            return await transport.send_request(
                provider, "openai_responses", {}, "model"
            )

        leader = asyncio.create_task(send())
        await retry_started.wait()
        follower = asyncio.create_task(send())
        for _ in range(3):
            await asyncio.sleep(0)
        release_retry.set()
        leader_result, follower_result = await asyncio.gather(leader, follower)

        assert leader_result.status_code == 200
        assert follower_result.status_code == 502
        assert client.calls == [f"{first}/responses"] * 3 + [f"{second}/responses"]
        assert sleeps == [1.0]
        assert provider.base_url == second
        assert provider.base_url_statuses() == (
            (first, "cooling"),
            (second, "available"),
        )
        assert writes == [("row-a", second)]

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("post_wait_result", ["503", "cdn"])
def test_entry_waiter_preserves_existing_non502_failover_state_machine(
    monkeypatch,
    streaming: bool,
    post_wait_result: str,
) -> None:
    async def scenario() -> None:
        first = "https://first.example/v1"
        second = "https://second.example/v1"
        provider, url_writes = _provider(
            "row-a",
            first,
            second,
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        credential_writes: list[tuple[str, str]] = []

        async def record_credential(configured_id: str, credential_id: str) -> None:
            credential_writes.append((configured_id, credential_id))

        provider.bind_current_credential_recorder(record_credential)
        success_body = b'data: {"ok":true}\n\n' if streaming else b'{"ok":true}'
        success_type = "text/event-stream" if streaming else "application/json"

        def success() -> _FakeStreamingResponse:
            return _FakeStreamingResponse(
                200,
                success_body,
                content_type=success_type,
            )

        client = _RoutingClient()
        post_wait_response = (
            _json_response(503, {"error": "busy"})
            if post_wait_result == "503"
            else _FakeStreamingResponse(200, _CDN_502_HTML, content_type="text/html")
        )
        client.add(
            f"{first}/responses",
            *_literal_502s(1),
            success(),
            post_wait_response,
            *([success()] if post_wait_result == "503" else []),
        )
        if post_wait_result == "cdn":
            client.add(f"{second}/responses", success())

        retry_started = asyncio.Event()
        release_retry = asyncio.Event()
        sleeps: list[float] = []

        async def blocking_sleep(delay: float) -> None:
            sleeps.append(delay)
            retry_started.set()
            await release_retry.wait()

        transport = _transport(monkeypatch, client, retry_sleep=blocking_sleep)

        async def send():
            if streaming:
                return await transport.send_streaming(
                    provider, "openai_responses", {}, "model"
                )
            return await transport.send_request(
                provider, "openai_responses", {}, "model"
            )

        leader = asyncio.create_task(send())
        await retry_started.wait()
        follower = asyncio.create_task(send())
        await asyncio.sleep(0)
        release_retry.set()
        leader_result, follower_result = await asyncio.gather(leader, follower)

        assert leader_result.status_code == follower_result.status_code == 200
        assert sleeps == [1.0]
        if post_wait_result == "503":
            assert client.calls == [f"{first}/responses"] * 4
            assert provider.base_url == first
            assert provider.current_credential_id == "second"
            assert url_writes == []
            assert credential_writes == [("row-a", "second")]
        else:
            assert client.calls == [f"{first}/responses"] * 3 + [f"{second}/responses"]
            assert provider.base_url == second
            assert provider.current_credential_id == "first"
            assert url_writes == [("row-a", second)]
            assert credential_writes == []

    asyncio.run(scenario())


def test_cancellation_during_retry_releases_url_gate(monkeypatch) -> None:
    async def scenario() -> None:
        origin = "https://first.example/v1"
        provider, _ = _provider("row-a", origin)
        client = _RoutingClient()
        client.add(
            f"{origin}/responses",
            *_literal_502s(1),
            _json_response(200, {"ok": True}),
        )
        retry_started = asyncio.Event()
        never_release = asyncio.Event()

        async def blocking_sleep(_delay: float) -> None:
            retry_started.set()
            await never_release.wait()

        transport = _transport(monkeypatch, client, retry_sleep=blocking_sleep)
        leader = asyncio.create_task(
            transport.send_request(provider, "openai_responses", {}, "model")
        )
        await retry_started.wait()
        follower = asyncio.create_task(
            transport.send_request(provider, "openai_responses", {}, "model")
        )
        await asyncio.sleep(0)
        leader.cancel()
        with pytest.raises(asyncio.CancelledError):
            await leader
        result = await asyncio.wait_for(follower, timeout=0.2)

        assert result.status_code == 200
        assert client.calls == [f"{origin}/responses"] * 2

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
def test_same_provider_concurrent_failures_publish_one_current_change(
    monkeypatch, streaming: bool
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
            *_literal_502s(7),
        )
        success_body = b'data: {"ok":true}\n\n' if streaming else b'{"ok":true}'
        content_type = "text/event-stream" if streaming else "application/json"
        client.add(
            f"{second}/responses",
            _FakeStreamingResponse(200, success_body, content_type=content_type),
            _FakeStreamingResponse(200, success_body, content_type=content_type),
        )
        transport = _transport(monkeypatch, client)

        async def send():
            if streaming:
                return await transport.send_streaming(
                    provider, "openai_responses", {}, "model"
                )
            return await transport.send_request(
                provider, "openai_responses", {}, "model"
            )

        first_result, second_result = await asyncio.gather(
            send(),
            send(),
        )

        assert first_result.status_code == second_result.status_code == 200
        assert writes == [("row-a", second)]
        assert client.calls.count(f"{first}/responses") == 7
        assert client.calls.count(f"{second}/responses") == 2

    asyncio.run(scenario())


def test_same_provider_concurrent_503s_publish_one_credential_change(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        origin = "https://first.example/v1"
        provider, _ = _provider(
            "row-a",
            origin,
            credentials=(("first", "key-first"), ("second", "key-second")),
        )
        credential_writes: list[tuple[str, str]] = []

        async def record_credential(configured_id: str, credential_id: str) -> None:
            credential_writes.append((configured_id, credential_id))

        provider.bind_current_credential_recorder(record_credential)
        client = _RoutingClient()
        both_started = asyncio.Event()
        started = 0

        async def synchronize_failures() -> None:
            nonlocal started
            started += 1
            if started == 2:
                both_started.set()
            await both_started.wait()

        client.before_response[f"{origin}/responses"] = synchronize_failures
        client.add(
            f"{origin}/responses",
            _json_response(503, {"error": "busy"}),
            _json_response(503, {"error": "busy"}),
            _json_response(200, {"ok": 1}),
            _json_response(200, {"ok": 2}),
        )
        transport = _transport(monkeypatch, client)

        first_result, second_result = await asyncio.gather(
            transport.send_request(provider, "openai_responses", {}, "model"),
            transport.send_request(provider, "openai_responses", {}, "model"),
        )

        assert first_result.status_code == second_result.status_code == 200
        assert provider.current_credential_id == "second"
        assert credential_writes == [("row-a", "second")]
        assert [item["Authorization"] for item in client.headers].count(
            "Bearer key-first"
        ) == 2
        assert [item["Authorization"] for item in client.headers].count(
            "Bearer key-second"
        ) == 2

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
