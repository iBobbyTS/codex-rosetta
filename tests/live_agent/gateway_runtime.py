"""Shared isolated Gateway/Codex runtime helpers for live-agent suites."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from codex_rosetta.gateway.config import _strip_jsonc_comments


AUTH_SOURCE = Path("/Users/ibobby/.codex-multi-2/auth.json")
GATEWAY_CONFIG_SOURCE = Path.home() / ".config/codex-rosetta-gateway/config.jsonc"


def write_json(path: Path, value: Any) -> None:
    """Write one deterministic UTF-8 JSON artifact."""

    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def toml_string(value: str) -> str:
    """Encode a TOML-compatible quoted string."""

    return json.dumps(value)


def free_port() -> int:
    """Reserve and release one localhost TCP port."""

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def check_ignored(root: Path, *paths: Path) -> None:
    """Fail when a credential destination is not ignored by Git."""

    for path in paths:
        completed = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", str(path)],
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"secret destination is not git-ignored: {path}")


def codex_env(run_root: Path) -> dict[str, str]:
    """Return an environment bound to an isolated Codex Home."""

    env = os.environ.copy()
    env["CODEX_HOME"] = str(run_root / "codex_home")
    return env


def configure_gateway_and_codex(
    root: Path,
    run_root: Path,
    gateway_log_root: Path,
    *,
    model: str,
    port: int,
    auto_compact_token_limit: int,
    expected_gateway_provider: str | None,
) -> tuple[str, list[str]]:
    """Configure one copied Gateway and its local-mode Codex client."""

    gateway_path = run_root / "gateway" / "config.jsonc"
    config = json.loads(_strip_jsonc_comments(gateway_path.read_text(encoding="utf-8")))
    server = config.setdefault("server", {})
    server["host"] = "127.0.0.1"
    server["port"] = port
    server["stream_trace"] = {
        "enabled": True,
        "filter": model,
        "path": str(gateway_log_root / "rosetta-trace.jsonl"),
    }
    api_keys = server.get("api_keys")
    if not isinstance(api_keys, list) or not api_keys:
        raise ValueError("copied gateway config has no server.api_keys")
    client_key = api_keys[0].get("key")
    if not isinstance(client_key, str) or not client_key:
        raise ValueError("copied gateway config has no usable client key")

    groups = config.get("model_groups")
    if not isinstance(groups, dict):
        raise ValueError("copied gateway config has no model_groups")
    matching_groups = [
        (name, group)
        for name, group in groups.items()
        if isinstance(group, dict) and model in group.get("models", {})
    ]
    if not matching_groups:
        raise RuntimeError(
            "USER_DECISION_REQUIRED: copied Gateway config does not route "
            f"model {model!r}; stop and choose whether to update the config or "
            "select another model"
        )
    providers = sorted(
        {
            provider
            for _, group in matching_groups
            if isinstance(provider := group.get("provider"), str) and provider
        }
    )
    if expected_gateway_provider and expected_gateway_provider not in providers:
        raise RuntimeError(
            "USER_DECISION_REQUIRED: expected provider "
            f"{expected_gateway_provider!r} is not configured for model {model!r}; "
            "stop and choose whether to accept the observed provider or update "
            "the Gateway config"
        )

    write_json(gateway_path, config)
    codex_config = "\n".join(
        [
            'model_provider = "codex_rosetta"',
            f"model = {toml_string(model)}",
            'sandbox_mode = "danger-full-access"',
            'approval_policy = "never"',
            'model_reasoning_effort = "medium"',
            f"model_auto_compact_token_limit = {auto_compact_token_limit}",
            "",
            "[model_providers.codex_rosetta]",
            'name = "OpenAI"',
            'wire_api = "responses"',
            "requires_openai_auth = true",
            f'base_url = "http://127.0.0.1:{port}/v1"',
            f"experimental_bearer_token = {toml_string(client_key)}",
            "",
            f"[projects.{toml_string(str(run_root / 'worktree'))}]",
            'trust_level = "trusted"',
            "",
        ]
    )
    (run_root / "codex_home" / "config.toml").write_text(
        codex_config,
        encoding="utf-8",
    )
    return client_key, providers


def validate_auth(run_root: Path, *, port: int, client_key: str) -> None:
    """Install only the approved OAuth file and emit credential-free evidence."""

    auth = json.loads(AUTH_SOURCE.read_text(encoding="utf-8"))
    if auth.get("auth_mode") != "chatgpt" or not isinstance(auth.get("tokens"), dict):
        raise RuntimeError("authorized Codex auth source is not ChatGPT OAuth")
    shutil.copy2(AUTH_SOURCE, run_root / "codex_home" / "auth.json")
    os.chmod(run_root / "codex_home" / "auth.json", 0o600)
    status = subprocess.run(
        ["codex", "login", "status"],
        check=False,
        capture_output=True,
        text=True,
        env=codex_env(run_root),
    )
    if status.returncode != 0 or "ChatGPT" not in status.stdout + status.stderr:
        raise RuntimeError("isolated Codex Home did not report ChatGPT authentication")
    write_json(
        run_root / "artifacts" / "runtime-auth.json",
        {
            "execution_mode": "oauth_plus_experimental_bearer_local_mode",
            "gateway_secret_source_directory": "~/.config/codex-rosetta-gateway",
            "auth_source": str(AUTH_SOURCE),
            "codex_login_status": "chatgpt_oauth",
            "gateway_mode": "local_mode",
            "provider_identity": "codex_rosetta",
            "provider_display_name": "OpenAI",
            "provider_requires_openai_auth": True,
            "provider_bearer_present": bool(client_key),
            "provider_base_url": f"http://127.0.0.1:{port}/v1",
        },
    )


def wait_ready(port: int, client_key: str, process: subprocess.Popen[bytes]) -> None:
    """Wait for an isolated Gateway's authenticated models endpoint."""

    deadline = time.monotonic() + 30
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/models",
        headers={"Authorization": f"Bearer {client_key}"},
    )
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"isolated gateway exited with {process.returncode}")
        try:
            with urllib.request.urlopen(request, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError, urllib.error.URLError:
            time.sleep(0.2)
    raise TimeoutError("isolated gateway did not become ready")
