from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

from codex_rosetta.gateway.search_provider_candidates import (
    ConfiguredResponsesSearchProviderCandidate,
    DeepSeekNativeResponsesSearchProviderCandidate,
    SearchProviderCandidate,
    SelfHostedSearchProviderCandidate,
    TavilySearchProviderCandidate,
)
from codex_rosetta.gateway.search_provider_chain import (
    SearchProviderAttemptCategory,
    SearchProviderAttemptError,
    SearchProviderBudgetExceeded,
    SearchProviderBudgetReason,
    SearchProviderChainCoordinator,
    SearchProviderRequestFailover,
    SearchProviderRequestFailoverReason,
    SearchProviderRequestBudget,
)
from codex_rosetta.gateway.search_provider_contract import (
    DEEPSEEK_NATIVE_RESPONSES_CONTRACT,
    GPT_PASSTHROUGH_CONTRACT,
    SearchProviderCapability,
    SearchProviderContract,
    SearchProviderExecutionMode,
    SearchProviderFamily,
)
from codex_rosetta.gateway.deepseek_responses_search import (
    DeepSeekSearchError,
    DeepSeekSearchErrorCategory,
    DeepSeekSearchResult,
)
from codex_rosetta.gateway.search_provider_executor import (
    SearchProviderExecutor,
    SearchProviderTerminalError,
    SearchRequest,
    _map_local_error,
)
from codex_rosetta.gateway.transport._base import UpstreamResponse, UpstreamTransport
from codex_rosetta.gateway.web_search import (
    TavilyRequestError,
    TavilyRequestErrorCategory,
    WebSearchSettings,
)
from codex_rosetta.gateway.web_run_sidecar import (
    WebRunSidecarSearchError,
    WebRunSidecarSearchErrorCategory,
)


def run(awaitable):
    return asyncio.run(awaitable)


class FakeSearch:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    async def search(self, query, *, settings):
        self.calls.append((query, settings))
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def configured_responses_candidate():
    candidate = object.__new__(ConfiguredResponsesSearchProviderCandidate)
    object.__setattr__(candidate, "row_id", "responses")
    object.__setattr__(candidate, "responses_model", "search-model")
    object.__setattr__(candidate, "responses_provider", "p")
    object.__setattr__(candidate, "provider", "configured_responses_provider")
    object.__setattr__(candidate, "identity", "responses-identity")
    object.__setattr__(candidate, "contract", GPT_PASSTHROUGH_CONTRACT)
    return candidate


def deepseek_candidate(*, credential: str = "deepseek-secret"):
    candidate = object.__new__(DeepSeekNativeResponsesSearchProviderCandidate)
    object.__setattr__(candidate, "row_id", "deepseek")
    object.__setattr__(candidate, "deepseek_provider", "official")
    object.__setattr__(
        candidate,
        "provider_info",
        SimpleNamespace(
            name="deepseek",
            base_url="https://api.deepseek.com",
            credential_values=(credential,),
        ),
    )
    object.__setattr__(candidate, "provider", "deepseek_native_responses")
    object.__setattr__(candidate, "model", "deepseek-v4-flash")
    object.__setattr__(candidate, "identity", "deepseek-identity")
    object.__setattr__(candidate, "contract", DEEPSEEK_NATIVE_RESPONSES_CONTRACT)
    return candidate


