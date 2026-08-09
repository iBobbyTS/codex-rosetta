"""Contract tests for the local Codex standalone-search bridge."""

from __future__ import annotations

import asyncio
import copy
import traceback
from datetime import datetime, timezone
from typing import Any

import pytest

from codex_rosetta.gateway.codex_page import OpenedPage
from codex_rosetta.gateway.codex_search import (
    CodexSearchProviderExecutionError,
    CodexSearchInvalidRequest,
    CodexSearchNotImplemented,
    execute_local_codex_search,
    should_use_local_codex_search,
)
from codex_rosetta.gateway.downstream_errors import CodexRosettaBlockedError
from codex_rosetta.gateway.deepseek_responses_search import DeepSeekSearchResult
from codex_rosetta.gateway.search_provider_candidates import (
    DeepSeekNativeResponsesSearchProviderCandidate,
    TavilySearchProviderCandidate,
)
from codex_rosetta.gateway.search_provider_chain import (
    SearchProviderBudgetExceeded,
    SearchProviderChainCoordinator,
    SearchProviderRequestBudget,
)
from codex_rosetta.gateway.search_provider_executor import SearchProviderExecutor
from codex_rosetta.gateway.transport._base import (
    UpstreamContentEncodingError,
    UpstreamCredentialCollisionError,
    UpstreamResponseContractError,
    UpstreamResponseTooLargeError,
)
from codex_rosetta.gateway.codex_search_references import (
    CodexSearchReferenceScope,
    CodexSearchReferenceStore,
)
from codex_rosetta.gateway.web_run_sidecar import (
    WebRunSidecarInvalidRequest,
    WebRunSidecarSearchError,
    WebRunSidecarSearchErrorCategory,
)
from codex_rosetta.gateway.web_search import (
    TavilyCredentialCollisionError,
    TavilyRequestError,
    TavilyRequestErrorCategory,
    WebSearchSettings,
)


class _OtherBlockedError(CodexRosettaBlockedError, RuntimeError):
    """A blocked subtype not known to the search bridge."""


def _exception_graph(root: BaseException) -> list[BaseException]:
    pending = [root]
    seen: set[int] = set()
    graph: list[BaseException] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        graph.append(current)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return graph


class _FakeTavilyClient:
    def __init__(self, *, url: str = "https://docs.python.org/3/") -> None:
        self.calls: list[tuple[str, WebSearchSettings]] = []
        self.url = url

    async def search(
        self,
        query: str,
        *,
        settings: WebSearchSettings,
    ) -> dict[str, Any]:
        self.calls.append((query, settings))
        return {
            "answer": f"Answer for {query}",
            "results": [
                {
                    "title": "Python documentation",
                    "url": self.url,
                    "content": "The official Python 3 documentation.",
                    "score": 0.99,
                }
            ],
        }


class _FakePageClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def open(self, url: str) -> OpenedPage:
        self.calls.append(url)
        return OpenedPage(
            url=url,
            title="Python 3 Documentation",
            lines=("Overview", "What's new", "Tutorial", "Library Reference"),
        )


class _FakeBrowserClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def execute(
        self,
        *,
        session_id: str,
        operation: str,
        arguments: dict[str, Any],
    ) -> str:
        self.calls.append((session_id, operation, arguments))
        return f"browser:{operation}:{arguments['ref_id']}"


class _FakeSelfHostedGoogleClient(_FakeBrowserClient):
    def __init__(self) -> None:
        super().__init__()
        self.search_calls: list[tuple[str, WebSearchSettings]] = []

    async def search(
        self,
        query: str,
        *,
        settings: WebSearchSettings,
    ) -> dict[str, Any]:
        self.search_calls.append((query, settings))
        return {
            "results": [
                {
                    "title": "Python",
                    "url": "https://www.python.org/",
                    "content": "The Python programming language.",
                }
            ]
        }


