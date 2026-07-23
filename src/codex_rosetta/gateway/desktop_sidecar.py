"""Restricted entry point used by the Tauri desktop shell."""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from typing import Any, BinaryIO

from .app import create_app, run_gateway
from .cli import _empty_config_template
from .config import (
    GatewayConfig,
    config_path_for_dir,
    load_config,
    load_config_raw,
    resolve_codex_home,
    write_config,
)
from .desktop_protocol import DesktopProtocolError, emit_event, parse_command
from .local_mode import (
    CodexLocalModeTransaction,
    codex_api_key_value,
    ensure_codex_api_key,
)
from .logging import setup_logging


LOOPBACK_HOST = "127.0.0.1"


def _read_command(stream: BinaryIO) -> dict[str, Any]:
    """Read one command without exposing its contents to logs."""
    line = stream.readline()
    if not line:
        raise DesktopProtocolError("stdin_closed", "Desktop input pipe closed")
    return parse_command(line)


def _config_path(config_dir: str) -> str:
    return config_path_for_dir(os.path.abspath(os.path.expanduser(config_dir)))


def _probe(config_path: str) -> None:
    if not os.path.isfile(config_path):
        emit_event(sys.stdout, "probe", state="needs_initialization")
        return
    config = GatewayConfig(load_config(config_path))
    state = (
        "needs_local_mode_confirmation"
        if config.local_mode and not config.local_mode_confirmed
        else "ready"
    )
    emit_event(
        sys.stdout,
        "probe",
        state=state,
        port=config.port,
        local_mode=config.local_mode,
        local_mode_confirmed=config.local_mode_confirmed,
    )


def _initialize(config_path: str) -> None:
    if os.path.exists(config_path):
        raise DesktopProtocolError(
            "config_exists", "Gateway configuration already exists"
        )
    command = _read_command(sys.stdin.buffer)
    if command.get("command") != "init":
        raise DesktopProtocolError("invalid_command", "Expected init command")
    password = command.get("admin_password")
    if not isinstance(password, str) or not password.strip():
        raise DesktopProtocolError(
            "empty_admin_password", "Admin password must not be empty"
        )
    raw = _empty_config_template()
    server = raw["server"]
    server["admin_password"] = password
    server["local_mode"] = False
    server["local_mode_confirmed"] = False
    GatewayConfig.from_raw_with_env(raw)
    write_config(config_path, raw)
    emit_event(sys.stdout, "initialized", state="ready_for_local_mode_confirmation")


def _confirm_local_mode(config_path: str, codex_home: str) -> None:
    command = _read_command(sys.stdin.buffer)
    if command.get("command") != "confirm_local_mode" or not isinstance(
        command.get("confirm"), bool
    ):
        raise DesktopProtocolError(
            "invalid_command", "Expected local-mode confirmation"
        )
    raw = load_config_raw(config_path)
    server = raw.setdefault("server", {})
    if command["confirm"] is False:
        server["local_mode"] = False
        server["local_mode_confirmed"] = False
        write_config(config_path, raw)
        emit_event(sys.stdout, "local_mode", enabled=False)
        return

    server["local_mode"] = True
    server["local_mode_confirmed"] = True
    ensure_codex_api_key(raw)
    config = GatewayConfig.from_raw_with_env(raw)
    if not 1 <= config.port <= 65535:
        raise DesktopProtocolError(
            "invalid_port", "Desktop port must be between 1 and 65535"
        )
    transaction = CodexLocalModeTransaction.sync(
        codex_home,
        raw,
        gateway_port=config.port,
        api_key=codex_api_key_value(config.api_keys),
    )
    try:
        write_config(config_path, raw, activate=transaction.apply)
    except BaseException:
        transaction.rollback()
        raise
    emit_event(sys.stdout, "local_mode", enabled=True, changed=transaction.changed)


async def _wait_for_bind(app: Any, server_task: asyncio.Task[None]) -> int:
    """Wait until the owned App has actually bound its listener."""
    for _ in range(300):
        if server_task.done():
            await server_task
            raise RuntimeError("Gateway exited before binding")
        server = getattr(app, "_server", None)
        sockets = getattr(server, "sockets", None)
        if sockets:
            address = sockets[0].getsockname()
            return int(address[1])
        await asyncio.sleep(0.01)
    app.shutdown()
    await server_task
    raise DesktopProtocolError("startup_timeout", "Gateway did not bind in time")


async def _wait_for_shutdown(stream: BinaryIO) -> None:
    line = await asyncio.to_thread(stream.readline)
    if not line:
        return
    command = parse_command(line)
    if command.get("command") != "shutdown" or set(command) != {"command"}:
        raise DesktopProtocolError("invalid_command", "Expected shutdown command")


async def _serve(config_path: str, codex_home: str) -> None:
    config = GatewayConfig(load_config(config_path))
    if config.local_mode and not config.local_mode_confirmed:
        raise DesktopProtocolError(
            "local_mode_unconfirmed", "Local mode requires explicit confirmation"
        )
    if not 1 <= config.port <= 65535:
        raise DesktopProtocolError(
            "invalid_port", "Desktop port must be between 1 and 65535"
        )
    app = create_app(
        config,
        config_path=config_path,
        codex_home=codex_home,
        gateway_port=config.port,
    )
    server_task = asyncio.create_task(run_gateway(app, LOOPBACK_HOST, config.port))
    try:
        port = await _wait_for_bind(app, server_task)
        setattr(app, "_bind_port", port)
        setattr(app, "gateway_port", port)
        emit_event(
            sys.stdout,
            "ready",
            host=LOOPBACK_HOST,
            port=port,
            admin_url=f"http://{LOOPBACK_HOST}:{port}/admin",
            health_url=f"http://{LOOPBACK_HOST}:{port}/health/live",
        )
        shutdown_task = asyncio.create_task(_wait_for_shutdown(sys.stdin.buffer))
        done, _ = await asyncio.wait(
            {server_task, shutdown_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if shutdown_task in done:
            await shutdown_task
            app.shutdown()
        else:
            shutdown_task.cancel()
            await asyncio.gather(shutdown_task, return_exceptions=True)
        await server_task
        emit_event(sys.stdout, "stopped", reason="requested")
    finally:
        if not server_task.done():
            app.shutdown()
            await server_task


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-rosetta-desktop-sidecar")
    parser.add_argument(
        "action", choices=("probe", "init", "confirm-local-mode", "serve")
    )
    parser.add_argument(
        "--config", required=True, help="Gateway configuration directory"
    )
    parser.add_argument("--codex-home")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> None:
    """Execute one restricted desktop sidecar action."""
    args = _parser().parse_args()
    try:
        config_path = _config_path(args.config)
        codex_home = resolve_codex_home(args.codex_home)
        if args.action == "probe":
            _probe(config_path)
        elif args.action == "init":
            _initialize(config_path)
        elif args.action == "confirm-local-mode":
            _confirm_local_mode(config_path, codex_home)
        else:
            setup_logging(log_level=args.log_level)
            asyncio.run(_serve(config_path, codex_home))
    except DesktopProtocolError as exc:
        emit_event(sys.stdout, "error", code=exc.code, message=str(exc))
        raise SystemExit(2) from None
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        error_id = secrets.token_hex(4)
        print(
            f"Desktop sidecar error {error_id}: {type(exc).__name__}", file=sys.stderr
        )
        emit_event(
            sys.stdout,
            "error",
            code="sidecar_failed",
            message=f"Desktop sidecar failed ({error_id})",
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
