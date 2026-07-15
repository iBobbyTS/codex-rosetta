"""CLI-owned Docker Compose lifecycle for the optional ``web-run`` sidecar."""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import shutil
import socket
import subprocess
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from codex_rosetta import __version__

from .config import WEB_RUN_SIDECAR_TOKEN_ENV, WEB_RUN_SIDECAR_URL_ENV
from .logging import get_logger
from .web_run_health import WebRunHealthState

DEFAULT_WEB_RUN_HOST_PORT = 8766
MAX_WEB_RUN_PORT_ATTEMPTS = 100
WEB_RUN_STARTUP_TIMEOUT_SECONDS = 90.0
WEB_RUN_HOST_PORT_ENV = "CODEX_ROSETTA_WEB_RUN_HOST_PORT"

_ENV_UNSET = object()
_PORT_CONFLICT_MARKERS = (
    "address already in use",
    "bind: address already in use",
    "port is already allocated",
)

logger = get_logger()


class WebRunSidecarStartupError(RuntimeError):
    """Stable startup failure for a CLI-managed ``web-run`` sidecar."""


@dataclass(frozen=True)
class ManagedWebRunEndpoint:
    """Runtime-only connection settings for one managed sidecar."""

    base_url: str
    port: int


class WebRunSidecarSupervisor:
    """Start, probe, and stop one isolated Docker Compose sidecar project."""

    def __init__(
        self,
        config_path: str,
        *,
        start_port: int = DEFAULT_WEB_RUN_HOST_PORT,
        startup_timeout: float = WEB_RUN_STARTUP_TIMEOUT_SECONDS,
        environ: MutableMapping[str, str] | None = None,
        compose_file: str | Path | None = None,
    ) -> None:
        if not 1 <= start_port <= 65535:
            raise ValueError("web-run start_port must be between 1 and 65535")
        if startup_timeout <= 0:
            raise ValueError("web-run startup_timeout must be positive")
        self._config_path = str(Path(config_path).resolve())
        self._start_port = start_port
        self._startup_timeout = startup_timeout
        self._environ = os.environ if environ is None else environ
        self._compose_file = Path(compose_file or _managed_compose_file()).resolve()
        self._project_name = _compose_project_name(self._config_path)
        self._token = secrets.token_urlsafe(32)
        self._compose_environment: dict[str, str] | None = None
        self._compose_started = False
        self._environment_applied = False
        self._previous_environment: dict[str, str | object] = {}
        self._endpoint: ManagedWebRunEndpoint | None = None

    @property
    def endpoint(self) -> ManagedWebRunEndpoint | None:
        """Return the active endpoint after successful startup."""
        return self._endpoint

    def start(self) -> ManagedWebRunEndpoint:
        """Start the sidecar on the first usable port and apply runtime overrides."""
        if self._endpoint is not None:
            return self._endpoint
        self._check_prerequisites()

        candidate = self._start_port
        attempts = 0
        while attempts < MAX_WEB_RUN_PORT_ATTEMPTS and candidate <= 65535:
            if not _is_loopback_port_available(candidate):
                candidate += 1
                attempts += 1
                continue

            environment = self._build_compose_environment(candidate)
            result = self._run_compose(
                "up",
                "--build",
                "--detach",
                "--remove-orphans",
                environment=environment,
            )
            if result.returncode != 0:
                self._best_effort_down(environment)
                if _is_port_conflict(result):
                    candidate += 1
                    attempts += 1
                    continue
                raise WebRunSidecarStartupError(
                    "failed to start web-run sidecar: "
                    f"{self._bounded_command_error(result)}"
                )

            self._compose_environment = environment
            self._compose_started = True
            endpoint = ManagedWebRunEndpoint(
                base_url=f"http://127.0.0.1:{candidate}",
                port=candidate,
            )
            try:
                asyncio.run(self._wait_until_ready(endpoint.base_url))
            except BaseException:
                self.stop()
                raise

            self._apply_runtime_environment(endpoint.base_url)
            self._endpoint = endpoint
            logger.info("Managed web-run sidecar is ready on 127.0.0.1:%d", candidate)
            return endpoint

        raise WebRunSidecarStartupError(
            f"no available web-run port found from {self._start_port} "
            f"after {attempts} attempts"
        )

    def stop(self) -> None:
        """Stop this supervisor's Compose project and restore process environment."""
        try:
            if self._compose_started and self._compose_environment is not None:
                result = self._run_compose(
                    "down",
                    "--remove-orphans",
                    "--timeout",
                    "10",
                    environment=self._compose_environment,
                )
                if result.returncode != 0:
                    logger.warning(
                        "Failed to stop managed web-run sidecar: %s",
                        self._bounded_command_error(result),
                    )
        finally:
            self._compose_started = False
            self._compose_environment = None
            self._endpoint = None
            self._restore_runtime_environment()

    def _check_prerequisites(self) -> None:
        if not self._compose_file.is_file():
            raise WebRunSidecarStartupError(
                "managed web-run Compose resource is missing from this installation"
            )
        for command in ("docker", "docker-compose"):
            if shutil.which(command) is None:
                raise WebRunSidecarStartupError(
                    f"{command} is required for --with-web-run"
                )
        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WebRunSidecarStartupError(
                "failed to query the Docker daemon for --with-web-run"
            ) from exc
        if result.returncode != 0:
            raise WebRunSidecarStartupError(
                "Docker daemon is unavailable for --with-web-run"
            )

    def _build_compose_environment(self, port: int) -> dict[str, str]:
        environment = dict(self._environ)
        environment[WEB_RUN_SIDECAR_TOKEN_ENV] = self._token
        environment[WEB_RUN_HOST_PORT_ENV] = str(port)
        environment["CODEX_ROSETTA_VERSION"] = __version__
        return environment

    def _run_compose(
        self,
        *arguments: str,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        command = [
            "docker-compose",
            "--project-name",
            self._project_name,
            "--file",
            str(self._compose_file),
            *arguments,
        ]
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(
                command,
                returncode=124,
                stdout=_decode_subprocess_output(exc.stdout),
                stderr="docker-compose command timed out",
            )
        except OSError as exc:
            return subprocess.CompletedProcess(
                command,
                returncode=127,
                stdout="",
                stderr=str(exc),
            )

    async def _wait_until_ready(self, base_url: str) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._startup_timeout
        state = WebRunHealthState(ttl_seconds=0.0)
        last_status = None
        while True:
            last_status = await state.status(base_url)
            if last_status.service_online and last_status.browser_ready is True:
                return
            if loop.time() >= deadline:
                break
            await asyncio.sleep(0.25)
        service = "online" if last_status and last_status.service_online else "offline"
        browser = (
            "ready"
            if last_status and last_status.browser_ready is True
            else "not ready"
        )
        raise WebRunSidecarStartupError(
            "web-run sidecar did not become ready before the startup timeout "
            f"(service={service}, browser={browser})"
        )

    def _apply_runtime_environment(self, base_url: str) -> None:
        if self._environment_applied:
            return
        for name, value in (
            (WEB_RUN_SIDECAR_URL_ENV, base_url),
            (WEB_RUN_SIDECAR_TOKEN_ENV, self._token),
        ):
            self._previous_environment[name] = self._environ.get(name, _ENV_UNSET)
            self._environ[name] = value
        self._environment_applied = True

    def _restore_runtime_environment(self) -> None:
        if not self._environment_applied:
            return
        for name, previous in self._previous_environment.items():
            if previous is _ENV_UNSET:
                self._environ.pop(name, None)
            else:
                self._environ[name] = str(previous)
        self._previous_environment.clear()
        self._environment_applied = False

    def _best_effort_down(self, environment: dict[str, str]) -> None:
        self._run_compose(
            "down",
            "--remove-orphans",
            "--timeout",
            "10",
            environment=environment,
        )

    def _bounded_command_error(self, result: subprocess.CompletedProcess[str]) -> str:
        message = (
            result.stderr or result.stdout or "unknown Docker Compose error"
        ).strip()
        message = " ".join(message.split())
        return message.replace(self._token, "[REDACTED]")[:1000]


def _managed_compose_file() -> Path:
    return Path(__file__).with_name("resources") / "web_run" / "compose.yaml"


def _compose_project_name(config_path: str) -> str:
    identity = f"{config_path}:{os.getpid()}:{secrets.token_hex(4)}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"codex-rosetta-web-run-{digest}"


def _is_loopback_port_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            candidate.bind(("127.0.0.1", port))
    except OSError:
        return False
    return True


def _is_port_conflict(result: subprocess.CompletedProcess[str]) -> bool:
    output = f"{result.stdout}\n{result.stderr}".lower()
    return any(marker in output for marker in _PORT_CONFLICT_MARKERS)


def _decode_subprocess_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


__all__: Sequence[str] = (
    "DEFAULT_WEB_RUN_HOST_PORT",
    "ManagedWebRunEndpoint",
    "WebRunSidecarStartupError",
    "WebRunSidecarSupervisor",
)
