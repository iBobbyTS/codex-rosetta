from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

from codex_rosetta.gateway.search_provider_candidates import (
    ConfiguredResponsesSearchProviderCandidate,
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
    GPT_PASSTHROUGH_CONTRACT,
    SearchProviderCapability,
    SearchProviderContract,
    SearchProviderExecutionMode,
    SearchProviderFamily,
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
    object.__setattr__(candidate, "responses_model", "search-model")
    object.__setattr__(candidate, "responses_provider", "p")
    object.__setattr__(candidate, "contract", GPT_PASSTHROUGH_CONTRACT)
    return candidate


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
    with pytest.raises(SearchProviderTerminalError):
        run(SearchProviderExecutor().execute(cast(object, object()), request))


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
