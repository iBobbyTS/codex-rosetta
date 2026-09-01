"""Focused Codex Cockpit health probe contract tests."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

import codex_rosetta.gateway.app as app_module
import pytest
from codex_rosetta._vendor.httpserver import JSONResponse, Response
from codex_rosetta.gateway.auth import api_key_principal_var
from codex_rosetta.gateway.app import _probe_codex_cockpit_after_model_error
from codex_rosetta.gateway.config import (
    GatewayConfig,
    ModelGroupConfigurationUnavailable,
    ModelGroupProviderRing,
    _ModelGroupProviderCandidate,
)
from codex_rosetta.gateway.providers import build_provider_info
from codex_rosetta.routing import ResolvedRoute


class _Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    async def request(
        self, method: str, url: str, *, headers: dict[str, str], **kwargs: object
    ) -> object:
        self.calls.append((method, url, headers))
        return self.response


class _Pool:
    def __init__(self, client: _Client) -> None:
        self.client = client

    def get(
        self, proxy_url: str | None = None, *, allow_redirects: bool = False
    ) -> _Client:
        return self.client


def _provider() -> Any:
    return build_provider_info(
        "openai_responses",
        {
            "openai_variant": "codex_cockpit",
            "base_url": "https://cockpit.example/v1",
            "api_keys": [{"id": "primary", "key": "secret"}],
            "auto_rotate_credentials": True,
            "request_encoding": "identity",
        },
    )


def test_health_probe_uses_current_url_and_bearer_without_rotation(monkeypatch) -> None:
    client = _Client(_Response(200, {"available_accounts": 1, "all_accounts": 2}))
    provider = _provider()

    async def fake_request(_client, method, url, **kwargs):
        client.calls.append((method, url, kwargs["headers"]))
        return client.response

    monkeypatch.setattr(
        "codex_rosetta.gateway.transport.http.transport.request_bounded_response",
        fake_request,
    )
    result = asyncio.run(provider.probe_codex_cockpit_health(_Pool(client)))

    assert result.available is True
    assert result.available_accounts == 1
    assert client.calls == [
        ("GET", "https://cockpit.example/v1/health", {"Authorization": "Bearer secret"})
    ]


def test_health_probe_preserves_last_success_on_failure(monkeypatch) -> None:
    client = _Client(_Response(200, {"available_accounts": 1, "all_accounts": 1}))
    provider = _provider()
    pool = _Pool(client)

    async def fake_request(_client, method, url, **kwargs):
        return client.response

    monkeypatch.setattr(
        "codex_rosetta.gateway.transport.http.transport.request_bounded_response",
        fake_request,
    )
    asyncio.run(provider.probe_codex_cockpit_health(pool))
    client.response = _Response(503, {"error": "busy"})

    result = asyncio.run(provider.probe_codex_cockpit_health(pool))

    assert result.available_accounts == 1
    assert result.all_accounts == 1
    assert result.available is True
    assert result.error == "health endpoint returned HTTP 503"


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        (
            _Response(503, {"error": "busy"}),
            "health endpoint returned HTTP 503",
        ),
        (RuntimeError("connection refused"), "connection refused"),
        (
            _Response(200, {"available_accounts": 2, "all_accounts": 1}),
            "health response contains invalid account counts",
        ),
    ],
)
def test_health_probe_retains_counts_but_marks_error_after_initial_success(
    monkeypatch, failure: object, expected_error: str
) -> None:
    client = _Client(_Response(200, {"available_accounts": 1, "all_accounts": 1}))
    provider = _provider()
    pool = _Pool(client)

    calls = 0

    async def fake_request(_client, method, url, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return client.response
        if isinstance(failure, BaseException):
            raise failure
        return failure

    monkeypatch.setattr(
        "codex_rosetta.gateway.transport.http.transport.request_bounded_response",
        fake_request,
    )
    first = asyncio.run(provider.probe_codex_cockpit_health(pool))
    assert (first.available_accounts, first.all_accounts, first.error) == (1, 1, None)

    result = asyncio.run(provider.probe_codex_cockpit_health(pool))

    assert (result.available_accounts, result.all_accounts) == (1, 1)
    assert result.available is True  # retained counts remain displayable
    assert result.error == expected_error


def test_model_error_probe_prioritizes_retained_health_error() -> None:
    updates: list[dict[str, object]] = []

    class _Provider:
        provider_variant = "codex_cockpit"

        async def probe_codex_cockpit_health(self, _pool):
            return SimpleNamespace(
                available=True,
                available_accounts=1,
                all_accounts=1,
                error="health endpoint returned HTTP 503",
            )

    config = SimpleNamespace(
        update_codex_cockpit_health=lambda provider_name, **kwargs: updates.append(
            {"provider_name": provider_name, **kwargs}
        )
    )
    request = SimpleNamespace(
        app=SimpleNamespace(transport=SimpleNamespace(_pool=object()))
    )

    result = asyncio.run(
        _probe_codex_cockpit_after_model_error(
            request,
            cast(GatewayConfig, config),
            _Provider(),
            "cockpit",
            JSONResponse({}, status_code=503),
            {"upstream_attempted": True, "upstream_provider_failure": True},
        )
    )

    assert result is False
    assert updates == [
        {
            "provider_name": "cockpit",
            "available": False,
            "detail": "health endpoint returned HTTP 503",
        }
    ]


def test_health_probe_rejects_invalid_counts(monkeypatch) -> None:
    client = _Client(_Response(200, {"available_accounts": 2, "all_accounts": 1}))

    async def fake_request(_client, method, url, **kwargs):
        return client.response

    monkeypatch.setattr(
        "codex_rosetta.gateway.transport.http.transport.request_bounded_response",
        fake_request,
    )
    result = asyncio.run(_provider().probe_codex_cockpit_health(_Pool(client)))

    assert result.available_accounts is None
    assert result.available is None
    assert result.error == "health response contains invalid account counts"


def test_model_error_probe_skips_404() -> None:
    calls: list[object] = []

    class _Provider:
        provider_variant = "codex_cockpit"

        async def probe_codex_cockpit_health(self, _pool):
            calls.append(True)
            return SimpleNamespace(available=False, error="unreachable")

    config = SimpleNamespace(
        update_codex_cockpit_health=lambda **kwargs: calls.append(kwargs)
    )
    request = SimpleNamespace(
        app=SimpleNamespace(transport=SimpleNamespace(_pool=object()))
    )
    result = asyncio.run(
        _probe_codex_cockpit_after_model_error(
            request,
            cast(GatewayConfig, config),
            _Provider(),
            "cockpit",
            JSONResponse({}, status_code=404),
            {"upstream_attempted": True, "upstream_provider_failure": True},
        )
    )

    assert result is None
    assert calls == []


def test_model_error_probe_updates_routing_state_on_health_failure() -> None:
    updates: list[dict[str, object]] = []

    class _Provider:
        provider_variant = "codex_cockpit"

        async def probe_codex_cockpit_health(self, _pool):
            return SimpleNamespace(
                available=False,
                error="health endpoint returned HTTP 503",
            )

    config = SimpleNamespace(
        update_codex_cockpit_health=lambda provider_name, **kwargs: updates.append(
            {"provider_name": provider_name, **kwargs}
        )
    )
    request = SimpleNamespace(
        app=SimpleNamespace(transport=SimpleNamespace(_pool=object()))
    )
    result = asyncio.run(
        _probe_codex_cockpit_after_model_error(
            request,
            cast(GatewayConfig, config),
            _Provider(),
            "cockpit",
            JSONResponse({}, status_code=503),
            {"upstream_attempted": True, "upstream_provider_failure": True},
        )
    )

    assert result is False
    assert updates == [
        {
            "provider_name": "cockpit",
            "available": False,
            "detail": "health endpoint returned HTTP 503",
        }
    ]


def test_model_error_probe_skips_pre_upstream_error_without_attempt() -> None:
    calls: list[object] = []

    class _Provider:
        provider_variant = "codex_cockpit"

        async def probe_codex_cockpit_health(self, _pool):
            calls.append("probe")
            return SimpleNamespace(available=False, error="unreachable")

    config = SimpleNamespace(
        update_codex_cockpit_health=lambda **kwargs: calls.append(kwargs)
    )
    request = SimpleNamespace(
        app=SimpleNamespace(transport=SimpleNamespace(_pool=object()))
    )
    result = asyncio.run(
        _probe_codex_cockpit_after_model_error(
            request,
            cast(GatewayConfig, config),
            _Provider(),
            "cockpit",
            JSONResponse({}, status_code=400),
            {},
        )
    )

    assert result is None
    assert calls == []


def test_proxy_does_not_probe_cockpit_after_local_pre_upstream_error(
    monkeypatch,
) -> None:
    probe_calls = 0

    class _Provider:
        provider_variant = "codex_cockpit"
        soft_interrupt = False

        async def probe_codex_cockpit_health(self, _pool):
            nonlocal probe_calls
            probe_calls += 1
            return SimpleNamespace(available=False, error="unexpected probe")

    provider = _Provider()

    class _Config:
        models = {"gpt-test": "cockpit"}
        model_group_names_by_model: dict[str, str] = {}
        model_group_rings: dict[str, object] = {}

        def resolve(self, source_provider, model):
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_chat",
                    provider_name="cockpit",
                ),
                provider,
            )

        def update_codex_cockpit_health(self, provider_name, **kwargs):
            raise AssertionError("pre-upstream errors must not update health")

    async def fake_handle_non_streaming(*args: Any, **kwargs: Any):
        return JSONResponse({"error": "local conversion failed"}, status_code=400), {}

    monkeypatch.setattr(app_module, "handle_non_streaming", fake_handle_non_streaming)
    request = SimpleNamespace(
        headers={},
        json=lambda: {"model": "gpt-test", "messages": []},
        app=SimpleNamespace(
            metadata_store=SimpleNamespace(),
            codex_tool_store=SimpleNamespace(),
            transport=SimpleNamespace(_pool=object()),
            metrics=None,
            request_log=None,
            persistence=None,
            profiler_state=None,
            gateway_config=_Config(),
        ),
    )

    token = api_key_principal_var.set("test-client")
    try:
        response = asyncio.run(app_module._proxy_handler(request, "openai_chat"))
    finally:
        api_key_principal_var.reset(token)

    assert response.status_code == 400
    assert probe_calls == 0


def test_model_group_claim_loser_with_sole_cockpit_preserves_original_response(
    monkeypatch,
) -> None:
    class _Ring:
        current = "cockpit"
        candidates = ("cockpit",)

        async def await_attempt(self):
            return (self.current, 0), False, False

        def observe(self):
            return self.current, 0

        async def claim_observation(self, observation):
            assert observation == (self.current, 0)
            return False, False

        async def publish(self):
            return None

        async def handoff(self):
            return None

    class _Provider:
        provider_variant = "codex_cockpit"
        model_group_candidate_identity = "cockpit"
        soft_interrupt = False

        async def probe_codex_cockpit_health(self, _pool):
            return SimpleNamespace(available=False, error="health unavailable")

    class _Config:
        models = {"gpt-test": "cockpit"}
        model_group_names_by_model = {"gpt-test": "main"}

        def __init__(self):
            self.ring = _Ring()
            self.model_group_rings = {"main": self.ring}
            self.providers = {"cockpit": _Provider()}
            self.resolve_calls = 0

        def resolve(self, source_provider, model):
            self.resolve_calls += 1
            if self.resolve_calls > 1:
                raise ModelGroupConfigurationUnavailable("no enabled provider")
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_chat",
                    provider_name="cockpit",
                ),
                self.providers["cockpit"],
            )

        def update_codex_cockpit_health(self, provider_name, **kwargs):
            return None

        def preferred_model_group_candidate(self, group_name, **kwargs):
            return None

    async def fake_handle_non_streaming(*args: Any, **kwargs: Any):
        return JSONResponse({"error": "cockpit upstream failed"}, status_code=503), {
            "upstream_attempted": True,
            "upstream_provider_failure": True,
        }

    monkeypatch.setattr(app_module, "handle_non_streaming", fake_handle_non_streaming)
    config = _Config()
    request = SimpleNamespace(
        headers={},
        json=lambda: {"model": "gpt-test", "messages": []},
        app=SimpleNamespace(
            metadata_store=SimpleNamespace(),
            codex_tool_store=SimpleNamespace(),
            transport=SimpleNamespace(_pool=object()),
            metrics=None,
            request_log=None,
            persistence=None,
            profiler_state=None,
            gateway_config=config,
        ),
    )

    token = api_key_principal_var.set("test-client")
    try:
        response = asyncio.run(app_module._proxy_handler(request, "openai_chat"))
    finally:
        api_key_principal_var.reset(token)

    assert response.status_code == 503
    assert isinstance(response, Response)
    assert json.loads(response.body) == {"error": "cockpit upstream failed"}
    assert config.resolve_calls == 1


def test_model_group_health_failover_claim_loser_does_not_publish_generation(
    monkeypatch,
) -> None:
    """A sole-provider loser must retain its response and leave the gate alone."""
    candidate = _ModelGroupProviderCandidate("cockpit")
    ring = ModelGroupProviderRing("main", [candidate], candidate)
    publish_started = asyncio.Event()
    release_publish = asyncio.Event()
    publish_calls = 0
    original_publish = ring.publish

    async def delayed_publish() -> None:
        nonlocal publish_calls
        publish_calls += 1
        publish_started.set()
        await release_publish.wait()
        await original_publish()

    cast(Any, ring).publish = delayed_publish

    health_waiters = 0
    health_ready = asyncio.Event()

    class _Provider:
        provider_variant = "codex_cockpit"
        model_group_candidate_identity = "cockpit"
        soft_interrupt = False

        async def probe_codex_cockpit_health(self, _pool):
            nonlocal health_waiters
            health_waiters += 1
            if health_waiters == 2:
                health_ready.set()
            await health_ready.wait()
            return SimpleNamespace(available=False, error="health unavailable")

    provider = _Provider()

    class _Config:
        models = {"gpt-test": "cockpit"}
        model_group_names_by_model = {"gpt-test": "main"}
        providers = {"cockpit": provider}
        model_group_rings = {"main": ring}

        def resolve(self, source_provider, model):
            return (
                ResolvedRoute(
                    source_provider=source_provider,
                    target_provider="openai_chat",
                    provider_name="cockpit",
                ),
                provider,
            )

        def update_codex_cockpit_health(self, provider_name, **kwargs):
            return None

        def preferred_model_group_candidate(self, group_name, **kwargs):
            return None

        def available_model_group_candidates(self, group_name):
            return (candidate,)

    async def fake_handle_non_streaming(*args: Any, **kwargs: Any):
        return JSONResponse({"error": "cockpit upstream failed"}, status_code=503), {
            "upstream_attempted": True,
            "upstream_provider_failure": True,
        }

    monkeypatch.setattr(app_module, "handle_non_streaming", fake_handle_non_streaming)

    def make_request() -> Any:
        return SimpleNamespace(
            headers={},
            json=lambda: {"model": "gpt-test", "messages": []},
            app=SimpleNamespace(
                metadata_store=SimpleNamespace(),
                codex_tool_store=SimpleNamespace(),
                transport=SimpleNamespace(_pool=object()),
                metrics=None,
                request_log=None,
                persistence=None,
                profiler_state=None,
                gateway_config=_Config(),
            ),
        )

    async def run_concurrent() -> tuple[Any, Any]:
        first = asyncio.create_task(
            app_module._proxy_handler(make_request(), "openai_chat")
        )
        second = asyncio.create_task(
            app_module._proxy_handler(make_request(), "openai_chat")
        )
        await publish_started.wait()
        release_publish.set()
        return await asyncio.gather(first, second)

    token = api_key_principal_var.set("test-client")
    try:
        responses = asyncio.run(run_concurrent())
    finally:
        api_key_principal_var.reset(token)

    assert [response.status_code for response in responses] == [503, 503]
    assert all(
        json.loads(response.body) == {"error": "cockpit upstream failed"}
        for response in responses
    )
    assert publish_calls == 1
