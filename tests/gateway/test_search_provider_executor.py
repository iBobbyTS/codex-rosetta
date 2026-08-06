from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from codex_rosetta.gateway.search_provider_candidates import (
    ConfiguredResponsesSearchProviderCandidate,
    SelfHostedSearchProviderCandidate,
)
from codex_rosetta.gateway.search_provider_chain import (
    SearchProviderAttemptCategory,
    SearchProviderAttemptError,
    SearchProviderBudgetExceeded,
    SearchProviderBudgetReason,
    SearchProviderRequestFailover,
    SearchProviderRequestFailoverReason,
)
from codex_rosetta.gateway.search_provider_executor import (
    SearchProviderExecutor,
    SearchProviderTerminalError,
    SearchRequest,
    _map_local_error,
)
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

    candidate = object.__new__(ConfiguredResponsesSearchProviderCandidate)
    object.__setattr__(candidate, "responses_model", "m")
    object.__setattr__(candidate, "responses_provider", "p")
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
    candidate = object.__new__(ConfiguredResponsesSearchProviderCandidate)
    object.__setattr__(candidate, "responses_model", "search-model")
    object.__setattr__(candidate, "responses_provider", "p")
    result = run(
        SearchProviderExecutor(responses_client=call).execute(
            candidate, SearchRequest.from_body(body)
        )
    )
    assert result["output"] == "ok"
    assert seen[0][1] == {**body, "model": "search-model"}
    assert body["model"] == "caller"


def test_responses_terminal_status_is_typed():
    async def call(candidate, body):
        del candidate, body
        raise SearchProviderTerminalError("Search request rejected")

    candidate = object.__new__(ConfiguredResponsesSearchProviderCandidate)
    object.__setattr__(candidate, "responses_model", "m")
    object.__setattr__(candidate, "responses_provider", "p")
    with pytest.raises(SearchProviderTerminalError):
        run(
            SearchProviderExecutor(responses_client=call).execute(
                candidate, SearchRequest.from_body({})
            )
        )


@pytest.mark.parametrize("status", [401, 429, 302])
def test_responses_non_success_statuses_are_http_attempt_failures(monkeypatch, status):
    async def bounded(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(status_code=status, content=b'{"output":"ignored"}')

    monkeypatch.setattr(
        "codex_rosetta.gateway.search_provider_executor.request_bounded_response",
        bounded,
    )
    provider_info = SimpleNamespace(
        credential_values=("secret",),
        auth_headers=lambda: {},
        upstream_url=lambda model: "https://example.invalid/responses",
    )
    candidate = object.__new__(ConfiguredResponsesSearchProviderCandidate)
    object.__setattr__(candidate, "responses_model", "m")
    object.__setattr__(candidate, "responses_provider", "p")
    object.__setattr__(candidate, "provider_info", provider_info)
    with pytest.raises(SearchProviderAttemptError) as caught:
        run(SearchProviderExecutor().execute(candidate, SearchRequest.from_body({})))
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


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("transport setup"),
        SearchProviderBudgetExceeded(SearchProviderBudgetReason.DEADLINE_EXCEEDED),
    ],
)
def test_responses_transport_unknown_and_budget_failures_propagate(
    monkeypatch, failure
):
    async def bounded(*args, **kwargs):
        del args, kwargs
        raise failure

    monkeypatch.setattr(
        "codex_rosetta.gateway.search_provider_executor.request_bounded_response",
        bounded,
    )
    provider_info = SimpleNamespace(
        credential_values=("secret",),
        auth_headers=lambda: {},
        upstream_url=lambda model: "https://example.invalid/responses",
    )
    candidate = object.__new__(ConfiguredResponsesSearchProviderCandidate)
    object.__setattr__(candidate, "responses_model", "m")
    object.__setattr__(candidate, "responses_provider", "p")
    object.__setattr__(candidate, "provider_info", provider_info)
    with pytest.raises(type(failure)) as caught:
        run(SearchProviderExecutor().execute(candidate, SearchRequest.from_body({})))
    assert caught.value is failure
