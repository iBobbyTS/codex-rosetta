"""Typed contracts for web-search provider families."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum


# The search provider module owns the local ``/alpha/search`` subset.  These
# are intentionally not derived from the Tool Catalog: the catalog identifies
# and binds ``web.run``, while provider adapters own request semantics.
WEB_RUN_BASE_COMMAND_FIELDS = {
    "open": frozenset({"ref_id", "lineno"}),
    "time": frozenset({"utc_offset"}),
    "response_length": None,
}
WEB_RUN_SEARCH_COMMAND_FIELDS = {
    "search_query": frozenset({"q", "domains"}),
}
WEB_RUN_SIDECAR_COMMAND_FIELDS = {
    "click": frozenset({"ref_id", "id"}),
    "find": frozenset({"ref_id", "pattern"}),
    "screenshot": frozenset({"ref_id", "pageno"}),
}
WEB_RUN_UNSUPPORTED_COMMANDS = frozenset(
    {
        "image_query",
        "finance",
        "weather",
        "sports",
    }
)
WEB_RUN_DESCRIPTION_DROP_MARKERS = frozenset({"empty query"})
WEB_RUN_DESCRIPTION_REPLACEMENTS = (
    (" (and optionally with a domain or recency filter)", " (optionally by domain)"),
)


class SearchProviderFamily(StrEnum):
    """Provider family selected by a canonical search candidate."""

    GPT_PASSTHROUGH = "gpt_passthrough"
    TAVILY_LOCAL = "tavily_local"
    SELF_HOSTED_LOCAL = "self_hosted_local"
    DEEPSEEK_NATIVE_RESPONSES = "deepseek_native_responses"


class SearchProviderExecutionMode(StrEnum):
    """Wire execution strategy owned by a provider contract."""

    ALPHA_SEARCH_PASSTHROUGH = "alpha_search_passthrough"
    LOCAL_QUERY_ADAPTER = "local_query_adapter"
    NATIVE_RESPONSES_HOSTED_SEARCH = "native_responses_hosted_search"


class SearchProviderCapability(StrEnum):
    """Capabilities that may be safely used by request projection."""

    SEARCH_QUERY = "search_query"
    DOMAIN_FILTER = "domain_filter"
    MULTI_QUERY = "multi_query"
    NORMALIZED_RESULTS = "normalized_results"
    REFERENCE_STORAGE = "reference_storage"
    FULL_WEB_RUN_PASSTHROUGH = "full_web_run_passthrough"


@dataclass(frozen=True, slots=True)
class SearchProviderContract:
    """Validated family, execution mode, and capability declaration."""

    family: SearchProviderFamily
    execution_mode: SearchProviderExecutionMode
    capabilities: frozenset[SearchProviderCapability]

    def __post_init__(self) -> None:
        if not isinstance(self.family, SearchProviderFamily):
            raise ValueError(f"unknown search provider family: {self.family!r}")
        if not isinstance(self.execution_mode, SearchProviderExecutionMode):
            raise ValueError(
                f"unknown search provider execution mode: {self.execution_mode!r}"
            )
        if not self.capabilities:
            raise ValueError("search provider contract must declare capabilities")
        if not isinstance(self.capabilities, frozenset) or any(
            not isinstance(capability, SearchProviderCapability)
            for capability in self.capabilities
        ):
            raise ValueError("unknown search provider capability")

    @classmethod
    def create(
        cls,
        family: SearchProviderFamily | str,
        execution_mode: SearchProviderExecutionMode | str,
        capabilities: Collection[SearchProviderCapability | str],
    ) -> SearchProviderContract:
        """Construct a contract from typed or wire-like values, fail closed."""
        try:
            parsed_family = SearchProviderFamily(family)
            parsed_mode = SearchProviderExecutionMode(execution_mode)
            parsed_capabilities = frozenset(
                SearchProviderCapability(capability) for capability in capabilities
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid search provider contract") from exc
        return cls(parsed_family, parsed_mode, parsed_capabilities)


GPT_PASSTHROUGH_CONTRACT = SearchProviderContract.create(
    SearchProviderFamily.GPT_PASSTHROUGH,
    SearchProviderExecutionMode.ALPHA_SEARCH_PASSTHROUGH,
    (SearchProviderCapability.FULL_WEB_RUN_PASSTHROUGH,),
)
GPT_MIXED_MODE_CAPABILITIES = frozenset(
    {
        SearchProviderCapability.SEARCH_QUERY,
        SearchProviderCapability.DOMAIN_FILTER,
        SearchProviderCapability.NORMALIZED_RESULTS,
        SearchProviderCapability.REFERENCE_STORAGE,
    }
)
LOCAL_QUERY_CAPABILITIES = frozenset(
    {
        SearchProviderCapability.SEARCH_QUERY,
        SearchProviderCapability.DOMAIN_FILTER,
        SearchProviderCapability.MULTI_QUERY,
        SearchProviderCapability.NORMALIZED_RESULTS,
        SearchProviderCapability.REFERENCE_STORAGE,
    }
)
TAVILY_LOCAL_CONTRACT = SearchProviderContract.create(
    SearchProviderFamily.TAVILY_LOCAL,
    SearchProviderExecutionMode.LOCAL_QUERY_ADAPTER,
    LOCAL_QUERY_CAPABILITIES,
)
SELF_HOSTED_LOCAL_CONTRACT = SearchProviderContract.create(
    SearchProviderFamily.SELF_HOSTED_LOCAL,
    SearchProviderExecutionMode.LOCAL_QUERY_ADAPTER,
    LOCAL_QUERY_CAPABILITIES,
)


def projection_capabilities(
    contract: SearchProviderContract,
) -> frozenset[SearchProviderCapability]:
    """Return the safe model-visible subset for a possibly mixed chain.

    Configured GPT supports the complete wire only when every candidate is
    passthrough.  Its aggregate response has no per-query adapter, so mixed
    chains deliberately remain single-query until one exists.
    """
    if contract.family is SearchProviderFamily.GPT_PASSTHROUGH:
        return GPT_MIXED_MODE_CAPABILITIES
    return contract.capabilities


def contract_for_wire_provider(provider: str) -> SearchProviderContract:
    """Resolve one persisted wire provider value to its unique contract."""
    if provider == "configured_responses_provider":
        return GPT_PASSTHROUGH_CONTRACT
    if provider == "tavily":
        return TAVILY_LOCAL_CONTRACT
    if provider in {
        "self_hosted_google",
        "self_hosted_bing",
        "self_hosted_bing_browser",
    }:
        return SELF_HOSTED_LOCAL_CONTRACT
    raise ValueError(f"unknown web search provider type: {provider!r}")