class FakeDeepSeekClient:
    def __init__(self, value):
        self.value = value
        self.calls = []

    async def execute(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


def test_deepseek_executor_calls_accepted_client_once_and_ignores_alpha_body():
    result_value = DeepSeekSearchResult(
        output="DeepSeek answer",
        results=(
            {
                "title": "Python",
                "url": "https://python.org/",
                "content": "Official site",
            },
        ),
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )
    client = FakeDeepSeekClient(result_value)
    factories = []

    def factory(credential, origin):
        factories.append((credential, origin))
        return client

    budget = SearchProviderRequestBudget(max_external_calls=1)
    body = {
        "model": "caller",
        "commands": [{"type": "private", "payload": "never-forward"}],
        "history": ["private"],
    }
    request = SearchRequest.from_body(
        body,
        [("latest Python", WebSearchSettings())],
        requires_reference_storage=True,
    )

    result = run(
        SearchProviderExecutor(deepseek_client_factory=factory).execute(
            deepseek_candidate(), request, request_budget=budget
        )
    )

    assert factories == [("deepseek-secret", "https://api.deepseek.com")]
    assert client.calls == [
        (
            "latest Python",
            {
                "model": "deepseek-v4-flash",
                "max_output_tokens": 1024,
                "citation_limit": 5,
            },
        )
    ]
    assert budget.external_calls == 1
    assert result == {
        "output": "DeepSeek answer",
        "results": [
            {
                "title": "Python",
                "url": "https://python.org/",
                "content": "Official site",
            }
        ],
    }
    assert request.body == body


@pytest.mark.parametrize(
    "search_request",
    [
        SearchRequest.from_body({}, []),
        SearchRequest.from_body(
            {}, [("one", WebSearchSettings()), ("two", WebSearchSettings())]
        ),
        SearchRequest.from_body(
            {}, [("one", WebSearchSettings(include_domains=("python.org",)))]
        ),
    ],
)
def test_deepseek_local_request_conflicts_are_terminal_before_effects(search_request):
    factories = []
    budget = SearchProviderRequestBudget()

    with pytest.raises(SearchProviderTerminalError):
        run(
            SearchProviderExecutor(
                deepseek_client_factory=lambda *args: factories.append(args)
            ).execute(deepseek_candidate(), search_request, request_budget=budget)
        )

    assert factories == []
    assert budget.external_calls == 0


def test_deepseek_contract_substitution_is_terminal_before_effects():
    candidate = deepseek_candidate()
    object.__setattr__(candidate, "contract", GPT_PASSTHROUGH_CONTRACT)
    budget = SearchProviderRequestBudget()
    factories = []

    with pytest.raises(SearchProviderTerminalError):
        run(
            SearchProviderExecutor(
                deepseek_client_factory=lambda *args: factories.append(args)
            ).execute(
                candidate,
                SearchRequest.from_body({}, [("q", WebSearchSettings())]),
                request_budget=budget,
            )
        )

    assert factories == []
    assert budget.external_calls == 0


@pytest.mark.parametrize(
    "provider_info",
    [
        SimpleNamespace(
            name="openai",
            base_url="https://api.deepseek.com",
            credential_values=("secret",),
        ),
        SimpleNamespace(
            name="deepseek",
            base_url="https://proxy.example/v1",
            credential_values=("secret",),
        ),
        SimpleNamespace(
            name="deepseek",
            base_url="https://api.deepseek.com",
            credential_values=(),
        ),
        SimpleNamespace(
            name="deepseek",
            base_url="https://api.deepseek.com",
            credential_values=("one", "two"),
        ),
    ],
)
def test_deepseek_invalid_candidate_state_is_terminal_before_effects(provider_info):
    candidate = deepseek_candidate()
    object.__setattr__(candidate, "provider_info", provider_info)
    factories = []
    budget = SearchProviderRequestBudget()

    with pytest.raises(SearchProviderTerminalError):
        run(
            SearchProviderExecutor(
                deepseek_client_factory=lambda *args: factories.append(args)
            ).execute(
                candidate,
                SearchRequest.from_body({}, [("q", WebSearchSettings())]),
                request_budget=budget,
            )
        )

    assert factories == []
    assert budget.external_calls == 0


def test_deepseek_exhausted_budget_does_not_enter_client_or_retry():
    client = FakeDeepSeekClient(DeepSeekSearchResult("unused", (), {"total_tokens": 0}))
    factories = []

    def factory(*args):
        factories.append(args)
        return client

    budget = SearchProviderRequestBudget(max_external_calls=1)

    async def consume() -> None:
        return None

    run(budget.run_external_call(consume))
    with pytest.raises(SearchProviderBudgetExceeded):
        run(
            SearchProviderExecutor(deepseek_client_factory=factory).execute(
                deepseek_candidate(),
                SearchRequest.from_body({}, [("q", WebSearchSettings())]),
                request_budget=budget,
            )
        )

    assert len(factories) == 1
    assert client.calls == []
    assert budget.external_calls == 1


def test_deepseek_invalid_normalized_mapping_is_attempt_failure():
    client = FakeDeepSeekClient(
        SimpleNamespace(as_search_response=lambda: {"output": 123, "results": []})
    )
    budget = SearchProviderRequestBudget()

    with pytest.raises(SearchProviderAttemptError) as caught:
        run(
            SearchProviderExecutor(deepseek_client_factory=lambda *_: client).execute(
                deepseek_candidate(),
                SearchRequest.from_body({}, [("q", WebSearchSettings())]),
                request_budget=budget,
            )
        )

    assert caught.value.category is SearchProviderAttemptCategory.INVALID_RESPONSE
    assert budget.external_calls == 1
    assert len(client.calls) == 1


def test_deepseek_factory_signal_and_unknown_client_error_propagate_unchanged():
    factory_signal = KeyboardInterrupt("factory")

    def failed_factory(*_args):
        raise factory_signal

    with pytest.raises(KeyboardInterrupt) as caught:
        run(
            SearchProviderExecutor(deepseek_client_factory=failed_factory).execute(
                deepseek_candidate(),
                SearchRequest.from_body({}, [("q", WebSearchSettings())]),
            )
        )
    assert caught.value is factory_signal

    client_error = RuntimeError("unknown")
    client = FakeDeepSeekClient(client_error)
    with pytest.raises(RuntimeError) as caught:
        run(
            SearchProviderExecutor(deepseek_client_factory=lambda *_: client).execute(
                deepseek_candidate(),
                SearchRequest.from_body({}, [("q", WebSearchSettings())]),
            )
        )
    assert caught.value is client_error
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("category", "status", "expected", "quota"),
    [
        (
            DeepSeekSearchErrorCategory.HTTP_ERROR,
            400,
            SearchProviderTerminalError,
            False,
        ),
        (
            DeepSeekSearchErrorCategory.HTTP_ERROR,
            422,
            SearchProviderTerminalError,
            False,
        ),
        (
            DeepSeekSearchErrorCategory.HTTP_ERROR,
            402,
            SearchProviderAttemptCategory.QUOTA_EXHAUSTED,
            True,
        ),
        (
            DeepSeekSearchErrorCategory.HTTP_ERROR,
            401,
            SearchProviderAttemptCategory.HTTP_ERROR,
            False,
        ),
        (
            DeepSeekSearchErrorCategory.HTTP_ERROR,
            403,
            SearchProviderAttemptCategory.HTTP_ERROR,
            False,
        ),
        (
            DeepSeekSearchErrorCategory.HTTP_ERROR,
            429,
            SearchProviderAttemptCategory.HTTP_ERROR,
            False,
        ),
        (
            DeepSeekSearchErrorCategory.HTTP_ERROR,
            500,
            SearchProviderAttemptCategory.UPSTREAM_FAILURE,
            False,
        ),
        (
            DeepSeekSearchErrorCategory.CONNECTION_ERROR,
            None,
            SearchProviderAttemptCategory.CONNECTION_ERROR,
            False,
        ),
        (
            DeepSeekSearchErrorCategory.TRANSPORT_ERROR,
            None,
            SearchProviderAttemptCategory.CONNECTION_ERROR,
            False,
        ),
        (
            DeepSeekSearchErrorCategory.TIMEOUT,
            None,
            SearchProviderAttemptCategory.CONNECTION_ERROR,
            False,
        ),
        (
            DeepSeekSearchErrorCategory.INVALID_JSON,
            None,
            SearchProviderAttemptCategory.INVALID_RESPONSE,
            False,
        ),
        (
            DeepSeekSearchErrorCategory.INVALID_SHAPE,
            None,
            SearchProviderAttemptCategory.INVALID_RESPONSE,
            False,
        ),
        (
            DeepSeekSearchErrorCategory.BODY_LIMIT,
            None,
            SearchProviderAttemptCategory.INVALID_RESPONSE,
            False,
        ),
        (
            DeepSeekSearchErrorCategory.CREDENTIAL_COLLISION,
            None,
            SearchProviderAttemptCategory.INVALID_RESPONSE,
            False,
        ),
    ],
)
def test_deepseek_adapter_error_mapping(category, status, expected, quota):
    client = FakeDeepSeekClient(DeepSeekSearchError(category, status_code=status))
    budget = SearchProviderRequestBudget()

    if expected is SearchProviderTerminalError:
        with pytest.raises(
            SearchProviderTerminalError, match="Search request rejected"
        ):
            run(
                SearchProviderExecutor(
                    deepseek_client_factory=lambda *_: client
                ).execute(
                    deepseek_candidate(),
                    SearchRequest.from_body({}, [("q", WebSearchSettings())]),
                    request_budget=budget,
                )
            )
    else:
        with pytest.raises(SearchProviderAttemptError) as caught:
            run(
                SearchProviderExecutor(
                    deepseek_client_factory=lambda *_: client
                ).execute(
                    deepseek_candidate(),
                    SearchRequest.from_body({}, [("q", WebSearchSettings())]),
                    request_budget=budget,
                )
            )
        assert caught.value.category is expected
        assert caught.value.quota_exhausted is quota
    assert budget.external_calls == 1
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "signal",
    [
        asyncio.CancelledError("cancel"),
        KeyboardInterrupt("keyboard"),
        SystemExit("exit"),
        MemoryError("memory"),
    ],
)
def test_deepseek_control_signals_propagate_identity_without_retry(signal):
    client = FakeDeepSeekClient(signal)
    with pytest.raises(type(signal)) as caught:
        run(
            SearchProviderExecutor(deepseek_client_factory=lambda *_: client).execute(
                deepseek_candidate(),
                SearchRequest.from_body({}, [("q", WebSearchSettings())]),
            )
        )
    assert caught.value is signal
    assert len(client.calls) == 1


