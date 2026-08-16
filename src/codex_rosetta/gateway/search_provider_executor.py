"""Typed, provider-neutral execution of one complete web-search request.

The executor deliberately owns no ordering or health state.  Callers can replay
the same request against another candidate after a request-local failure.
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Never, Protocol

from .downstream_errors import CodexRosettaBlockedError
from .deepseek_responses_search import (
    DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN,
    DEEPSEEK_RESPONSES_SEARCH_MODEL,
    DEFAULT_DEEPSEEK_RESPONSES_SEARCH_CITATION_LIMIT,
    DEFAULT_DEEPSEEK_RESPONSES_SEARCH_MAX_OUTPUT_TOKENS,
    DeepSeekResponsesSearchClient,
    DeepSeekSearchError,
    DeepSeekSearchErrorCategory,
    DeepSeekSearchResult,
    normalize_deepseek_responses_origin,
)
from .search_provider_candidates import (
    ConfiguredResponsesSearchProviderCandidate,
    DeepSeekNativeResponsesSearchProviderCandidate,
    SearchProviderCandidate,
    SelfHostedSearchProviderCandidate,
    TavilySearchProviderCandidate,
)
from .search_provider_chain import (
    SearchProviderAttemptCategory,
    SearchProviderAttemptError,
    SearchProviderBudgetExceeded,
    SearchProviderRequestFailover,
    SearchProviderRequestBudget,
)
from .search_provider_contract import (
    DEEPSEEK_NATIVE_RESPONSES_CONTRACT,
    GPT_PASSTHROUGH_CONTRACT,
    SELF_HOSTED_LOCAL_CONTRACT,
    TAVILY_LOCAL_CONTRACT,
    SearchProviderCapability,
    SearchProviderContract,
    SearchProviderExecutionMode,
)
from .transport._base import (
    UpstreamConnectionError,
    UpstreamSafetyError,
    UpstreamTransport,
)
from .transport._retry import _FAILOVER_RETRY_POLICY
from .transport.credential_redaction import CredentialRedactingTransport
from .web_search import (
    TavilyHTTPClient,
    TavilyRequestError,
    TavilyRequestErrorCategory,
    WebSearchSettings,
    format_web_search_result_for_model,
)
from .web_run_sidecar import (
    WebRunCandidateSearchClient,
    WebRunSearchClient,
    WebRunSidecarInvalidRequest,
    WebRunSidecarSearchError,
    WebRunSidecarSearchErrorCategory,
)


class SearchProviderExecutorFailure(StrEnum):
    """Bounded executor failures suitable for metrics and failover."""

    QUOTA = "quota"
    TERMINAL = "terminal"
    INVALID_RESPONSE = "invalid_response"


class SearchProviderTerminalError(RuntimeError):
    """The request is invalid for this provider and must not fail over."""


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """Immutable snapshot of the complete request and its query settings."""

    body: dict[str, Any]
    queries: tuple[tuple[str, WebSearchSettings], ...] = ()
    requires_reference_storage: bool = False

    @classmethod
    def from_body(
        cls,
        body: Mapping[str, Any],
        queries: Sequence[tuple[str, WebSearchSettings]] = (),
        *,
        requires_reference_storage: bool = False,
    ) -> SearchRequest:
        return cls(
            copy.deepcopy(dict(body)),
            tuple(queries),
            requires_reference_storage=requires_reference_storage,
        )


class SearchResponseClient(Protocol):
    async def __call__(
        self,
        candidate: ConfiguredResponsesSearchProviderCandidate,
        body: dict[str, Any],
    ) -> Any: ...


class _DeepSeekSearchClient(Protocol):
    async def execute(
        self,
        query: object,
        *,
        model: object,
        max_output_tokens: object,
        citation_limit: object,
    ) -> DeepSeekSearchResult: ...


class _DeepSeekSearchClientFactory(Protocol):
    def __call__(
        self, credential: str, origin: str, proxy_url: str | None
    ) -> _DeepSeekSearchClient: ...


def _default_deepseek_client_factory(
    credential: str, origin: str, proxy_url: str | None
) -> _DeepSeekSearchClient:
    return DeepSeekResponsesSearchClient(credential, origin=origin, proxy_url=proxy_url)


def _validate_response(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("output"), str):
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.INVALID_RESPONSE)
    if "results" in value and not isinstance(value["results"], list):
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.INVALID_RESPONSE)
    if (
        "encrypted_output" in value
        and value["encrypted_output"] is not None
        and not isinstance(value["encrypted_output"], str)
    ):
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.INVALID_RESPONSE)
    if "results" in value:
        try:
            json.dumps(value["results"])
        except (TypeError, ValueError, OverflowError):  # fmt: skip
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.INVALID_RESPONSE
            ) from None
    return value


def _validate_query_outputs(value: dict[str, Any], expected: int) -> dict[str, Any]:
    """Require one valid response object per requested query."""
    outputs = value.get("query_outputs")
    if not isinstance(outputs, list) or len(outputs) != expected:
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.INVALID_RESPONSE)
    for item in outputs:
        _validate_response(item)
    return value


class SearchProviderExecutor:
    """Execute one admitted search-provider candidate."""

    def __init__(
        self,
        *,
        tavily_client: WebRunSearchClient | None = None,
        self_hosted_client: WebRunSearchClient | None = None,
        candidate_self_hosted_client: WebRunCandidateSearchClient | None = None,
        responses_client: SearchResponseClient | None = None,
        responses_transport: UpstreamTransport | None = None,
        responses_extra_headers: Mapping[str, str] | None = None,
        deepseek_client_factory: _DeepSeekSearchClientFactory | None = None,
        _retry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._tavily_client = tavily_client
        self._self_hosted_client = self_hosted_client
        self._candidate_self_hosted_client = candidate_self_hosted_client
        self._responses_client = responses_client
        self._responses_transport = (
            CredentialRedactingTransport.wrap(responses_transport)
            if responses_transport is not None
            else None
        )
        self._responses_extra_headers = dict(responses_extra_headers or {})
        self._deepseek_client_factory = (
            deepseek_client_factory or _default_deepseek_client_factory
        )
        self._retry_sleep = _retry_sleep

    async def execute(
        self,
        candidate: SearchProviderCandidate,
        request: SearchRequest | Mapping[str, Any],
        *,
        request_budget: SearchProviderRequestBudget | None = None,
    ) -> dict[str, Any]:
        """Run every query for *candidate* atomically and return one SearchResponse."""
        snapshot = (
            request
            if isinstance(request, SearchRequest)
            else SearchRequest.from_body(request)
        )
        _validate_candidate_execution_contract(candidate, snapshot)
        if isinstance(candidate, TavilySearchProviderCandidate):
            client: Any = self._tavily_client or TavilyHTTPClient(candidate.api_key)
            candidate_client = None
            self_hosted_provider = None
        elif isinstance(candidate, SelfHostedSearchProviderCandidate):
            client = self._self_hosted_client
            candidate_client = self._candidate_self_hosted_client
            self_hosted_provider = candidate.provider
        elif isinstance(candidate, DeepSeekNativeResponsesSearchProviderCandidate):
            return await self._execute_deepseek(
                candidate,
                snapshot,
                request_budget=request_budget,
            )
        else:
            body = copy.deepcopy(snapshot.body)
            body["model"] = candidate.responses_model
            responses_client = self._responses_client
            if responses_client is not None:

                async def operation() -> Any:
                    return await responses_client(candidate, body)

                raw = await (
                    request_budget.run_external_call(operation)
                    if request_budget
                    else operation()
                )
                validated = _validate_response(raw)
                if len(snapshot.queries) > 1:
                    _validate_query_outputs(validated, len(snapshot.queries))
                return validated
            return _validate_response(
                await self._call_responses(
                    candidate,
                    body,
                    request_budget=request_budget,
                    expected_query_count=len(snapshot.queries),
                )
            )
        if client is None and candidate_client is None:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.UPSTREAM_FAILURE
            )
        outputs: list[dict[str, Any]] = []
        for query, settings in snapshot.queries:
            try:

                async def operation() -> Any:
                    if candidate_client is not None:
                        assert self_hosted_provider is not None
                        return await candidate_client.search_for_provider(
                            self_hosted_provider,
                            query,
                            settings=settings,
                        )
                    assert client is not None
                    return await client.search(query, settings=settings)

                raw = await (
                    request_budget.run_external_call(operation)
                    if request_budget
                    else operation()
                )
                outputs.append(_normalize_local_result(query, raw))
            except SearchProviderRequestFailover:
                raise
            except Exception as exc:
                if isinstance(exc, (CodexRosettaBlockedError, UpstreamSafetyError)):
                    raise
                _map_local_error(exc)
        if not outputs:
            return {"output": "", "results": []}
        return _merge_results(outputs)

    async def _execute_deepseek(
        self,
        candidate: DeepSeekNativeResponsesSearchProviderCandidate,
        request: SearchRequest,
        *,
        request_budget: SearchProviderRequestBudget | None,
    ) -> dict[str, Any]:
        """Execute one already-validated DeepSeek hosted-search candidate."""
        query = request.queries[0][0]

        async def operation() -> DeepSeekSearchResult:
            return await self._run_deepseek_operation(candidate, query)

        try:
            result = await (
                request_budget.run_external_call(operation)
                if request_budget
                else operation()
            )
        except DeepSeekSearchError as exc:
            _map_deepseek_error(exc)
        return _validate_response(result.as_search_response())

    async def _run_deepseek_operation(
        self,
        candidate: DeepSeekNativeResponsesSearchProviderCandidate,
        query: str,
    ) -> DeepSeekSearchResult:
        provider_info = candidate.provider_info
        single_attempt = await provider_info.wait_for_credential_rotation()
        while True:
            if not provider_info.has_available_credential():
                raise DeepSeekSearchError(
                    DeepSeekSearchErrorCategory.HTTP_ERROR,
                    status_code=503,
                )
            observation = provider_info.observe_credential_rotation()
            observed = observation[0]
            credential = self._deepseek_credential(candidate, observed)
            result = await self._attempt_deepseek(candidate, query, credential)
            if not isinstance(result, DeepSeekSearchError):
                return result
            if result.status_code != 503 or single_attempt:
                raise result
            (
                leader,
                waited,
            ) = await provider_info.claim_credential_rotation_observation(observation)
            if not leader:
                single_attempt = True
                continue
            try:
                if waited:
                    single_attempt = True
                    continue
                return await self._run_deepseek_credential_leader(
                    candidate,
                    query,
                    observed,
                    credential,
                    result,
                )
            finally:
                await provider_info.publish_credential_rotation()

    async def _run_deepseek_credential_leader(
        self,
        candidate: DeepSeekNativeResponsesSearchProviderCandidate,
        query: str,
        observed: str,
        credential: str,
        initial_result: DeepSeekSearchError,
    ) -> DeepSeekSearchResult:
        provider_info = candidate.provider_info
        result: DeepSeekSearchResult | DeepSeekSearchError = initial_result
        while True:
            result = await _FAILOVER_RETRY_POLICY.run(
                result,
                lambda: self._attempt_deepseek(candidate, query, credential),
                lambda item: (
                    isinstance(item, DeepSeekSearchError) and item.status_code == 503
                ),
                sleep=self._retry_sleep,
            )
            if not isinstance(result, DeepSeekSearchError):
                return result
            if result.status_code != 503:
                raise result
            provider_info.mark_credential_failed(observed)
            next_credential = provider_info.next_available_credential(observed)
            if next_credential is None:
                raise result
            await provider_info.select_credential(next_credential)
            observed = next_credential
            credential = self._deepseek_credential(candidate, observed)
            result = await self._attempt_deepseek(candidate, query, credential)

    async def _attempt_deepseek(
        self,
        candidate: DeepSeekNativeResponsesSearchProviderCandidate,
        query: str,
        credential: str,
    ) -> DeepSeekSearchResult | DeepSeekSearchError:
        client = self._deepseek_client_factory(
            credential,
            DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN,
            candidate.provider_info.proxy_url,
        )
        try:
            return await client.execute(
                query,
                model=DEEPSEEK_RESPONSES_SEARCH_MODEL,
                max_output_tokens=DEFAULT_DEEPSEEK_RESPONSES_SEARCH_MAX_OUTPUT_TOKENS,
                citation_limit=DEFAULT_DEEPSEEK_RESPONSES_SEARCH_CITATION_LIMIT,
            )
        except DeepSeekSearchError as exc:
            return exc

    @staticmethod
    def _deepseek_credential(
        candidate: DeepSeekNativeResponsesSearchProviderCandidate,
        observed: str,
    ) -> str:
        provider_info = candidate.provider_info
        return dict(zip(provider_info.credential_ids, provider_info.credential_values))[
            observed
        ]

    async def _call_responses(
        self,
        candidate: ConfiguredResponsesSearchProviderCandidate,
        body: dict[str, Any],
        *,
        request_budget: SearchProviderRequestBudget | None = None,
        expected_query_count: int = 0,
    ) -> Any:
        transport = self._responses_transport
        if transport is None:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.UPSTREAM_FAILURE
            )
        try:

            async def operation() -> Any:
                return await transport.send_passthrough(
                    candidate.provider_info,
                    f"{candidate.provider_info.base_url}/alpha/search",
                    body,
                    extra_headers=self._responses_extra_headers,
                )

            response = await (
                request_budget.run_external_call(operation)
                if request_budget
                else operation()
            )
        except (UpstreamSafetyError, SearchProviderBudgetExceeded):  # fmt: skip
            raise
        except UpstreamConnectionError:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.CONNECTION_ERROR
            ) from None
        if response.status_code in {400, 422}:
            raise SearchProviderTerminalError("Search request rejected")
        if response.status_code in {432, 433}:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.QUOTA_EXHAUSTED, quota_exhausted=True
            )
        if response.status_code >= 500:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.UPSTREAM_FAILURE
            )
        if not 200 <= response.status_code < 300:
            raise SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)
        try:
            payload = response.body
            if expected_query_count > 1:
                if not isinstance(payload, dict):
                    raise SearchProviderAttemptError(
                        SearchProviderAttemptCategory.INVALID_RESPONSE
                    )
                _validate_query_outputs(payload, expected_query_count)
            return payload
        except Exception:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.INVALID_RESPONSE
            ) from None


def _validate_candidate_execution_contract(  # noqa: C901
    candidate: object, request: SearchRequest
) -> None:
    """Reject candidates whose declared contract cannot execute this request.

    This runs before selecting a client or charging an external-call budget, so
    configuration or contract mismatches remain local terminal failures instead
    of affecting provider health.
    """
    expected: SearchProviderContract
    required_capabilities: frozenset[SearchProviderCapability]
    if isinstance(candidate, ConfiguredResponsesSearchProviderCandidate):
        expected = GPT_PASSTHROUGH_CONTRACT
        required_capabilities = frozenset(
            {SearchProviderCapability.FULL_WEB_RUN_PASSTHROUGH}
        )
    elif isinstance(candidate, TavilySearchProviderCandidate):
        expected = TAVILY_LOCAL_CONTRACT
        required_capabilities = frozenset(
            {
                SearchProviderCapability.SEARCH_QUERY,
                SearchProviderCapability.NORMALIZED_RESULTS,
            }
        )
        if len(request.queries) > 1:
            required_capabilities = required_capabilities | frozenset(
                {SearchProviderCapability.MULTI_QUERY}
            )
    elif isinstance(candidate, SelfHostedSearchProviderCandidate):
        expected = SELF_HOSTED_LOCAL_CONTRACT
        required_capabilities = frozenset(
            {
                SearchProviderCapability.SEARCH_QUERY,
                SearchProviderCapability.NORMALIZED_RESULTS,
            }
        )
        if len(request.queries) > 1:
            required_capabilities = required_capabilities | frozenset(
                {SearchProviderCapability.MULTI_QUERY}
            )
    elif isinstance(candidate, DeepSeekNativeResponsesSearchProviderCandidate):
        expected = DEEPSEEK_NATIVE_RESPONSES_CONTRACT
        required_capabilities = frozenset(
            {
                SearchProviderCapability.SEARCH_QUERY,
                SearchProviderCapability.NORMALIZED_RESULTS,
            }
        )
        if request.requires_reference_storage:
            required_capabilities = required_capabilities | frozenset(
                {SearchProviderCapability.REFERENCE_STORAGE}
            )
        if len(request.queries) != 1:
            raise SearchProviderTerminalError(
                "DeepSeek search requires exactly one query"
            )
        query, settings = request.queries[0]
        if not isinstance(query, str) or not isinstance(settings, WebSearchSettings):
            raise SearchProviderTerminalError("Search request is invalid")
        provider_info = candidate.provider_info
        try:
            credentials = provider_info.credential_values
            official_origin = normalize_deepseek_responses_origin(
                provider_info.base_url
            )
        except AttributeError, TypeError, ValueError:
            raise SearchProviderTerminalError(
                "DeepSeek search provider is invalid"
            ) from None
        if (
            provider_info.name != "deepseek"
            or official_origin != DEEPSEEK_RESPONSES_OFFICIAL_ORIGIN
            or not credentials
            or any(type(item) is not str or not item.strip() for item in credentials)
            or candidate.model != DEEPSEEK_RESPONSES_SEARCH_MODEL
        ):
            raise SearchProviderTerminalError("DeepSeek search provider is invalid")
    else:
        raise SearchProviderTerminalError("Unsupported search provider candidate")

    contract = getattr(candidate, "contract", None)
    if not isinstance(contract, SearchProviderContract):
        raise SearchProviderTerminalError("Search provider contract is invalid")
    if contract.family is not expected.family:
        raise SearchProviderTerminalError("Search provider contract family is invalid")
    if contract.execution_mode is not expected.execution_mode:
        raise SearchProviderTerminalError("Search provider execution mode is invalid")
    if not required_capabilities <= contract.capabilities:
        raise SearchProviderTerminalError(
            "Search provider capabilities are insufficient"
        )
    if isinstance(candidate, DeepSeekNativeResponsesSearchProviderCandidate) and (
        contract is not DEEPSEEK_NATIVE_RESPONSES_CONTRACT
    ):
        raise SearchProviderTerminalError("Search provider contract is invalid")
    if any(settings.include_domains for _, settings in request.queries):
        if SearchProviderCapability.DOMAIN_FILTER not in contract.capabilities:
            raise SearchProviderTerminalError(
                "Search provider does not support domain filtering"
            )
    if (
        request.requires_reference_storage
        and contract.execution_mode is SearchProviderExecutionMode.LOCAL_QUERY_ADAPTER
        and SearchProviderCapability.REFERENCE_STORAGE not in contract.capabilities
    ):
        raise SearchProviderTerminalError(
            "Search provider does not support reference storage"
        )
    if contract.execution_mode is SearchProviderExecutionMode.LOCAL_QUERY_ADAPTER:
        for query, settings in request.queries:
            if not isinstance(query, str) or not isinstance(
                settings, WebSearchSettings
            ):
                raise SearchProviderTerminalError("Search request is invalid")


def _map_deepseek_error(exc: DeepSeekSearchError) -> Never:
    """Map one accepted adapter failure to existing chain categories."""
    if exc.category is DeepSeekSearchErrorCategory.HTTP_ERROR:
        status = exc.status_code
        if status in {400, 422}:
            raise SearchProviderTerminalError("Search request rejected") from None
        if status == 402:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.QUOTA_EXHAUSTED,
                quota_exhausted=True,
            ) from None
        if status is not None and status >= 500:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.UPSTREAM_FAILURE
            ) from None
        raise SearchProviderAttemptError(
            SearchProviderAttemptCategory.HTTP_ERROR
        ) from None
    if exc.category in {
        DeepSeekSearchErrorCategory.CONNECTION_ERROR,
        DeepSeekSearchErrorCategory.TRANSPORT_ERROR,
        DeepSeekSearchErrorCategory.TIMEOUT,
    }:
        raise SearchProviderAttemptError(
            SearchProviderAttemptCategory.CONNECTION_ERROR
        ) from None
    if exc.category in {
        DeepSeekSearchErrorCategory.INVALID_JSON,
        DeepSeekSearchErrorCategory.INVALID_SHAPE,
        DeepSeekSearchErrorCategory.BODY_LIMIT,
        DeepSeekSearchErrorCategory.CREDENTIAL_COLLISION,
    }:
        raise SearchProviderAttemptError(
            SearchProviderAttemptCategory.INVALID_RESPONSE
        ) from None
    raise exc


def _map_local_error(exc: Exception) -> None:
    if isinstance(
        exc,
        (
            SearchProviderAttemptError,
            SearchProviderRequestFailover,
            CodexRosettaBlockedError,
            UpstreamSafetyError,
            WebRunSidecarInvalidRequest,
        ),
    ):
        raise exc
    if isinstance(exc, TavilyRequestError):
        category = exc.category
        status = exc.status_code
    elif isinstance(exc, WebRunSidecarSearchError):
        category = exc.category
        status = exc.status_code
    else:
        raise exc
    if status in {432, 433}:
        raise SearchProviderAttemptError(
            SearchProviderAttemptCategory.QUOTA_EXHAUSTED, quota_exhausted=True
        ) from None
    if status in {400, 422}:
        raise SearchProviderTerminalError("Search request rejected") from None
    if category is WebRunSidecarSearchErrorCategory.UNAVAILABLE:
        raise SearchProviderAttemptError(
            SearchProviderAttemptCategory.UPSTREAM_FAILURE
        ) from None
    if category in {
        TavilyRequestErrorCategory.INVALID_JSON,
        TavilyRequestErrorCategory.INVALID_SHAPE,
        WebRunSidecarSearchErrorCategory.INVALID_JSON,
        WebRunSidecarSearchErrorCategory.INVALID_SHAPE,
    }:
        raise SearchProviderAttemptError(
            SearchProviderAttemptCategory.INVALID_RESPONSE
        ) from None
    if category in {
        TavilyRequestErrorCategory.CONNECTION_ERROR,
        WebRunSidecarSearchErrorCategory.CONNECTION_ERROR,
    }:
        raise SearchProviderAttemptError(
            SearchProviderAttemptCategory.CONNECTION_ERROR
        ) from None
    if category in {
        TavilyRequestErrorCategory.HTTP_ERROR,
        WebRunSidecarSearchErrorCategory.HTTP_ERROR,
    }:
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)
    raise exc


def _normalize_local_result(query: str, value: Any) -> dict[str, Any]:
    """Convert a local bridge result into the frozen SearchResponse shape."""
    if not isinstance(value, dict) or not isinstance(value.get("results"), list):
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.INVALID_RESPONSE)
    result = dict(value)
    output = result.get("output")
    if output is None:
        result["output"] = format_web_search_result_for_model(query, result)
    elif not isinstance(output, str):
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.INVALID_RESPONSE)
    return _validate_response(result)


def _merge_results(outputs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    merged = dict(outputs[-1])
    merged["results"] = [
        item for output in outputs for item in output.get("results", [])
    ]
    merged["output"] = "\n\n".join(
        output.get("output", "")
        for output in outputs
        if isinstance(output.get("output", ""), str)
    )
    merged["query_outputs"] = [dict(output) for output in outputs]
    return merged


__all__ = [
    "SearchRequest",
    "SearchProviderExecutor",
    "SearchProviderTerminalError",
    "SearchProviderExecutorFailure",
]
