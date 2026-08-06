from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from codex_rosetta.gateway.search_provider_candidates import (
    search_candidates_capabilities,
)
from codex_rosetta.gateway.search_provider_contract import (
    GPT_PASSTHROUGH_CONTRACT,
    LOCAL_QUERY_CAPABILITIES,
    TAVILY_LOCAL_CONTRACT,
    SearchProviderCapability,
)
from codex_rosetta.gateway.web_run_capabilities import (
    WEB_RUN_BASIC_SEARCH_CAPABILITY,
    WEB_RUN_SIDECAR_CAPABILITY,
    project_modified_web_run_schema,
    web_run_capability_trace_summary,
    web_run_model_availability,
)
from codex_rosetta.routing import ResolvedRoute


def _candidate(contract, provider="configured_responses_provider"):
    return SimpleNamespace(contract=contract, provider=provider)


def _schema() -> dict:
    commands = {
        name: {
            "type": "array",
            "items": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
        for name in (
            "search_query",
            "image_query",
            "finance",
            "weather",
            "sports",
            "open",
            "time",
        )
    }
    commands.update(
        {
            "click": commands["open"],
            "find": commands["open"],
            "screenshot": commands["open"],
        }
    )
    return {"type": "object", "properties": commands, "required": list(commands)}


def test_candidate_chain_capabilities_preserve_gpt_and_intersect_mixed() -> None:
    assert search_candidates_capabilities(
        [_candidate(GPT_PASSTHROUGH_CONTRACT)], self_hosted_ready=False
    ) == frozenset({SearchProviderCapability.FULL_WEB_RUN_PASSTHROUGH})
    assert (
        search_candidates_capabilities(
            [
                _candidate(GPT_PASSTHROUGH_CONTRACT),
                _candidate(TAVILY_LOCAL_CONTRACT, "tavily"),
            ],
            self_hosted_ready=False,
        )
        == LOCAL_QUERY_CAPABILITIES
    )


def test_typed_empty_or_unknown_does_not_fall_back_to_legacy_search() -> None:
    route = ResolvedRoute(
        source_provider="openai_responses",
        target_provider="openai_responses",
        provider_name="test",
        tool_runtime_capabilities=frozenset({WEB_RUN_BASIC_SEARCH_CAPABILITY}),
        web_run_search_capabilities=frozenset(),
    )
    assert web_run_model_availability(route) == (False, False)
    projected = project_modified_web_run_schema(
        _schema(),
        search_available=True,
        browser_available=False,
        search_capabilities=(),
    )
    assert projected is None


def test_route_clone_keeps_typed_capabilities_and_sidecar_independent() -> None:
    route = ResolvedRoute(
        source_provider="openai_responses",
        target_provider="openai_responses",
        provider_name="test",
        web_run_search_capabilities=frozenset({"search_query"}),
    )
    clone = replace(
        route, tool_runtime_capabilities=frozenset({WEB_RUN_SIDECAR_CAPABILITY})
    )
    assert clone.web_run_search_capabilities == frozenset({"search_query"})
    assert web_run_model_availability(clone) == (True, True)


def test_capability_trace_is_bounded_and_uses_canonical_modes() -> None:
    summary = web_run_capability_trace_summary(
        [SearchProviderCapability.FULL_WEB_RUN_PASSTHROUGH], ["weather", "search_query"]
    )
    assert summary["execution_mode"] == "alpha_search_passthrough"
    assert summary["projected_commands"] == ["search_query", "weather"]
    assert (
        web_run_capability_trace_summary([], ["search_query"])["execution_mode"]
        == "unknown"
    )
    assert "api_key" not in str(summary)