class _FakeDeepSeekClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, query: str, **kwargs: Any) -> DeepSeekSearchResult:
        self.calls.append((query, kwargs))
        return DeepSeekSearchResult(
            output="DeepSeek answer",
            results=(
                {
                    "title": "Python documentation",
                    "url": "https://docs.python.org/3/",
                    "content": "Official Python documentation.",
                },
            ),
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


def _deepseek_candidate() -> DeepSeekNativeResponsesSearchProviderCandidate:
    provider_info = type(
        "ProviderInfoStub",
        (),
        {
            "name": "deepseek",
            "base_url": "https://api.deepseek.com",
            "credential_values": ("deepseek-secret",),
        },
    )()
    return DeepSeekNativeResponsesSearchProviderCandidate(
        row_id="deepseek-row",
        deepseek_provider="official-deepseek",
        provider_info=provider_info,
        identity="deepseek-identity",
    )


def test_deepseek_chain_publishes_answer_references_attribution_and_cache():
    candidate = _deepseek_candidate()
    client = _FakeDeepSeekClient()
    executor = SearchProviderExecutor(deepseek_client_factory=lambda *_: client)
    coordinator = SearchProviderChainCoordinator()
    store = CodexSearchReferenceStore()
    query = "private-query-marker"
    body = _body({"search_query": [{"q": query}]})

    first = asyncio.run(
        execute_local_codex_search(
            body,
            {},
            reference_store=store,
            principal_id="client-a",
            search_candidates=(candidate,),
            search_coordinator=coordinator,
            search_executor=executor,
        )
    )
    second = asyncio.run(
        execute_local_codex_search(
            body,
            {},
            reference_store=store,
            principal_id="client-a",
            search_candidates=(candidate,),
            search_coordinator=coordinator,
            search_executor=executor,
        )
    )

    assert client.calls == [
        (
            query,
            {
                "model": "deepseek-v4-flash",
                "max_output_tokens": 1024,
                "citation_limit": 5,
            },
        )
    ]
    assert "DeepSeek answer" in first.output
    assert "[turn0search0] Python documentation" in first.output
    assert first.search_reference_count == 1
    assert first.search_cache_hit is False
    assert second.output == first.output
    assert second.search_cache_hit is True
    assert first.attribution is not None
    assert first.attribution.provider_name == "official-deepseek"
    assert first.attribution.target_provider == "openai_responses"
    assert first.attribution.model == "deepseek-v4-flash"
    trace = first.trace_summary()
    assert trace["executor"] == "deepseek_native_responses"
    assert trace["candidate_id"] == "deepseek-row"
    assert trace["candidate_provider"] == "deepseek_native_responses"
    rendered = repr(trace)
    assert "deepseek-secret" not in rendered
    assert "deepseek-identity" not in rendered
    assert query not in rendered


def test_q_only_allowed_domains_rejects_before_chain_and_reference_side_effects():
    class NeverRunCoordinator:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            raise AssertionError("candidate chain must not run")

    coordinator = NeverRunCoordinator()
    client = _FakeTavilyClient()
    store = CodexSearchReferenceStore()
    budget = SearchProviderRequestBudget()
    candidates = (
        TavilySearchProviderCandidate(
            "tavily-row", api_key="tvly-test", identity="tavily-identity"
        ),
        _deepseek_candidate(),
    )

    with pytest.raises(
        CodexSearchNotImplemented, match="settings.filters.allowed_domains"
    ):
        asyncio.run(
            execute_local_codex_search(
                _body(
                    {"search_query": [{"q": "python"}]},
                    settings={"filters": {"allowed_domains": ["python.org"]}},
                ),
                {},
                client=client,
                reference_store=store,
                principal_id="client-a",
                request_budget=budget,
                search_candidates=candidates,
                search_coordinator=coordinator,
            )
        )

    assert coordinator.calls == 0
    assert client.calls == []
    assert budget.external_calls == 0
    assert (
        store.provider_affinity(CodexSearchReferenceScope("client-a", "search-session"))
        is None
    )


def _body(commands: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "id": "search-session",
        "model": "gateway-model",
        "commands": commands,
        **extra,
    }


def test_search_query_uses_tavily_with_supported_filters() -> None:
    client = _FakeTavilyClient()
    result = asyncio.run(
        execute_local_codex_search(
            _body(
                {
                    "search_query": [
                        {
                            "q": "official Python documentation",
                            "domains": ["docs.python.org", "python.org"],
                        }
                    ],
                    "response_length": "long",
                },
                settings={
                    "search_context_size": "low",
                    "filters": {"allowed_domains": ["docs.python.org"]},
                    "allowed_callers": ["direct"],
                    "external_web_access": True,
                },
            ),
            {"tavily_api_key": "tvly-test"},
            client=client,
        )
    )

    assert client.calls == [
        (
            "official Python documentation",
            WebSearchSettings(
                max_results=8,
                search_depth="advanced",
                include_domains=("docs.python.org",),
            ),
        )
    ]
    assert result.search_count == 1
    assert result.open_count == 0
    assert result.time_count == 0
    assert result.tavily_result_count == 1
    assert "https://docs.python.org/3/" in result.output
    assert result.response_body() == {
        "output": result.output,
        "results": [
            {
                "type": "text_result",
                "title": "Python documentation",
                "url": "https://docs.python.org/3/",
                "content": "The official Python 3 documentation.",
                "score": 0.99,
            }
        ],
    }


def test_time_uses_python_without_tavily() -> None:
    result = asyncio.run(
        execute_local_codex_search(
            _body(
                {
                    "time": [
                        {"utc_offset": "+03:00"},
                        {"utc_offset": "-05:30"},
                    ]
                }
            ),
            {},
            now=lambda: datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc),
        )
    )

    assert result.search_count == 0
    assert result.open_count == 0
    assert result.time_count == 2
    assert result.response_body() == {"output": result.output}
    assert "+03:00: 2026-07-12T15:00:00+03:00" in result.output
    assert "-05:30: 2026-07-12T06:30:00-05:30" in result.output


