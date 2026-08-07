from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import asyncio
import pytest

from codex_rosetta.gateway.app import _resolve_request_tool_runtime_capabilities
from codex_rosetta.gateway.code_mode_projection import (
    ExecToolProjection,
    project_exec_tool_definitions,
    project_modified_exec_web_run_description,
)
from codex_rosetta.gateway.config import GatewayConfig
from codex_rosetta.gateway.proxy import (
    _apply_profile_runtime_adapter,
    _web_run_projection_trace_summary,
)
from codex_rosetta.gateway.search_provider_candidates import (
    search_candidates_capabilities,
)
from codex_rosetta.gateway.search_provider_contract import (
    GPT_MIXED_MODE_CAPABILITIES,
    GPT_PASSTHROUGH_CONTRACT,
    LOCAL_QUERY_CAPABILITIES,
    SELF_HOSTED_LOCAL_CONTRACT,
    TAVILY_LOCAL_CONTRACT,
    SearchProviderCapability,
)
from codex_rosetta.gateway.web_run_capabilities import (
    WEB_RUN_BASIC_SEARCH_CAPABILITY,
    WEB_RUN_SIDECAR_CAPABILITY,
    WEB_RUN_TRACE_MAX_COMMAND_BYTES,
    WEB_RUN_TRACE_MAX_PROJECTED_COMMANDS,
    project_modified_web_run_function,
    project_modified_web_run_schema,
    web_run_capability_trace_summary,
    web_run_model_availability,
)
from codex_rosetta.routing import ResolvedRoute


def _candidate(contract, provider="configured_responses_provider"):
    return SimpleNamespace(contract=contract, provider=provider)


def _schema() -> dict:
    def array(**properties: dict[str, str]) -> dict[str, Any]:
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    name: {"type": field_type}
                    for name, field_type in properties.items()
                },
            },
        }

    commands = {
        "search_query": array(q="string", domains="array", recency="number"),
        "image_query": array(q="string"),
        "finance": array(ticker="string", type="string", market="string"),
        "weather": array(location="string", duration="number"),
        "sports": array(fn="string", league="string"),
        "open": array(ref_id="string", lineno="number"),
        "time": array(utc_offset="string"),
        "click": array(ref_id="string", id="number"),
        "find": array(ref_id="string", pattern="string"),
        "screenshot": array(ref_id="string", pageno="number"),
        "response_length": {"type": "string"},
    }
    return {"type": "object", "properties": commands, "required": list(commands)}


def _function() -> dict[str, Any]:
    commands = _schema()["properties"]
    return {
        "type": "function",
        "name": "web__run",
        "description": "\n".join(f"Use `{name}`." for name in commands),
        "parameters": _schema(),
    }


def _route(capabilities, *, runtime=frozenset()) -> ResolvedRoute:
    return ResolvedRoute(
        source_provider="openai_responses",
        target_provider="openai_responses",
        provider_name="test",
        tool_profile={"namespace.web.run": "modified"},
        tool_runtime_capabilities=runtime,
        web_run_search_capabilities=capabilities,
    )


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
        == GPT_MIXED_MODE_CAPABILITIES
    )


def test_local_candidate_and_self_hosted_readiness_are_explicit() -> None:
    assert (
        search_candidates_capabilities(
            [_candidate(TAVILY_LOCAL_CONTRACT, "tavily")], self_hosted_ready=False
        )
        == LOCAL_QUERY_CAPABILITIES
    )
    self_hosted = _candidate(SELF_HOSTED_LOCAL_CONTRACT, "self_hosted_google")
    assert not search_candidates_capabilities([self_hosted], self_hosted_ready=False)
    assert (
        search_candidates_capabilities([self_hosted], self_hosted_ready=True)
        == LOCAL_QUERY_CAPABILITIES
    )


def test_gpt_and_self_hosted_capabilities_stay_local_across_readiness_changes() -> None:
    candidates = [
        _candidate(GPT_PASSTHROUGH_CONTRACT),
        _candidate(SELF_HOSTED_LOCAL_CONTRACT, "self_hosted_google"),
    ]
    assert (
        search_candidates_capabilities(candidates, self_hosted_ready=False)
        == GPT_MIXED_MODE_CAPABILITIES
    )
    assert (
        search_candidates_capabilities(candidates, self_hosted_ready=True)
        == GPT_MIXED_MODE_CAPABILITIES
    )
    assert (
        search_candidates_capabilities(candidates, self_hosted_ready=False)
        == GPT_MIXED_MODE_CAPABILITIES
    )


@pytest.mark.parametrize(
    ("capabilities", "expected"),
    [
        (
            frozenset({SearchProviderCapability.FULL_WEB_RUN_PASSTHROUGH}),
            {
                "search_query",
                "image_query",
                "finance",
                "weather",
                "sports",
                "open",
                "time",
                "response_length",
                "click",
                "find",
                "screenshot",
            },
        ),
        (LOCAL_QUERY_CAPABILITIES, {"search_query", "open", "time", "response_length"}),
        (frozenset(), {"open", "time", "response_length"}),
    ],
)
def test_schema_and_description_match_typed_projection(capabilities, expected) -> None:
    projected = project_modified_web_run_function(
        _function(),
        search_available=bool(capabilities),
        browser_available=False,
        search_capabilities=capabilities,
    )
    assert projected is not None
    assert set(projected["parameters"]["properties"]) == expected
    for command in set(_schema()["properties"]) - expected:
        assert f"`{command}`" not in projected["description"]


