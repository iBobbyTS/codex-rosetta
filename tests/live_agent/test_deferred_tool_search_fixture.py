"""Regression tests for the isolated capability-discovery live fixtures."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

from codex_rosetta import convert


SUITE = Path(__file__).parent / "deferred_tool_search"
COMMON = SUITE / "common"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def prepare_module() -> ModuleType:
    return _load_module("deferred_tool_prepare_run", SUITE / "prepare_run.py")


@pytest.fixture(scope="module")
def server_module() -> ModuleType:
    return _load_module(
        "deferred_tool_fixture_server",
        COMMON / "fixtures" / "deterministic_mcp_server.py",
    )


def test_expected_contract_is_uniform_for_all_tasks() -> None:
    for task_id in ("01", "02", "03", "04", "05", "06", "07"):
        expected = json.loads((SUITE / task_id / "expected.json").read_text())
        assert expected["task_id"] == task_id
        assert expected["candidate_count"] == 3
        assert len(expected["catalog_exposure"]["candidate_order"]) == 3
        assert expected["body_access"] in {
            "host_injection",
            "agent_read",
            "not_applicable",
        }
        assert isinstance(expected["plugin_guidance_expected"], bool)
        assert isinstance(expected["prohibited_fallbacks"], list)


@pytest.mark.parametrize("task_id", ["04", "05", "06", "07"])
def test_implicit_prompts_do_not_leak_capability_identifiers(task_id: str) -> None:
    prompt = (SUITE / task_id / "TASK.md").read_text().lower()
    expected = json.loads((SUITE / task_id / "expected.json").read_text())
    assert expected["invocation_mode"] == "implicit"
    assert expected["prompt_mentions_capability"] is False
    for forbidden in (
        "plugin://",
        "deferred-marker",
        "isolated-skill-marker",
        "get_archive_proof",
        "archive_proof_ok",
        "skill_body_ok",
        "plugin_skill_body",
        "all_tools",
    ):
        assert forbidden not in prompt


def test_fixture_server_lists_candidates_in_stable_order(
    server_module: ModuleType,
) -> None:
    response = server_module.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        capabilities=("archive", "arithmetic", "palette"),
        server_name="fixture",
    )
    assert response is not None
    tools = response["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "get_archive_proof",
        "add_integers",
        "normalize_color",
    ]
    assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
    assert all("Rosetta live candidate" in tool["description"] for tool in tools)


def test_fixture_server_returns_unprompted_archive_marker(
    server_module: ModuleType,
) -> None:
    response = server_module.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_archive_proof",
                "arguments": {"record_id": "ARCHIVE-20260716"},
            },
        },
        capabilities=("archive",),
        server_name="fixture",
    )
    assert response is not None
    assert response["result"]["content"] == [
        {"type": "text", "text": "ARCHIVE_PROOF_OK:ARCHIVE-20260716"}
    ]
    assert response["result"]["isError"] is False


def test_fixture_server_uses_mcp_resource_template_result_shape(
    server_module: ModuleType,
) -> None:
    response = server_module.handle_message(
        {"jsonrpc": "2.0", "id": 3, "method": "resources/templates/list"},
        capabilities=("archive",),
        server_name="fixture",
    )
    assert response == {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {"resourceTemplates": []},
    }


@pytest.mark.parametrize(
    ("task_id", "keeps_skills", "keeps_mcp"),
    [("01", False, True), ("06", True, False), ("07", False, True)],
)
def test_plugin_surface_materialization_is_task_specific(
    tmp_path: Path,
    prepare_module: ModuleType,
    task_id: str,
    keeps_skills: bool,
    keeps_mcp: bool,
) -> None:
    worktree = tmp_path / "worktree"
    shutil.copytree(COMMON, worktree)
    prepare_module._materialize_plugin_surfaces(worktree, task_id)

    for plugin_name in prepare_module.PLUGIN_NAMES:
        plugin = worktree / "marketplace" / "plugins" / plugin_name
        manifest = json.loads((plugin / ".codex-plugin" / "plugin.json").read_text())
        assert ("skills" in manifest) is keeps_skills
        assert (plugin / "skills").exists() is keeps_skills
        assert ("mcpServers" in manifest) is keeps_mcp
        assert (plugin / ".mcp.json").exists() is keeps_mcp
        if keeps_mcp:
            mcp_text = (plugin / ".mcp.json").read_text()
            assert prepare_module.SERVER_PATH_TOKEN not in mcp_text
            assert str(worktree / "fixtures" / "deterministic_mcp_server.py") in (
                mcp_text
            )


def test_responses_to_chat_preserves_context_and_candidate_order() -> None:
    skills = (
        "<skills_instructions>\n"
        "archive proof candidate\ninteger addition candidate\n"
        "color normalization candidate\n"
        "</skills_instructions>"
    )
    plugins = "<plugins_instructions>\ngeneric plugin rules\n</plugins_instructions>"
    skill_body = "<skill>\nprivate archive body\n</skill>"
    exec_description = (
        "Deferred nested tools are available through the ALL_TOOLS runtime catalog."
    )
    body = {
        "model": "deepseek-v4-flash",
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": skills}],
            },
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": plugins}],
            },
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": skill_body}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "archive request"}],
            },
        ],
        "tools": [
            {
                "type": "custom",
                "name": "exec",
                "description": exec_description,
                "format": {"type": "text"},
            }
        ],
    }

    converted = convert(body, "openai_chat", "openai_responses")
    assert converted["messages"] == [
        {"role": "system", "content": skills},
        {"role": "system", "content": plugins},
        {"role": "system", "content": skill_body},
        {"role": "user", "content": "archive request"},
    ]
    function = converted["tools"][0]["function"]
    assert function["name"] == "exec"
    assert function["description"] == exec_description
    assert "ALL_TOOLS" in function["description"]
    assert "get_archive_proof" not in function["description"]