def test_search_query_preserves_explicit_empty_structured_results() -> None:
    class EmptySearchClient:
        async def search(
            self,
            query: str,
            *,
            settings: WebSearchSettings,
        ) -> dict[str, Any]:
            del query, settings
            return {"results": []}

    result = asyncio.run(
        execute_local_codex_search(
            _body({"search_query": [{"q": "nothing"}]}),
            {"tavily_api_key": "tvly-test"},
            client=EmptySearchClient(),
        )
    )

    assert result.response_body() == {"output": result.output, "results": []}


def test_each_query_uses_budget_and_second_failure_is_atomic() -> None:
    body = _body({"search_query": [{"q": "one"}, {"q": "two"}]})
    original = copy.deepcopy(body)
    client = _FakeTavilyClient()
    budget = SearchProviderRequestBudget(max_external_calls=1)

    with pytest.raises(SearchProviderBudgetExceeded):
        asyncio.run(
            execute_local_codex_search(
                body,
                {"tavily_api_key": "key"},
                client=client,
                request_budget=budget,
            )
        )

    assert [query for query, _settings in client.calls] == ["one"]
    assert budget.external_calls == 1
    assert body == original


def test_provider_failure_has_only_a_safe_typed_cause() -> None:
    secret = "provider-secret-detail"
    raw_failures: list[BaseException] = []

    class FailingClient:
        async def search(self, query: str, *, settings: WebSearchSettings):
            del query, settings
            try:
                raise ValueError(secret)
            except ValueError as cause:
                raw_failure = RuntimeError(secret)
                raw_failures.extend((cause, raw_failure))
                raise raw_failure from cause

    with pytest.raises(CodexSearchProviderExecutionError) as caught:
        asyncio.run(
            execute_local_codex_search(
                _body({"search_query": [{"q": "one"}]}),
                {"tavily_api_key": "key"},
                client=FailingClient(),
            )
        )

    graph = _exception_graph(caught.value)
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert not {id(error) for error in graph} & {id(error) for error in raw_failures}
    assert secret not in "".join(repr(error) for error in graph)
    assert secret not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    "failure",
    [
        TavilyRequestError(TavilyRequestErrorCategory.CONNECTION_ERROR),
        WebRunSidecarSearchError(WebRunSidecarSearchErrorCategory.CONNECTION_ERROR),
    ],
)
def test_typed_provider_failure_preserves_safe_cause(failure: Exception) -> None:
    class FailingClient:
        async def search(self, query: str, *, settings: WebSearchSettings):
            del query, settings
            raise failure

    with pytest.raises(CodexSearchProviderExecutionError) as caught:
        asyncio.run(
            execute_local_codex_search(
                _body({"search_query": [{"q": "one"}]}),
                {"tavily_api_key": "key"},
                client=FailingClient(),
            )
        )

    assert caught.value.__cause__ is failure
    assert set(_exception_graph(caught.value)) == {caught.value, failure}