def test_deepseek_runtime_integration_does_not_import_offline_harness_helpers():
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/codex_rosetta").rglob("*.py")
    )
    assert "deepseek_search_evidence" not in combined
    assert "deepseek_web_search_smoke" not in combined


def test_self_hosted_replays_all_queries_and_merges_results():
    client = FakeSearch(
        [{"output": "a", "results": [{"title": "A"}]}, {"output": "b", "results": []}]
    )
    request = SearchRequest.from_body(
        {"query": "original", "nested": {"x": 1}},
        [("a", WebSearchSettings()), ("b", WebSearchSettings())],
    )
    result = run(
        SearchProviderExecutor(self_hosted_client=client).execute(
            SelfHostedSearchProviderCandidate("row", "self_hosted_google"), request
        )
    )
    assert result["output"] == "a\n\nb"
    assert result["results"] == [{"title": "A"}]
    assert request.body == {"query": "original", "nested": {"x": 1}}


def test_local_bridge_results_only_are_normalized_for_one_and_many_queries():
    client = FakeSearch([{"results": [{"title": "A"}]}, {"results": [{"title": "B"}]}])
    request = SearchRequest.from_body(
        {}, [("a", WebSearchSettings()), ("b", WebSearchSettings())]
    )
    result = run(
        SearchProviderExecutor(self_hosted_client=client).execute(
            SelfHostedSearchProviderCandidate("row", "self_hosted_google"), request
        )
    )
    assert result["output"]
    assert result["results"] == [{"title": "A"}, {"title": "B"}]