def test_mixed_projection_limits_search_query_to_one_item() -> None:
    projected = project_modified_web_run_function(
        _function(),
        search_available=True,
        browser_available=False,
        search_capabilities=GPT_MIXED_MODE_CAPABILITIES,
    )
    assert projected is not None
    assert projected["parameters"]["properties"]["search_query"]["maxItems"] == 1


@pytest.mark.parametrize(
    "malformed",
    [
        frozenset(),
        frozenset({"unknown"}),
        ["search_query", "unknown"],
        "search_query",
        {"search_query": True},
    ],
)
def test_present_malformed_typed_capabilities_override_legacy(malformed) -> None:
    route = SimpleNamespace(
        tool_runtime_capabilities=frozenset({WEB_RUN_BASIC_SEARCH_CAPABILITY}),
        web_run_search_capabilities=malformed,
    )
    assert web_run_model_availability(route) == (False, False)


def test_absent_typed_field_retains_legacy_compatibility() -> None:
    route = SimpleNamespace(
        tool_runtime_capabilities=frozenset({WEB_RUN_BASIC_SEARCH_CAPABILITY})
    )
    assert web_run_model_availability(route) == (True, False)


def test_top_level_and_nested_projection_surfaces_are_equal() -> None:
    route = _route(LOCAL_QUERY_CAPABILITIES)
    top_level, removed = _apply_profile_runtime_adapter(
        _function(), "namespace.web.run", "modified", "web__run", route
    )
    assert top_level is not None and not removed
    description = """### `web__run`
Tool for accessing the internet.
exec tool declaration:
```ts
declare const tools: { web__run(args: { search_query?: Array<{ q: string; domains?: Array<string>; recency?: number; }>; image_query?: Array<{ q: string; }>; finance?: Array<{ ticker: string; }>; weather?: Array<{ location: string; }>; sports?: Array<{ fn: string; }>; open?: Array<{ ref_id: string; lineno?: number; }>; time?: Array<{ utc_offset: string; }>; response_length?: string; }): Promise<unknown>; };
```"""
    projected_description = project_modified_exec_web_run_description(
        description, route
    )
    nested = project_exec_tool_definitions(
        projected_description,
        {"web-run": ExecToolProjection("namespace.web.run", "web-run", "web__run")},
    )["web-run"]["function"]
    assert set(top_level["parameters"]["properties"]) == set(
        nested["parameters"]["properties"]
    )


def test_gateway_config_resolve_carries_typed_enum() -> None:
    raw = {
        "providers": {
            "test": {
                "api_key": "sk-test",
                "base_url": "https://api.example.com",
                "provider": "custom",
                "api_type": "chat",
            }
        },
        "model_groups": {
            "test-llm": {
                "provider": "test",
                "type": "llm",
                "models": {"gpt-test": {"upstream_model": "gpt-5.6-terra"}},
            }
        },
        "server": {
            "admin_password": "test-admin-password",
            "api_keys": [
                {"id": "test-client", "key": "test-gateway-key", "label": "Test"}
            ],
            "web_search": {
                "provider": "tavily",
                "tavily_api_key": "tvly-secret",
            },
        },
    }
    route, _ = GatewayConfig(raw).resolve("openai_responses", "gpt-test")
    assert route.web_run_search_capabilities == LOCAL_QUERY_CAPABILITIES
    assert all(
        isinstance(value, SearchProviderCapability)
        for value in route.web_run_search_capabilities
    )


def test_request_time_replace_promotes_ready_self_hosted_typed_enum() -> None:
    class Health:
        async def status(self, _url):
            return SimpleNamespace(browser_ready=True)

    config = SimpleNamespace(
        web_run_sidecar_url="http://sidecar",
        web_run_sidecar_token="secret",
        web_search_candidates=(
            _candidate(SELF_HOSTED_LOCAL_CONTRACT, "self_hosted_google"),
        ),
    )
    resolved = asyncio.run(
        _resolve_request_tool_runtime_capabilities(
            SimpleNamespace(web_run_health_state=Health()),
            config,
            _route(frozenset()),
            {"tools": [_function()]},
        )
    )
    assert resolved.web_run_search_capabilities == LOCAL_QUERY_CAPABILITIES
    assert WEB_RUN_SIDECAR_CAPABILITY in resolved.tool_runtime_capabilities


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
    assert projected is not None
    assert set(projected["properties"]) == {"open", "time", "response_length"}


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
    untrusted = [f"command-{index}" for index in range(100)] + [
        "x" * (WEB_RUN_TRACE_MAX_COMMAND_BYTES + 1)
    ]
    bounded = web_run_capability_trace_summary(LOCAL_QUERY_CAPABILITIES, untrusted)
    assert len(bounded["projected_commands"]) == WEB_RUN_TRACE_MAX_PROJECTED_COMMANDS
    assert all(
        len(command.encode()) <= WEB_RUN_TRACE_MAX_COMMAND_BYTES
        for command in bounded["projected_commands"]
    )


def test_projection_trace_summary_reads_projected_schema_not_request_commands() -> None:
    route = _route(LOCAL_QUERY_CAPABILITIES)
    projected, _ = _apply_profile_runtime_adapter(
        _function(), "namespace.web.run", "modified", "web__run", route
    )
    assert projected is not None
    summary = _web_run_projection_trace_summary(
        {
            "tools": [projected],
            "commands": {"untrusted-command": "credential-body-value"},
        },
        route,
    )
    assert summary is not None
    assert summary["execution_mode"] == "local_query_adapter"
    assert summary["projected_commands"] == [
        "open",
        "response_length",
        "search_query",
        "time",
    ]
    assert "untrusted-command" not in str(summary)
    assert "credential-body-value" not in str(summary)
