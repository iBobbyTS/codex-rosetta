"""Typed, provider-neutral execution of one complete web-search request.

The executor deliberately owns no ordering or health state.  Callers can replay
the same request against another candidate after a request-local failure.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from codex_rosetta._vendor.httpclient import AsyncClient
from codex_rosetta.observability.redaction import SecretRedactor

from .search_provider_candidates import (
    ConfiguredResponsesSearchProviderCandidate,
    SearchProviderCandidate,
    SelfHostedSearchProviderCandidate,
    TavilySearchProviderCandidate,
)
from .search_provider_chain import (
    SearchProviderAttemptCategory,
    SearchProviderAttemptError,
    SearchProviderBudgetExceeded,
    SearchProviderRequestFailover,
    SearchProviderRequestFailoverReason,
    SearchProviderRequestBudget,
)
from .downstream_errors import CodexRosettaBlockedError
from .transport._base import UpstreamConnectionError, UpstreamSafetyError
from .transport.http.transport import request_bounded_response
from .web_search import (
    TavilyHTTPClient,
    TavilyRequestError,
    TavilyRequestErrorCategory,
    WebSearchSettings,
    format_web_search_result_for_model,
)
from .web_run_sidecar import (
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

    @classmethod
    def from_body(
        cls,
        body: Mapping[str, Any],
        queries: Sequence[tuple[str, WebSearchSettings]] = (),
    ) -> SearchRequest:
        return cls(copy.deepcopy(dict(body)), tuple(queries))


class SearchResponseClient(Protocol):
    async def __call__(
        self,
        candidate: ConfiguredResponsesSearchProviderCandidate,
        body: dict[str, Any],
    ) -> Any: ...


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
    """Execute Tavily, self-hosted, or configured Responses candidates once."""

    def __init__(
        self,
        *,
        self_hosted_client: Any | None = None,
        responses_client: SearchResponseClient | None = None,
    ) -> None:
        self._self_hosted_client = self_hosted_client
        self._responses_client = responses_client

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
        if isinstance(candidate, TavilySearchProviderCandidate):
            client: Any = TavilyHTTPClient(candidate.api_key)
        elif isinstance(candidate, SelfHostedSearchProviderCandidate):
            client = self._self_hosted_client
        else:
            body = copy.deepcopy(snapshot.body)
            body["model"] = candidate.responses_model
            if self._responses_client is not None:
                async def operation() -> Any:
                    return await self._responses_client(candidate, body)
                raw = await (request_budget.run_external_call(operation) if request_budget else operation())
                validated = _validate_response(raw)
                if len(snapshot.queries) > 1:
                    _validate_query_outputs(validated, len(snapshot.queries))
                return validated
            return _validate_response(await self._call_responses(candidate, body, request_budget=request_budget, expected_query_count=len(snapshot.queries)))
        if client is None:
            raise SearchProviderRequestFailover(
                SearchProviderRequestFailoverReason.LOCAL_UNAVAILABLE
            )
        outputs: list[dict[str, Any]] = []
        for query, settings in snapshot.queries:
            try:
                async def operation() -> Any:
                    return await client.search(query, settings=settings)
                raw = await (request_budget.run_external_call(operation) if request_budget else operation())
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

    async def _call_responses(
        self,
        candidate: ConfiguredResponsesSearchProviderCandidate,
        body: dict[str, Any],
        *,
        request_budget: SearchProviderRequestBudget | None = None,
        expected_query_count: int = 0,
    ) -> Any:
        headers = candidate.provider_info.auth_headers()
        redactor = SecretRedactor(candidate.provider_info.credential_values)
        async with AsyncClient(timeout=120.0) as client:
            try:
                async def operation() -> Any:
                    return await request_bounded_response(
                        client,
                        "POST",
                        candidate.provider_info.upstream_url(candidate.responses_model),
                        headers=headers,
                        json=body,
                    )
                response = await (request_budget.run_external_call(operation) if request_budget else operation())
            except (UpstreamSafetyError, SearchProviderBudgetExceeded):  # fmt: skip
                raise
            except UpstreamConnectionError:
                raise SearchProviderAttemptError(
                    SearchProviderAttemptCategory.CONNECTION_ERROR
                ) from None
        if redactor.contains_json_semantic(response.content):
            raise RuntimeError("Search provider response blocked")
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
            payload = json.loads(response.content.decode("utf-8"))
            if expected_query_count > 1:
                if not isinstance(payload, dict):
                    raise SearchProviderAttemptError(SearchProviderAttemptCategory.INVALID_RESPONSE)
                _validate_query_outputs(payload, expected_query_count)
            return payload
        except Exception:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.INVALID_RESPONSE
            ) from None


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
        raise SearchProviderRequestFailover(
            SearchProviderRequestFailoverReason.LOCAL_UNAVAILABLE
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
