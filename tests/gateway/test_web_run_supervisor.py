"""CLI-managed Docker Compose lifecycle tests for the web-run sidecar."""

from __future__ import annotations

import subprocess
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
