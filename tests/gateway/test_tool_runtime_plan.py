"""Catalog v6 compilation and runtime planning tests."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, cast

import pytest

from codex_rosetta.auto_detect import ProviderType
from codex_rosetta.gateway.admin.tool_catalog import load_tool_catalog
from codex_rosetta.gateway.tool_catalog_contract import compile_tool_catalog
from codex_rosetta.gateway.tool_runtime_plan import build_tool_runtime_plan
from codex_rosetta.gateway.tool_search_bridge import project_tool_search_request
from codex_rosetta.routing import ResolvedRoute


def _route(
    profile: dict[str, str] | None,
    *,
    target_provider: ProviderType = "openai_chat",
    modalities: list[str] | None = None,
) -> ResolvedRoute:
    return ResolvedRoute(
        source_provider="openai_responses",
        target_provider=target_provider,
        provider_name="test",
        tool_profile_name="test" if profile else None,
        tool_profile=profile or {},
        tool_profile_inputs={},
        input_modalities=modalities,
    )


def _builtin() -> dict[str, str]:
    from codex_rosetta.gateway.tool_profiles import tool_profile_contract

    return dict(tool_profile_contract()["builtin"])


def _native_tool_search() -> dict[str, object]:
    return {
        "type": "tool_search",
        "execution": "client",
        "description": "Search live tools.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    }


def test_catalog_v6_compiles_57_immutable_items_and_history_aliases():
    compiled = compile_tool_catalog(copy.deepcopy(load_tool_catalog()))

    assert len(compiled.items) == 57
    assert compiled.history_aliases["Bash"] == "function.exec_command"
    assert (
        compiled.items["injection.claude_code.read"]["catalog_definition"]["function"][
            "name"
        ]
        == "Read"
    )
    with pytest.raises(TypeError):
        cast(Any, compiled.items["injection.claude_code.read"])["name"] = "changed"


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (
            lambda catalog: catalog["items"][0].update({"unknown_v6_field": True}),
            "unsupported fields",
        ),
        (
            lambda catalog: catalog["items"][0].update(
                {"runtime_adapters": ["unknown_adapter"]}
            ),
            "unknown runtime adapters",
        ),
        (
            lambda catalog: next(
                item
                for item in catalog["items"]
                if item["id"] == "injection.rosetta.send_line"
            ).update({"availability": {"dependency_effective": "missing.item"}}),
            "unknown dependencies",
        ),
    ],
)
def test_catalog_v6_fails_closed_for_invalid_runtime_contracts(mutate, error):
    catalog = copy.deepcopy(load_tool_catalog())
    mutate(catalog)

    with pytest.raises(ValueError, match=error):
        compile_tool_catalog(catalog)


def test_catalog_v6_rejects_availability_dependency_cycles():
    catalog = copy.deepcopy(load_tool_catalog())
    write_stdin = next(
        item for item in catalog["items"] if item["id"] == "function.write_stdin"
    )
    write_stdin["availability"] = {
        "dependency_effective": "injection.rosetta.send_line"
    }

    with pytest.raises(ValueError, match="dependency cycle"):
        compile_tool_catalog(catalog)


def test_runtime_plan_filters_view_image_by_catalog_modality_and_redacts_trace():
    body = {
        "tools": [
            {
                "type": "function",
                "name": "view_image",
                "parameters": {"type": "object"},
            }
        ]
    }

    text_plan = build_tool_runtime_plan(body, _route(_builtin(), modalities=["text"]))
    unknown_plan = build_tool_runtime_plan(body, _route(_builtin(), modalities=None))

    assert "view_image" in text_plan.remove_names
    assert "view_image" not in unknown_plan.remove_names
    trace = json.dumps(text_plan.trace_summary())
    assert "parameters" not in trace
    assert "Search live tools" not in trace


def test_model_visible_tool_ownership_stays_in_catalog() -> None:
    root = Path(__file__).resolve().parents[2]
    source_root = root / "src" / "codex_rosetta" / "gateway"
    catalog_source = (source_root / "admin" / "tool_catalog.json").read_text()
    for fragment in (
        "Send one complete line",
        "Search deferred tools in Codex",
        "Create or overwrite a file",
        "Search file contents with ripgrep",
    ):
        assert fragment in catalog_source
        for path in source_root.glob("*.py"):
            assert fragment not in path.read_text(), path

    proxy_source = (source_root / "proxy.py").read_text()
    assert "image_generation" not in proxy_source
    assert not re.search(r'_remove_tool_definition\([^\n]+["\']', proxy_source)
    adaptation_source = (source_root / "tool_adaptation.py").read_text()
    assert "_localized_chat_tool_definitions" not in adaptation_source


def test_responses_special_passthrough_bypasses_all_runtime_actions():
    body = {"tools": [_native_tool_search()]}

    plan = build_tool_runtime_plan(
        body, _route(None, target_provider="openai_responses")
    )

    assert plan.bypass is True
    assert plan.actions == ()
    assert plan.remove_names == frozenset()


def test_passthrough_native_tool_search_projects_live_definition_and_history():
    profile = _builtin()
    profile["hosted.tool_search"] = "passthrough"
    body = {
        "tools": [_native_tool_search()],
        "input": [
            {
                "type": "tool_search_call",
                "call_id": "call_1",
                "execution": "client",
                "arguments": {"query": "calendar", "limit": 3},
            },
            {
                "type": "tool_search_output",
                "call_id": "call_1",
                "execution": "client",
                "status": "completed",
                "tools": [{"name": "calendar.search", "description": "Search"}],
            },
        ],
    }
    route = _route(profile)
    plan = build_tool_runtime_plan(body, route)

    projected = project_tool_search_request(body, plan, route)

    assert projected["tools"] == [
        {
            "type": "function",
            "name": "tool_search",
            "description": "Search live tools.",
            "parameters": _native_tool_search()["parameters"],
            "strict": False,
        }
    ]
    assert projected["input"][0]["type"] == "function_call"
    assert json.loads(projected["input"][0]["arguments"])["limit"] == 3
    assert projected["input"][1]["type"] == "function_call_output"


def test_passthrough_native_tool_search_direct_function_wins():
    profile = _builtin()
    profile["hosted.tool_search"] = "passthrough"
    direct = {
        "type": "function",
        "name": "tool_search",
        "description": "Direct",
        "parameters": {"type": "object"},
    }
    body = {"tools": [_native_tool_search(), direct]}
    route = _route(profile)

    projected = project_tool_search_request(
        body, build_tool_runtime_plan(body, route), route
    )

    assert projected["tools"] == [direct]


@pytest.mark.parametrize(
    "body",
    [
        {"tools": [{**_native_tool_search(), "execution": "server"}]},
        {
            "tools": [_native_tool_search()],
            "input": [
                {
                    "type": "tool_search_output",
                    "call_id": "orphan",
                    "execution": "client",
                    "tools": [],
                }
            ],
        },
    ],
)
def test_passthrough_native_tool_search_malformed_or_orphan_fails_closed(body):
    profile = _builtin()
    profile["hosted.tool_search"] = "passthrough"
    route = _route(profile)

    with pytest.raises(ValueError):
        project_tool_search_request(body, build_tool_runtime_plan(body, route), route)