def test_responses_rejects_invalid_encrypted_output_and_result_values():
    async def invalid_encrypted(candidate, body):
        del candidate, body
        return {"output": "ok", "encrypted_output": 123}

    async def invalid_results(candidate, body):
        del candidate, body
        return {"output": "ok", "results": [{"bad": object()}]}

    candidate = configured_responses_candidate()
    request = SearchRequest.from_body({})
    with pytest.raises(SearchProviderAttemptError):
        run(
            SearchProviderExecutor(responses_client=invalid_encrypted).execute(
                candidate, request
            )
        )
    with pytest.raises(SearchProviderAttemptError):
        run(
            SearchProviderExecutor(responses_client=invalid_results).execute(
                candidate, request
            )
        )


def test_responses_single_query_accepts_formal_search_response_without_query_outputs():
    async def call(candidate, body):
        del candidate, body
        return {
            "output": "GPT answer",
            "results": [{"title": "Result"}],
            "encrypted_output": "opaque",
        }

    candidate = configured_responses_candidate()
    coordinator = SearchProviderChainCoordinator()
    result = run(
        coordinator.run(
            (candidate,),
            lambda admitted: SearchProviderExecutor(responses_client=call).execute(
                admitted,
                SearchRequest.from_body({}, [("q", WebSearchSettings())]),
            ),
        )
    )

    assert result["output"] == "GPT answer"
    assert result["results"] == [{"title": "Result"}]
    assert not coordinator.is_cooling(candidate)


