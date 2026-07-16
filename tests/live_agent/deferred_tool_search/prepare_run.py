#!/usr/bin/env python3
"""Prepare copied gateway and Codex configs for one isolated live run."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from codex_rosetta.gateway.config import _strip_jsonc_comments
from codex_rosetta.gateway.local_mode import build_model_catalog


TASK_IDS = ("01", "02", "03", "04", "05", "06", "07")
PLUGIN_NAMES = ("deferred-marker", "arithmetic-helper", "palette-helper")
SKILL_DIR_NAMES = (
    "isolated-skill-marker",
    "isolated-arithmetic-helper",
    "isolated-palette-helper",
)
PLUGIN_TASKS = frozenset({"01", "06", "07"})
MCP_TASKS = frozenset({"01", "02", "05", "07"})
SKILL_TASKS = frozenset({"03", "04"})
MCP_ONLY_PLUGIN_TASKS = frozenset({"01", "07"})
SKILL_ONLY_PLUGIN_TASKS = frozenset({"06"})
SERVER_PATH_TOKEN = "__ROSETTA_FIXTURE_SERVER__"


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _run_codex(
    run_root: Path, artifact_name: str, *args: str, expect_json: bool = False
) -> None:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(run_root / "codex_home")
    completed = subprocess.run(
        ["codex", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    artifact = run_root / "artifacts" / artifact_name
    artifact.write_text(completed.stdout, encoding="utf-8")
    if completed.stderr:
        artifact.with_suffix(artifact.suffix + ".stderr").write_text(
            completed.stderr, encoding="utf-8"
        )
    if completed.returncode != 0:
        raise RuntimeError(
            f"codex {' '.join(args[:3])} failed with exit code {completed.returncode}"
        )
    if expect_json:
        json.loads(completed.stdout)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _materialize_plugin_surfaces(worktree: Path, task_id: str) -> None:
    """Keep only the plugin surface exercised by one isolated task."""
    server = (worktree / "fixtures" / "deterministic_mcp_server.py").resolve()
    for plugin_name in PLUGIN_NAMES:
        plugin = worktree / "marketplace" / "plugins" / plugin_name
        manifest_path = plugin / ".codex-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if task_id in MCP_ONLY_PLUGIN_TASKS:
            shutil.rmtree(plugin / "skills")
            manifest.pop("skills", None)
            mcp_path = plugin / ".mcp.json"
            mcp_text = mcp_path.read_text(encoding="utf-8")
            if SERVER_PATH_TOKEN not in mcp_text:
                raise ValueError(f"missing server placeholder in {mcp_path}")
            mcp_path.write_text(
                mcp_text.replace(SERVER_PATH_TOKEN, str(server)), encoding="utf-8"
            )
        elif task_id in SKILL_ONLY_PLUGIN_TASKS:
            (plugin / ".mcp.json").unlink()
            manifest.pop("mcpServers", None)
        else:
            raise ValueError(f"unsupported plugin task id: {task_id}")
        _write_json(manifest_path, manifest)


def _install_plugins(run_root: Path) -> None:
    worktree = run_root / "worktree"
    _run_codex(
        run_root,
        "marketplace-add.json",
        "plugin",
        "marketplace",
        "add",
        str(worktree / "marketplace"),
        "--json",
        expect_json=True,
    )
    for plugin_name in PLUGIN_NAMES:
        _run_codex(
            run_root,
            f"plugin-add-{plugin_name}.json",
            "plugin",
            "add",
            f"{plugin_name}@rosetta-live-fixtures",
            "--json",
            expect_json=True,
        )
    _run_codex(
        run_root,
        "plugin-list.json",
        "plugin",
        "list",
        "--json",
        expect_json=True,
    )


def _install_standalone_skills(run_root: Path) -> None:
    worktree = run_root / "worktree"
    installed = []
    for skill_dir_name in SKILL_DIR_NAMES:
        source = worktree / "fixtures" / skill_dir_name
        destination = run_root / "codex_home" / "skills" / source.name
        shutil.copytree(source, destination)
        installed.append({"name": source.name, "installedPath": str(destination)})
    _write_json(run_root / "artifacts" / "skill-install.json", installed)


def _install_standalone_mcp(run_root: Path) -> None:
    server = run_root / "worktree" / "fixtures" / "deterministic_mcp_server.py"
    _run_codex(
        run_root,
        "mcp-add.txt",
        "mcp",
        "add",
        "standalone-capabilities",
        "--",
        "python3",
        str(server),
        "--capability",
        "all",
        "--server-name",
        "standalone-capabilities",
    )


def _provision_capability(run_root: Path, task_id: str) -> None:
    worktree = run_root / "worktree"
    if task_id in PLUGIN_TASKS:
        _materialize_plugin_surfaces(worktree, task_id)
        _install_plugins(run_root)
    elif task_id in MCP_TASKS:
        _install_standalone_mcp(run_root)
    elif task_id in SKILL_TASKS:
        _install_standalone_skills(run_root)
    else:
        raise ValueError(f"unsupported task id: {task_id}")

    if task_id in MCP_TASKS:
        _run_codex(
            run_root,
            "mcp-list.json",
            "mcp",
            "list",
            "--json",
            expect_json=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--gateway-log-root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--task-id", choices=TASK_IDS, required=True)
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    gateway_log_root = args.gateway_log_root.resolve()
    gateway_log_root.mkdir(parents=True, exist_ok=False)

    gateway_path = run_root / "gateway" / "config.jsonc"
    gateway_config = json.loads(
        _strip_jsonc_comments(gateway_path.read_text(encoding="utf-8"))
    )
    server = gateway_config.setdefault("server", {})
    server["host"] = "127.0.0.1"
    server["port"] = args.port
    server["stream_trace"] = {
        "enabled": True,
        "filter": args.model,
        "path": str(gateway_log_root / "rosetta-trace.jsonl"),
    }
    gateway_path.write_text(
        json.dumps(gateway_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    api_keys = server.get("api_keys")
    if not isinstance(api_keys, list) or not api_keys:
        raise ValueError("copied gateway config has no server.api_keys")
    client_key = api_keys[0].get("key")
    if not isinstance(client_key, str) or not client_key:
        raise ValueError("copied gateway config has no usable client key")

    provider_id = "deferred-tool-test"
    config_lines = [
        f"model_provider = {_toml_string(provider_id)}",
        f"model = {_toml_string(args.model)}",
        'sandbox_mode = "danger-full-access"',
        'approval_policy = "never"',
        'model_reasoning_effort = "medium"',
    ]
    if args.model != "gpt-5.6-terra":
        model_catalog_path = run_root / "codex_home" / "model_catalog.json"
        model_catalog_path.write_text(
            json.dumps(
                build_model_catalog(gateway_config), ensure_ascii=False, indent=2
            )
            + "\n",
            encoding="utf-8",
        )
        config_lines.append(
            f"model_catalog_json = {_toml_string(str(model_catalog_path))}"
        )

    config_lines.extend(
        [
            "",
            "[features]",
            "plugins = true",
            "",
            "[skills]",
            "include_instructions = true",
            "",
            f"[model_providers.{provider_id}]",
            'name = "openai"',
            'wire_api = "responses"',
            "requires_openai_auth = true",
            f'base_url = "http://127.0.0.1:{args.port}/v1"',
            f"experimental_bearer_token = {_toml_string(client_key)}",
            "",
            f"[projects.{_toml_string(str(run_root / 'worktree'))}]",
            'trust_level = "trusted"',
            "",
        ]
    )
    codex_config = "\n".join(config_lines)
    (run_root / "codex_home" / "config.toml").write_text(codex_config, encoding="utf-8")
    (run_root / "artifacts" / "gateway-log-root.txt").write_text(
        str(gateway_log_root) + "\n", encoding="utf-8"
    )
    (run_root / "artifacts" / "port.txt").write_text(
        str(args.port) + "\n", encoding="utf-8"
    )
    _provision_capability(run_root, args.task_id)


if __name__ == "__main__":
    main()