@pytest.mark.parametrize(
    "failure",
    [
        asyncio.CancelledError(),
        TavilyCredentialCollisionError("blocked"),
        _OtherBlockedError("blocked by another policy owner"),
        UpstreamResponseTooLargeError("bounded response overflow"),
        UpstreamContentEncodingError("compressed response blocked"),
        UpstreamCredentialCollisionError("credential collision blocked"),
        UpstreamResponseContractError("response contract blocked"),
        MemoryError("allocation failed"),
        SystemExit("fatal"),
    ],
)
def test_local_search_propagates_cancel_and_safety_failures(
    failure: BaseException,
) -> None:
    class FailingClient:
        async def search(self, query: str, *, settings: WebSearchSettings):
            del query, settings
            raise failure

    with pytest.raises(type(failure)) as caught:
        asyncio.run(
            execute_local_codex_search(
                _body({"search_query": [{"q": "one"}]}),
                {"tavily_api_key": "key"},
                client=FailingClient(),
            )
        )

    assert caught.value is failure


def test_open_direct_url_returns_line_addressable_static_page() -> None:
    page_client = _FakePageClient()
    result = asyncio.run(
        execute_local_codex_search(
            _body(
                {
                    "open": [
                        {
                            "ref_id": "https://docs.python.org/3/",
                            "lineno": 2,
                        }
                    ]
                }
            ),
            {},
            page_client=page_client,
        )
    )

    assert page_client.calls == ["https://docs.python.org/3/"]
    assert result.search_count == 0
    assert result.open_count == 1
    assert result.time_count == 0
    assert "Title: Python 3 Documentation" in result.output
    assert "L2: Tutorial" in result.output
    assert "L0: Overview" not in result.output


def test_search_result_reference_can_be_opened_in_the_same_session() -> None:
    store = CodexSearchReferenceStore()
    search_result = asyncio.run(
        execute_local_codex_search(
            _body({"search_query": [{"q": "python"}]}),
            {"tavily_api_key": "tvly-test"},
            client=_FakeTavilyClient(),
            reference_store=store,
            principal_id="client-a",
        )
    )
    page_client = _FakePageClient()
    open_result = asyncio.run(
        execute_local_codex_search(
            _body({"open": [{"ref_id": "turn0search0"}]}),
            {},
            page_client=page_client,
            reference_store=store,
            principal_id="client-a",
        )
    )

    assert "[turn0search0] Python documentation" in search_result.output
    assert page_client.calls == ["https://docs.python.org/3/"]
    assert "Title: Python 3 Documentation" in open_result.output
    assert open_result.stored_reference_open_count == 1