def test_local_unavailable_is_request_failover():
    request = SearchRequest.from_body({}, [("q", WebSearchSettings())])
    with pytest.raises(SearchProviderRequestFailover) as caught:
        run(
            SearchProviderExecutor().execute(
                SelfHostedSearchProviderCandidate("row", "self_hosted_google"), request
            )
        )
    assert caught.value.reason is SearchProviderRequestFailoverReason.LOCAL_UNAVAILABLE


def test_failed_query_does_not_publish_partial_result():
    client = FakeSearch(
        [
            {"output": "first", "results": []},
            SearchProviderAttemptError(SearchProviderAttemptCategory.CONNECTION_ERROR),
        ]
    )
    request = SearchRequest.from_body(
        {}, [("a", WebSearchSettings()), ("b", WebSearchSettings())]
    )
    with pytest.raises(SearchProviderAttemptError):
        run(
            SearchProviderExecutor(self_hosted_client=client).execute(
                SelfHostedSearchProviderCandidate("row", "self_hosted_google"), request
            )
        )


def test_responses_overrides_model_only_and_validates_shape():
    seen = []

    async def call(candidate, body):
        seen.append((candidate, body))
        return {"output": "ok", "results": []}

    body = {
        "model": "caller",
        "input": [{"role": "user", "content": "q"}],
        "tools": [{"type": "x"}],
    }
    candidate = configured_responses_candidate()
    result = run(
        SearchProviderExecutor(responses_client=call).execute(
            candidate, SearchRequest.from_body(body)
        )
    )
    assert result["output"] == "ok"
    assert seen[0][1] == {**body, "model": "search-model"}
    assert body["model"] == "caller"


def test_gpt_passthrough_captures_complete_body_url_model_and_result():
    payload = {"output": "complete", "results": [], "opaque": {"kept": True}}
    transport = SimpleNamespace(
        send_passthrough=AsyncMock(
            return_value=UpstreamResponse(
                status_code=200, body=payload, raw_content=b"{}"
            )
        )
    )
    provider_info = SimpleNamespace(
        base_url="https://example.invalid/v1",
        credential_values=("secret",),
    )
    candidate = configured_responses_candidate()
    object.__setattr__(candidate, "provider_info", provider_info)
    body = {
        "model": "caller",
        "input": [{"role": "user", "content": "q"}],
        "commands": [{"type": "search_query", "query": "q"}],
        "gpt_only": {"preserve": [1, 2]},
    }

    result = run(
        SearchProviderExecutor(
            responses_transport=cast(UpstreamTransport, transport)
        ).execute(candidate, SearchRequest.from_body(body))
    )

    assert result is payload
    _, url, sent_body = transport.send_passthrough.await_args.args[:3]
    assert url == "https://example.invalid/v1/alpha/search"
    assert sent_body == {**body, "model": "search-model"}


