"""CLI-managed Docker Compose lifecycle tests for the web-run sidecar."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from codex_rosetta.gateway import web_run_supervisor
from codex_rosetta.gateway.config import (
    WEB_RUN_SIDECAR_TOKEN_ENV,
    WEB_RUN_SIDECAR_URL_ENV,
)
from codex_rosetta.gateway.web_run_supervisor import (
    WEB_RUN_HOST_PORT_ENV,
    WebRunSidecarStartupError,
    WebRunSidecarSupervisor,
)


def _compose_file(tmp_path: Path) -> Path:
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    return compose_file


def _successful_command(*_args, **_kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, "", "")


def test_supervisor_skips_occupied_ports_and_restores_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = {
        WEB_RUN_SIDECAR_URL_ENV: "https://existing.example",
        WEB_RUN_SIDECAR_TOKEN_ENV: "existing-token",
    }
    supervisor = WebRunSidecarSupervisor(
        str(tmp_path / "config.jsonc"),
        start_port=8766,
        environ=environment,
        compose_file=_compose_file(tmp_path),
    )
    compose_environments: list[dict[str, str]] = []

    monkeypatch.setattr(supervisor, "_check_prerequisites", lambda: None)
    monkeypatch.setattr(
        web_run_supervisor,
        "_is_loopback_port_available",
        lambda port: port != 8766,
    )

    def run_compose(*_args: str, environment: dict[str, str]):
        compose_environments.append(environment)
        return _successful_command()

    async def ready(_base_url: str) -> None:
        return None

    monkeypatch.setattr(supervisor, "_run_compose", run_compose)
    monkeypatch.setattr(supervisor, "_wait_until_ready", ready)

    endpoint = supervisor.start()

    assert endpoint.port == 8767
    assert endpoint.base_url == "http://127.0.0.1:8767"
    assert compose_environments[0][WEB_RUN_HOST_PORT_ENV] == "8767"
    assert environment[WEB_RUN_SIDECAR_URL_ENV] == endpoint.base_url
    assert environment[WEB_RUN_SIDECAR_TOKEN_ENV] != "existing-token"

    supervisor.stop()

    assert environment == {
        WEB_RUN_SIDECAR_URL_ENV: "https://existing.example",
        WEB_RUN_SIDECAR_TOKEN_ENV: "existing-token",
    }


def test_supervisor_retries_compose_port_allocation_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment: dict[str, str] = {}
    supervisor = WebRunSidecarSupervisor(
        str(tmp_path / "config.jsonc"),
        start_port=9000,
        environ=environment,
        compose_file=_compose_file(tmp_path),
    )
    up_ports: list[str] = []
    first_up = True

    monkeypatch.setattr(supervisor, "_check_prerequisites", lambda: None)
    monkeypatch.setattr(
        web_run_supervisor,
        "_is_loopback_port_available",
        lambda _port: True,
    )

    def run_compose(*arguments: str, environment: dict[str, str]):
        nonlocal first_up
        if arguments[0] == "up":
            up_ports.append(environment[WEB_RUN_HOST_PORT_ENV])
            if first_up:
                first_up = False
                return subprocess.CompletedProcess(
                    [], 1, "", "port is already allocated"
                )
        return _successful_command()

    async def ready(_base_url: str) -> None:
        return None

    monkeypatch.setattr(supervisor, "_run_compose", run_compose)
    monkeypatch.setattr(supervisor, "_wait_until_ready", ready)

    endpoint = supervisor.start()

    assert endpoint.port == 9001
    assert up_ports == ["9000", "9001"]
    supervisor.stop()


def test_supervisor_cleans_compose_project_when_health_never_becomes_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment: dict[str, str] = {}
    supervisor = WebRunSidecarSupervisor(
        str(tmp_path / "config.jsonc"),
        environ=environment,
        compose_file=_compose_file(tmp_path),
    )
    commands: list[str] = []

    monkeypatch.setattr(supervisor, "_check_prerequisites", lambda: None)
    monkeypatch.setattr(
        web_run_supervisor,
        "_is_loopback_port_available",
        lambda _port: True,
    )

    def run_compose(*arguments: str, environment: dict[str, str]):
        del environment
        commands.append(arguments[0])
        return _successful_command()

    async def not_ready(_base_url: str) -> None:
        raise WebRunSidecarStartupError("not ready")

    monkeypatch.setattr(supervisor, "_run_compose", run_compose)
    monkeypatch.setattr(supervisor, "_wait_until_ready", not_ready)

    with pytest.raises(WebRunSidecarStartupError, match="not ready"):
        supervisor.start()

    assert commands == ["up", "down"]
    assert environment == {}
    assert supervisor.endpoint is None


def test_supervisor_reports_compose_startup_timeout_without_blocking_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = WebRunSidecarSupervisor(
        str(tmp_path / "config.jsonc"),
        compose_file=_compose_file(tmp_path),
    )

    monkeypatch.setattr(supervisor, "_check_prerequisites", lambda: None)
    monkeypatch.setattr(
        web_run_supervisor,
        "_is_loopback_port_available",
        lambda _port: True,
    )
    monkeypatch.setattr(
        supervisor,
        "_run_compose",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [],
            124,
            "",
            "docker-compose command timed out after 30 seconds",
        ),
    )

    def unexpected_cleanup(_environment: dict[str, str]) -> None:
        pytest.fail("timed-out startup must not perform another blocking Compose call")

    monkeypatch.setattr(supervisor, "_best_effort_down", unexpected_cleanup)

    with pytest.raises(
        WebRunSidecarStartupError,
        match="Docker Compose startup timed out after 30 seconds",
    ):
        supervisor.start()


def test_run_compose_converts_timeout_to_bounded_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = WebRunSidecarSupervisor(
        str(tmp_path / "config.jsonc"),
        compose_file=_compose_file(tmp_path),
    )

    real_popen = subprocess.Popen

    def spawn_process_with_child(*_args, **kwargs):
        assert kwargs["start_new_session"] is True
        return real_popen(
            [
                sys.executable,
                "-c",
                "import subprocess, sys, time; "
                "print('partial build output', flush=True); "
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                "time.sleep(60)",
            ],
            **kwargs,
        )

    monkeypatch.setattr(
        web_run_supervisor.subprocess, "Popen", spawn_process_with_child
    )
    monkeypatch.setattr(web_run_supervisor, "DOCKER_COMPOSE_TIMEOUT_SECONDS", 0.1)

    started_at = time.monotonic()
    result = supervisor._run_compose("up", environment={})
    elapsed = time.monotonic() - started_at

    assert result.returncode == 124
    assert result.stdout == "partial build output\n"
    assert result.stderr == "docker-compose command timed out after 0.1 seconds"
    assert elapsed < 2.0


def test_managed_compose_resource_uses_dynamic_loopback_port() -> None:
    compose_file = web_run_supervisor._managed_compose_file()
    contents = compose_file.read_text(encoding="utf-8")

    assert compose_file.is_file()
    assert "127.0.0.1:${CODEX_ROSETTA_WEB_RUN_HOST_PORT:" in contents
    assert "container_name:" not in contents
    assert 'restart: "no"' in contents


def test_repository_compose_reuses_packaged_build_context() -> None:
    compose_file = Path(__file__).parents[2] / "docker" / "docker-compose.yaml"
    contents = compose_file.read_text(encoding="utf-8")

    assert "../src/codex_rosetta/gateway/resources/web_run" in contents
    assert "container_name: web-run" not in contents


def test_web_run_container_uses_patchright_without_playwright_runtime() -> None:
    resource_dir = (
        Path(__file__).parents[2]
        / "src"
        / "codex_rosetta"
        / "gateway"
        / "resources"
        / "web_run"
    )
    requirements = (resource_dir / "requirements.txt").read_text(encoding="utf-8")
    dockerfile = (resource_dir / "Dockerfile").read_text(encoding="utf-8")
    app_source = (resource_dir / "app.py").read_text(encoding="utf-8")

    assert "patchright==1.61.2" in requirements
    assert "playwright==" not in requirements
    assert "mcr.microsoft.com/playwright" not in dockerfile
    assert "patchright install --with-deps chromium" in dockerfile
    assert "from patchright.async_api import" in app_source
    assert "from playwright." not in app_source
    assert "_NAVIGATION_TIMEOUT_MS = 120_000" in app_source
    assert "_ACTION_TIMEOUT_MS = 60_000" in app_source
    assert "_PDF_DOWNLOAD_TIMEOUT_SECONDS = 120.0" in app_source


def test_supervisor_uses_bounded_lifecycle_timeouts() -> None:
    assert web_run_supervisor.WEB_RUN_STARTUP_TIMEOUT_SECONDS == 300.0
    assert web_run_supervisor.DOCKER_DAEMON_TIMEOUT_SECONDS == 30
    assert web_run_supervisor.DOCKER_COMPOSE_TIMEOUT_SECONDS == 30
    assert web_run_supervisor.DOCKER_COMPOSE_STOP_GRACE_SECONDS == 30