def test_sidecar_executes_open_click_find_and_pdf_screenshot() -> None:
    store = CodexSearchReferenceStore()
    asyncio.run(
        execute_local_codex_search(
            _body({"search_query": [{"q": "python"}]}),
            {"tavily_api_key": "tvly-test"},
            client=_FakeTavilyClient(),
            reference_store=store,
            principal_id="client-a",
        )
    )
    browser = _FakeBrowserClient()

    result = asyncio.run(
        execute_local_codex_search(
            _body(
                {
                    "open": [{"ref_id": "turn0search0", "lineno": 2}],
                    "click": [{"ref_id": "turn1fetch0", "id": 7}],
                    "find": [{"ref_id": "turn1fetch0", "pattern": "Python"}],
                    "screenshot": [
                        {"ref_id": "https://example.com/file.pdf", "pageno": 3}
                    ],
                }
            ),
            {},
            browser_client=browser,
            reference_store=store,
            principal_id="client-a",
        )
    )

    session_ids = {call[0] for call in browser.calls}
    assert len(session_ids) == 1
    assert len(next(iter(session_ids))) == 64
    assert browser.calls[0][1:] == (
        "open",
        {"ref_id": "https://docs.python.org/3/", "lineno": 2},
    )
    assert browser.calls[1][1:] == (
        "click",
        {"ref_id": "turn1fetch0", "id": 7},
    )
    assert browser.calls[2][1:] == (
        "find",
        {"ref_id": "turn1fetch0", "pattern": "Python"},
    )
    assert browser.calls[3][1:] == (
        "screenshot",
        {"ref_id": "https://example.com/file.pdf", "pageno": 3},
    )
    assert result.open_count == 1
    assert result.browser_open_count == 1
    assert result.click_count == 1
    assert result.find_count == 1
    assert result.screenshot_count == 1
    assert result.trace_summary()["executor"] == "tavily_python_web_run_sidecar"


def test_sidecar_invalid_reference_maps_to_codex_invalid_request() -> None:
    class InvalidBrowser:
        async def execute(self, **kwargs: Any) -> str:
            del kwargs
            raise WebRunSidecarInvalidRequest("Unknown or expired page reference")

    with pytest.raises(CodexSearchInvalidRequest, match="Unknown or expired"):
        asyncio.run(
            execute_local_codex_search(
                _body({"click": [{"ref_id": "turn9fetch0", "id": 1}]}),
                {},
                browser_client=InvalidBrowser(),
            )
        )


@pytest.mark.parametrize(
    ("principal_id", "session_id"),
    [("client-b", "search-session"), ("client-a", "other-session")],
)
def test_stored_reference_fails_closed_outside_its_owner_session(
    principal_id: str,
    session_id: str,
) -> None:
    store = CodexSearchReferenceStore()
    asyncio.run(
        execute_local_codex_search(
            _body({"search_query": [{"q": "python"}]}),
            {"tavily_api_key": "tvly-test"},
            client=_FakeTavilyClient(),
            reference_store=store,
            principal_id="client-a",
        )
    )

    body = _body({"open": [{"ref_id": "turn0search0"}]})
    body["id"] = session_id
    with pytest.raises(CodexSearchInvalidRequest, match="Unknown search reference"):
        asyncio.run(
            execute_local_codex_search(
                body,
                {},
                page_client=_FakePageClient(),
                reference_store=store,
                principal_id=principal_id,
            )
        )


def test_retried_search_reuses_results_and_reference_ids() -> None:
    store = CodexSearchReferenceStore()
    client = _FakeTavilyClient()
    body = _body({"search_query": [{"q": "python"}]})

    first = asyncio.run(
        execute_local_codex_search(
            body,
            {"tavily_api_key": "tvly-test"},
            client=client,
            reference_store=store,
            principal_id="client-a",
        )
    )
    second = asyncio.run(
        execute_local_codex_search(
            body,
            {"tavily_api_key": "tvly-test"},
            client=client,
            reference_store=store,
            principal_id="client-a",
        )
    )

    assert first.output == second.output
    assert first.search_cache_hit is False
    assert second.search_cache_hit is True
    assert len(client.calls) == 1