def test_tavily_local_adapter_captures_only_canonical_queries_and_settings():
    client = FakeSearch([{"output": "ok", "results": []}])
    settings = WebSearchSettings(max_results=3, include_domains=("example.com",))
    request = SearchRequest.from_body(
        {
            "commands": [{"type": "unknown", "payload": "do not forward"}],
            "gpt_only": {"nested": True},
        },
        [("canonical query", settings)],
    )

    result = run(
        SearchProviderExecutor(tavily_client=client).execute(
            TavilySearchProviderCandidate("row", api_key="secret"), request
        )
    )

    assert result["output"] == "ok"
    assert client.calls == [("canonical query", settings)]


def test_self_hosted_local_adapter_captures_all_queries_without_request_body():
    client = FakeSearch(
        [{"output": "first", "results": []}, {"output": "second", "results": []}]
    )
    first = WebSearchSettings(max_results=1)
    second = WebSearchSettings(max_results=2, include_domains=("example.org",))
    request = SearchRequest.from_body(
        {"commands": [{"type": "unknown"}], "model": "gpt-only"},
        [("first", first), ("second", second)],
    )

    result = run(
        SearchProviderExecutor(self_hosted_client=client).execute(
            SelfHostedSearchProviderCandidate("row", "self_hosted_google"), request
        )
    )

    assert result["output"] == "first\n\nsecond"
    assert client.calls == [("first", first), ("second", second)]


def test_contract_mismatch_is_terminal_and_does_not_cool_candidate():
    client = FakeSearch([{"output": "should not run", "results": []}])
    candidate = TavilySearchProviderCandidate("row", api_key="secret")
    object.__setattr__(candidate, "contract", GPT_PASSTHROUGH_CONTRACT)
    coordinator = SearchProviderChainCoordinator()
    request = SearchRequest.from_body({}, [("q", WebSearchSettings())])

    with pytest.raises(SearchProviderTerminalError):
        run(
            coordinator.run(
                (candidate,),
                lambda admitted: SearchProviderExecutor(tavily_client=client).execute(
                    admitted, request
                ),
            )
        )

    assert client.calls == []
    assert not coordinator.is_cooling(candidate)


def test_unknown_candidate_is_terminal_without_external_call():
    request = SearchRequest.from_body({}, [("q", WebSearchSettings())])
    candidate = object()
    with pytest.raises(SearchProviderTerminalError):
        run(
            SearchProviderExecutor().execute(
                cast(SearchProviderCandidate, candidate), request
            )
        )


@pytest.mark.parametrize(
    ("missing", "search_request"),
    [
        (
            SearchProviderCapability.DOMAIN_FILTER,
            SearchRequest.from_body(
                {}, [("q", WebSearchSettings(include_domains=("example.com",)))]
            ),
        ),
        (
            SearchProviderCapability.MULTI_QUERY,
            SearchRequest.from_body(
                {}, [("a", WebSearchSettings()), ("b", WebSearchSettings())]
            ),
        ),
        (
            SearchProviderCapability.NORMALIZED_RESULTS,
            SearchRequest.from_body({}, [("q", WebSearchSettings())]),
        ),
        (
            SearchProviderCapability.REFERENCE_STORAGE,
            SearchRequest.from_body(
                {}, [("q", WebSearchSettings())], requires_reference_storage=True
            ),
        ),
    ],
)
def test_local_missing_capability_is_terminal_before_budget_or_client(
    missing: SearchProviderCapability,
    search_request: SearchRequest,
) -> None:
    candidate = TavilySearchProviderCandidate("row", api_key="secret")
    capabilities = frozenset(
        {
            SearchProviderCapability.SEARCH_QUERY,
            SearchProviderCapability.DOMAIN_FILTER,
            SearchProviderCapability.MULTI_QUERY,
            SearchProviderCapability.NORMALIZED_RESULTS,
            SearchProviderCapability.REFERENCE_STORAGE,
        }
        - {missing}
    )
    object.__setattr__(
        candidate,
        "contract",
        SearchProviderContract.create(
            SearchProviderFamily.TAVILY_LOCAL,
            SearchProviderExecutionMode.LOCAL_QUERY_ADAPTER,
            capabilities,
        ),
    )
    client = FakeSearch([{"output": "must not run", "results": []}])
    budget = SearchProviderRequestBudget()

    with pytest.raises(SearchProviderTerminalError):
        run(
            SearchProviderExecutor(tavily_client=client).execute(
                candidate, search_request, request_budget=budget
            )
        )

    assert client.calls == []
    assert budget.external_calls == 0


