"""Catalog v7 compilation and runtime planning tests."""

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


def test_catalog_v7_compiles_complete_immutable_source_inventory():
    compiled = compile_tool_catalog(copy.deepcopy(load_tool_catalog()))

    assert len(compiled.items) == 57
    assert len(compiled.source_registrations) == 62
    assert set(compiled.dynamic_families) == {
        "runtime.mcp",
        "runtime.apps_connectors",
        "runtime.thread_function",
        "runtime.thread_namespace",
        "runtime.extension_contributor",
    }
    assert compiled.history_aliases["Bash"] == "function.exec_command"
    assert (
        compiled.items["injection.claude_code.read"]["catalog_definition"]["function"][
            "name"
        ]
        == "Read"
    )
    with pytest.raises(TypeError):
        cast(Any, compiled.items["injection.claude_code.read"])["name"] = "changed"
    with pytest.raises(TypeError):
        cast(Any, compiled.dynamic_families["runtime.mcp"])["id"] = "changed"


def test_catalog_codex_source_bindings_match_reviewed_registration_sites():
    root = Path(__file__).resolve().parents[2]
    baseline = json.loads(
        (root / "docs/dev/version-compatibility/codex-source-contract.json").read_text()
    )
    sites = baseline["contract"]["tool_registration_sites"]
    compiled = compile_tool_catalog(copy.deepcopy(load_tool_catalog()))

    for item in compiled.items.values():
        if item["source_binding"]["origin"] != "codex_source":
            continue
        for registration_id in item["source_binding"]["registration_ids"]:
            registration = compiled.source_registrations[registration_id]
            assert registration["source_symbol"] in sites
            assert (
                sites[registration["source_symbol"]]["path"]
                == registration["source_path"]
            )

    for family in compiled.dynamic_families.values():
        assert family["source_symbol"] in sites
        assert sites[family["source_symbol"]]["path"] == family["source_path"]

    expected_0147_dynamic_owners = {
        "runtime.mcp": (
            "codex-rs/core/src/mcp_tool_exposure.rs",
            "append_mcp_tools",
        ),
        "runtime.apps_connectors": (
            "codex-rs/core/src/mcp_tool_exposure.rs",
            "append_mcp_tools",
        ),
        "runtime.thread_function": (
            "codex-rs/core/src/tools/spec_plan.rs",
            "append_dynamic_tool_runtimes::Function",
        ),
        "runtime.thread_namespace": (
            "codex-rs/core/src/tools/spec_plan.rs",
            "append_dynamic_tool_runtimes::Namespace",
        ),
        "runtime.extension_contributor": (
            "codex-rs/core/src/tools/spec_plan.rs",
            "append_extension_tool_executors",
        ),
    }
    assert {
        family_id: (family["source_path"], family["source_symbol"])
        for family_id, family in compiled.dynamic_families.items()
    } == expected_0147_dynamic_owners
    for item_id in ("custom.exec", "function.wait"):
        registration_id = compiled.items[item_id]["source_binding"]["registration_ids"][
            0
        ]
        assert (
            compiled.source_registrations[registration_id]["source_symbol"]
            == "register_code_mode_executors"
        )


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (
            lambda catalog: catalog["items"][0].update({"unknown_v7_field": True}),
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
def test_catalog_v7_fails_closed_for_invalid_runtime_contracts(mutate, error):
    catalog = copy.deepcopy(load_tool_catalog())
    mutate(catalog)

    with pytest.raises(ValueError, match=error):
        compile_tool_catalog(catalog)


def test_catalog_v7_rejects_availability_dependency_cycles():
    catalog = copy.deepcopy(load_tool_catalog())
    write_stdin = next(
        item for item in catalog["items"] if item["id"] == "function.write_stdin"
    )
    write_stdin["availability"] = {
        "dependency_effective": "injection.rosetta.send_line"
    }

    with pytest.raises(ValueError, match="dependency cycle"):
        compile_tool_catalog(catalog)


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (
            lambda catalog: catalog["items"][0]["source_binding"].update(
                {"registration_ids": ["missing.registration"]}
            ),
            "unknown source registration",
        ),
        (
            lambda catalog: catalog["source_registrations"][0].update(
                {"family_id": "runtime.mcp"}
            ),
            "exactly one item or family",
        ),
        (
            lambda catalog: catalog["dynamic_families"][0].update(
                {"deferred_adapters": ["guessed_adapter"]}
            ),
            "deferred adapters are invalid",
        ),
        (
            lambda catalog: catalog["items"][0]["surface_policy"].update(
                {"stability": "unknown"}
            ),
            "surface stability is invalid",
        ),
    ],
)
def test_catalog_v7_rejects_incomplete_source_inventory(mutate, error):
    catalog = copy.deepcopy(load_tool_catalog())
    mutate(catalog)

    with pytest.raises(ValueError, match=error):
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


def test_runtime_plan_uses_catalog_declaration_order_for_injected_definitions() -> None:
    profile = _builtin()
    injected = [
        "injection.claude_code.read",
        "injection.claude_code.edit",
        "injection.claude_code.write",
        "injection.claude_code.glob",
        "injection.claude_code.grep",
    ]
    for item_id in injected:
        profile[item_id] = "injected"

    plan = build_tool_runtime_plan({}, _route(profile))

    assert list(plan.definitions)[:5] == injected


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