def test_parallel_searches_allocate_distinct_turn_references() -> None:
    store = CodexSearchReferenceStore()

    async def run() -> list[str]:
        results = await asyncio.gather(
            execute_local_codex_search(
                _body({"search_query": [{"q": "python one"}]}),
                {"tavily_api_key": "tvly-test"},
                client=_FakeTavilyClient(url="https://docs.python.org/3/"),
                reference_store=store,
                principal_id="client-a",
            ),
            execute_local_codex_search(
                _body({"search_query": [{"q": "python two"}]}),
                {"tavily_api_key": "tvly-test"},
                client=_FakeTavilyClient(url="https://docs.python.org/3/tutorial/"),
                reference_store=store,
                principal_id="client-a",
            ),
        )
        return [result.output for result in results]

    outputs = asyncio.run(run())
    assert any("[turn0search0]" in output for output in outputs)
    assert any("[turn1search0]" in output for output in outputs)


@pytest.mark.parametrize(
    ("commands", "settings", "feature"),
    [
        ({"click": [{"ref_id": "turn0fetch0", "id": 1}]}, None, "commands.click"),
        (
            {"find": [{"ref_id": "turn0fetch0", "pattern": "Python"}]},
            None,
            "commands.find",
        ),
        ({"image_query": [{"q": "python"}]}, None, "commands.image_query"),
        (
            {"screenshot": [{"ref_id": "turn0view0", "pageno": 0}]},
            None,
            "commands.screenshot",
        ),
        ({"finance": [{"ticker": "AMD", "type": "equity"}]}, None, "commands.finance"),
        ({"weather": [{"location": "Paris"}]}, None, "commands.weather"),
        ({"sports": [{"fn": "standings", "league": "nfl"}]}, None, "commands.sports"),
        (
            {"search_query": [{"q": "python", "recency": 7}]},
            None,
            "commands.search_query[].recency",
        ),
        (
            {"search_query": [{"q": "python"}]},
            {"user_location": {"type": "approximate", "country": "US"}},
            "settings.user_location",
        ),
        (
            {"search_query": [{"q": "python"}]},
            {"filters": {"blocked_domains": ["example.com"]}},
            "settings.filters.blocked_domains",
        ),
        (
            {"search_query": [{"q": "python"}]},
            {"external_web_access": "cached"},
            "settings.external_web_access",
        ),
    ],
)
def test_unsupported_features_fail_before_tavily(
    commands: dict[str, Any],
    settings: dict[str, Any] | None,
    feature: str,
) -> None:
    client = _FakeTavilyClient()
    body = _body(commands)
    if settings is not None:
        body["settings"] = settings

    with pytest.raises(CodexSearchNotImplemented, match=feature.replace("[", r"\[")):
        asyncio.run(
            execute_local_codex_search(
                body,
                {"tavily_api_key": "tvly-test"},
                client=client,
            )
        )

    assert client.calls == []


def test_mixed_supported_and_unsupported_request_is_atomic() -> None:
    client = _FakeTavilyClient()
    page_client = _FakePageClient()
    with pytest.raises(CodexSearchNotImplemented, match="commands.click"):
        asyncio.run(
            execute_local_codex_search(
                _body(
                    {
                        "search_query": [{"q": "python"}],
                        "open": [{"ref_id": "https://docs.python.org/3/"}],
                        "click": [{"ref_id": "turn0fetch0", "id": 1}],
                    }
                ),
                {"tavily_api_key": "tvly-test"},
                client=client,
                page_client=page_client,
            )
        )
    assert client.calls == []
    assert page_client.calls == []


@pytest.mark.parametrize(
    ("commands", "message"),
    [
        ({}, "at least one"),
        ({"search_query": [{"q": ""}]}, "non-empty string"),
        ({"search_query": [{"q": "python"}] * 5}, "at most 4"),
        ({"open": [{"ref_id": "https://example.com", "lineno": -1}]}, "non-negative"),
        ({"time": [{"utc_offset": "+14:30"}]}, "exceeds"),
        ({"time": [{"utc_offset": "UTC"}]}, "must match"),
    ],
)
def test_invalid_requests_are_rejected(commands: dict[str, Any], message: str) -> None:
    with pytest.raises(CodexSearchInvalidRequest, match=message):
        asyncio.run(execute_local_codex_search(_body(commands), {}))