def test_responses_terminal_status_is_typed():
    async def call(candidate, body):
        del candidate, body
        raise SearchProviderTerminalError("Search request rejected")

    candidate = configured_responses_candidate()
    with pytest.raises(SearchProviderTerminalError):
        run(
            SearchProviderExecutor(responses_client=call).execute(
                candidate, SearchRequest.from_body({})
            )
        )


@pytest.mark.parametrize("status", [401, 429, 302])
def test_responses_non_success_statuses_are_http_attempt_failures(status):
    transport = SimpleNamespace(
        send_passthrough=AsyncMock(
            return_value=UpstreamResponse(
                status_code=status,
                body=None,
                raw_content=b'{"output":"ignored"}',
            )
        )
    )
    provider_info = SimpleNamespace(
        base_url="https://example.invalid/v1",
        credential_values=("secret",),
    )
    candidate = configured_responses_candidate()
    object.__setattr__(candidate, "provider_info", provider_info)
    with pytest.raises(SearchProviderAttemptError) as caught:
        run(
            SearchProviderExecutor(
                responses_transport=cast(UpstreamTransport, transport)
            ).execute(candidate, SearchRequest.from_body({}))
        )
    assert caught.value.category is SearchProviderAttemptCategory.HTTP_ERROR


def test_local_error_mapping_is_whitelisted_and_unknown_is_propagated():
    with pytest.raises(SearchProviderAttemptError) as caught:
        _map_local_error(
            TavilyRequestError(TavilyRequestErrorCategory.HTTP_ERROR, status_code=401)
        )
    assert caught.value.category is SearchProviderAttemptCategory.HTTP_ERROR
    with pytest.raises(SearchProviderRequestFailover):
        _map_local_error(
            WebRunSidecarSearchError(WebRunSidecarSearchErrorCategory.UNAVAILABLE)
        )
    unknown = RuntimeError("unknown")
    with pytest.raises(RuntimeError) as caught_unknown:
        _map_local_error(unknown)
    assert caught_unknown.value is unknown


def test_responses_request_budget_failure_propagates():
    provider_info = SimpleNamespace(
        base_url="https://example.invalid/v1",
        credential_values=("secret",),
    )
    candidate = configured_responses_candidate()
    object.__setattr__(candidate, "provider_info", provider_info)
    transport = SimpleNamespace(send_passthrough=AsyncMock())
    budget = SearchProviderRequestBudget(max_external_calls=1)

    async def consume_budget() -> None:
        return None

    run(budget.run_external_call(consume_budget))
    with pytest.raises(SearchProviderBudgetExceeded) as caught:
        run(
            SearchProviderExecutor(
                responses_transport=cast(UpstreamTransport, transport)
            ).execute(
                candidate,
                SearchRequest.from_body({}),
                request_budget=budget,
            )
        )
    assert (
        caught.value.reason is SearchProviderBudgetReason.EXTERNAL_CALL_LIMIT_EXCEEDED
    )
    transport.send_passthrough.assert_not_awaited()