def test_search_without_tavily_key_is_not_implemented() -> None:
    with pytest.raises(CodexSearchNotImplemented, match="Admin > Web Search"):
        asyncio.run(
            execute_local_codex_search(
                _body({"search_query": [{"q": "python"}]}),
                {},
            )
        )


@pytest.mark.parametrize(
    ("provider", "executor"),
    [
        ("self_hosted_google", "google_web_run_sidecar"),
        ("self_hosted_bing", "bing_web_run_sidecar"),
        ("self_hosted_bing_browser", "bing_browser_web_run_sidecar"),
    ],
)
def test_self_hosted_search_uses_web_run_sidecar(provider: str, executor: str) -> None:
    client = _FakeSelfHostedGoogleClient()

    result = asyncio.run(
        execute_local_codex_search(
            _body(
                {"search_query": [{"q": "official Python", "domains": ["python.org"]}]}
            ),
            {"provider": provider, "tavily_api_key": ""},
            client=client,
            browser_client=client,
        )
    )

    assert client.search_calls == [
        (
            "official Python",
            WebSearchSettings(include_domains=("python.org",)),
        )
    ]
    assert "https://www.python.org/" in result.output
    assert result.search_count == 1
    assert result.trace_summary()["executor"] == executor
    assert result.trace_summary()["search_result_count"] == 1
    assert result.trace_summary()["tavily_result_count"] == 0


@pytest.mark.parametrize(
    "provider",
    ["self_hosted_google", "self_hosted_bing", "self_hosted_bing_browser"],
)
def test_self_hosted_search_requires_sidecar(provider: str) -> None:
    with pytest.raises(CodexSearchNotImplemented, match="healthy web-run sidecar"):
        asyncio.run(
            execute_local_codex_search(
                _body({"search_query": [{"q": "python"}]}),
                {"provider": provider, "tavily_api_key": ""},
            )
        )


def test_max_output_tokens_applies_conservative_character_cap() -> None:
    result = asyncio.run(
        execute_local_codex_search(
            _body(
                {"time": [{"utc_offset": "+00:00"}]},
                max_output_tokens=20,
            ),
            {},
            now=lambda: datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc),
        )
    )

    assert len(result.output) == 20


def test_local_bridge_selection_preserves_native_passthrough_without_tavily() -> None:
    search = _body({"search_query": [{"q": "python"}]})
    page = _body({"open": [{"ref_id": "https://docs.python.org/3/"}]})
    clock = _body({"time": [{"utc_offset": "+00:00"}]})

    assert not should_use_local_codex_search(
        search, {}, native_passthrough_available=True
    )
    assert should_use_local_codex_search(
        search,
        {"tavily_api_key": "tvly-test"},
        native_passthrough_available=True,
    )
    assert not should_use_local_codex_search(
        search,
        {"provider": "self_hosted_google"},
        native_passthrough_available=True,
    )
    assert should_use_local_codex_search(
        search,
        {"provider": "self_hosted_google"},
        native_passthrough_available=True,
        browser_available=True,
    )
    assert should_use_local_codex_search(
        search,
        {"provider": "self_hosted_bing"},
        native_passthrough_available=True,
        browser_available=True,
    )
    assert should_use_local_codex_search(
        search,
        {"provider": "self_hosted_bing_browser"},
        native_passthrough_available=True,
        browser_available=True,
    )
    assert should_use_local_codex_search(search, {}, native_passthrough_available=False)
    assert should_use_local_codex_search(page, {}, native_passthrough_available=True)
    assert should_use_local_codex_search(clock, {}, native_passthrough_available=True)
