"""Regression coverage for gateway terminal log-level CLI wiring."""

from __future__ import annotations

import errno
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from codex_rosetta.gateway import app as gateway_app
from codex_rosetta.gateway import cli


@pytest.mark.parametrize(
    ("log_level_args", "expected_level"),
    [
        ([], "warning"),
        (["--log-level", "info"], "info"),
        (["--log-level", "stats"], "stats"),
        (["--log-level", "warning"], "warning"),
        (["--log-level", "error"], "error"),
    ],
)
def test_main_passes_selected_log_level_to_logging_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    log_level_args: list[str],
    expected_level: str,
) -> None:
    config_path = tmp_path / "config.jsonc"
    config_path.write_text("{}", encoding="utf-8")
    config = SimpleNamespace(
        host="127.0.0.1",
        port=8765,
        socket=None,
        providers={},
        models={},
        log_bodies=False,
        local_mode=True,
        api_keys=[{"id": "codex", "label": "codex", "key": "test-codex-key"}],
    )
    selected_levels: list[str] = []
    app_kwargs: list[dict[str, object]] = []
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "original-codex-home"))

    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "codex-rosetta-gateway",
            "--config",
            str(tmp_path),
            "--codex-home",
            str(codex_home),
            "--confirm-clear-existing-catalog",
            *log_level_args,
        ],
    )
    monkeypatch.setattr(cli, "discover_config", lambda _path: str(config_path))
    monkeypatch.setattr(cli, "load_config", lambda _path: {})

    class FakeGatewayConfig:
        def __new__(cls, _raw):
            return config

        @classmethod
        def from_raw_with_env(cls, _raw):
            return config

    monkeypatch.setattr(cli, "GatewayConfig", FakeGatewayConfig)
    monkeypatch.setattr(
        cli,
        "setup_logging",
        lambda *, log_level: selected_levels.append(log_level),
    )
    monkeypatch.setattr(
        gateway_app,
        "create_app",
        lambda *_args, **kwargs: app_kwargs.append(kwargs) or object(),
    )

    async def fake_run_gateway(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(gateway_app, "run_gateway", fake_run_gateway)

    cli.main()

    assert selected_levels == [expected_level]
    assert app_kwargs[0]["codex_home"] == str(codex_home)
    assert app_kwargs[0]["gateway_port"] == 8765
    assert cli.os.environ["CODEX_HOME"] == str(codex_home)


@pytest.mark.parametrize("explicit_config", [False, True])
def test_main_initializes_missing_config_and_continues_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    explicit_config: bool,
) -> None:
    config_dir = tmp_path / ("explicit" if explicit_config else "default")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    argv = [
        "codex-rosetta-gateway",
        "--confirm-clear-existing-catalog",
    ]
    if explicit_config:
        argv.extend(["--config", str(config_dir)])
    else:
        monkeypatch.setattr(cli, "DEFAULT_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(cli.sys, "argv", argv)
    monkeypatch.setattr(cli, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(gateway_app, "create_app", lambda *_args, **_kwargs: object())
    started: list[tuple[str, int]] = []

    async def fake_run_gateway(_app, host, port, **_kwargs) -> None:
        started.append((host, port))

    monkeypatch.setattr(gateway_app, "run_gateway", fake_run_gateway)

    cli.main()

    config_path = config_dir / "config.jsonc"
    assert config_path.is_file()
    generated = json.loads(config_path.read_text(encoding="utf-8"))
    provider_uuids = [
        entry["api_keys"][0]["uuid"] for entry in generated["providers"].values()
    ]
    assert len(set(provider_uuids)) == 4
    assert all(UUID(value).version == 4 for value in provider_uuids)
    assert list(generated["providers"]) == [
        "openai_custom",
        "opencode_go",
        "glm",
        "deepseek",
    ]
    assert {
        name: {
            "provider": entry["provider"],
            "api_type": entry["api_type"],
            "base_urls": entry["base_urls"],
            "api_key": entry["api_keys"][0]["key"],
        }
        for name, entry in generated["providers"].items()
    } == {
        "openai_custom": {
            "provider": "openai",
            "api_type": "responses",
            "base_urls": ["https://api.example.test/v1"],
            "api_key": "${OPENAI_API_KEY}",
        },
        "opencode_go": {
            "provider": "opencode_go",
            "api_type": "chat",
            "base_urls": ["https://opencode.ai/zen/go/v1"],
            "api_key": "${OPENCODE_API_KEY}",
        },
        "glm": {
            "provider": "zhipu",
            "api_type": "chat",
            "base_urls": ["https://open.bigmodel.cn/api/paas/v4"],
            "api_key": "${ZHIPU_API_KEY}",
        },
        "deepseek": {
            "provider": "deepseek",
            "api_type": "chat",
            "base_urls": ["https://api.deepseek.com"],
            "api_key": "${DEEPSEEK_API_KEY}",
        },
    }
    assert generated["providers"]["openai_custom"]["request_encoding"] == (
        "passthrough"
    )
    assert list(generated["model_groups"]) == [
        "OpenAI",
        "OpenCode Go",
        "GLM",
        "DeepSeek",
    ]
    assert generated["model_groups"]["OpenAI"]["tool_profile"] == "passthrough"
    assert "tool_profile" not in generated["model_groups"]["OpenCode Go"]
    assert "tool_profile" not in generated["model_groups"]["GLM"]
    assert "tool_profile" not in generated["model_groups"]["DeepSeek"]
    assert started == [("127.0.0.1", 8765)]


@pytest.mark.parametrize("removed_option", ["--verbose", "-v", "--no-banner"])
def test_main_rejects_removed_cli_option(
    monkeypatch: pytest.MonkeyPatch,
    removed_option: str,
) -> None:
    monkeypatch.setattr(
        cli.sys,
        "argv",
        ["codex-rosetta-gateway", removed_option],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 2


def test_main_reports_address_in_use_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.jsonc"
    config_path.write_text("{}", encoding="utf-8")
    codex_home = tmp_path / "codex-home"
    config = SimpleNamespace(
        host="127.0.0.1",
        port=8765,
        socket=None,
        providers={},
        models={},
        log_bodies=False,
        local_mode=False,
    )

    class FakeGatewayConfig:
        def __new__(cls, _raw):
            return config

        @classmethod
        def from_raw_with_env(cls, _raw):
            return config

    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "codex-rosetta-gateway",
            "--config",
            str(tmp_path),
            "--codex-home",
            str(codex_home),
            "--no-local-mode",
            "--port",
            "8888",
        ],
    )
    monkeypatch.setattr(cli, "GatewayConfig", FakeGatewayConfig)
    monkeypatch.setattr(cli, "load_config", lambda _path: {})
    monkeypatch.setattr(cli, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(gateway_app, "create_app", lambda *_args, **_kwargs: object())
    logged_errors: list[str] = []
    monkeypatch.setattr(
        cli.logger,
        "error",
        lambda message, *args: logged_errors.append(message % args),
    )

    async def fake_run_gateway(*_args, **_kwargs) -> None:
        raise OSError(errno.EADDRINUSE, "address already in use")

    monkeypatch.setattr(gateway_app, "run_gateway", fake_run_gateway)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert logged_errors == [
        "Cannot start codex-rosetta gateway because 127.0.0.1:8888 is already in use."
    ]
    assert capsys.readouterr().err == ""


def test_main_manages_web_run_sidecar_around_gateway_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.jsonc"
    config_path.write_text("{}", encoding="utf-8")
    codex_home = tmp_path / "codex-home"
    events: list[str] = []
    observed_runtime_environment: list[tuple[str | None, str | None]] = []
    config = SimpleNamespace(
        host="127.0.0.1",
        port=8765,
        socket=None,
        providers={},
        models={},
        log_bodies=False,
        local_mode=False,
    )

    class FakeSupervisor:
        def __init__(self, received_config_path: str) -> None:
            assert received_config_path == str(config_path)

        def start(self) -> None:
            events.append("sidecar-start")
            monkeypatch.setenv("CODEX_ROSETTA_WEB_RUN_URL", "http://127.0.0.1:8767")
            monkeypatch.setenv("CODEX_ROSETTA_WEB_RUN_TOKEN", "managed-token")

        def stop(self) -> None:
            events.append("sidecar-stop")
            monkeypatch.delenv("CODEX_ROSETTA_WEB_RUN_URL")
            monkeypatch.delenv("CODEX_ROSETTA_WEB_RUN_TOKEN")

    class FakeGatewayConfig:
        def __new__(cls, _raw):
            observed_runtime_environment.append(
                (
                    cli.os.environ.get("CODEX_ROSETTA_WEB_RUN_URL"),
                    cli.os.environ.get("CODEX_ROSETTA_WEB_RUN_TOKEN"),
                )
            )
            return config

        @classmethod
        def from_raw_with_env(cls, _raw):
            return config

    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "codex-rosetta-gateway",
            "--config",
            str(tmp_path),
            "--codex-home",
            str(codex_home),
            "--no-local-mode",
            "--with-web-run",
        ],
    )
    monkeypatch.setattr(cli, "WebRunSidecarSupervisor", FakeSupervisor)
    monkeypatch.setattr(cli, "GatewayConfig", FakeGatewayConfig)
    monkeypatch.setattr(cli, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(
        gateway_app,
        "create_app",
        lambda *_args, **_kwargs: events.append("create-app") or object(),
    )

    async def fake_run_gateway(*_args, **_kwargs) -> None:
        events.append("run-gateway")

    monkeypatch.setattr(gateway_app, "run_gateway", fake_run_gateway)

    cli.main()

    assert observed_runtime_environment == [("http://127.0.0.1:8767", "managed-token")]
    assert events == [
        "sidecar-start",
        "create-app",
        "run-gateway",
        "sidecar-stop",
    ]


def test_main_logs_web_run_startup_failure_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.jsonc"
    config_path.write_text("{}", encoding="utf-8")
    codex_home = tmp_path / "codex-home"
    events: list[str] = []
    logged_errors: list[str] = []
    config = SimpleNamespace(local_mode=False)

    class FakeGatewayConfig:
        @classmethod
        def from_raw_with_env(cls, _raw):
            return config

    class FailingSupervisor:
        def __init__(self, _config_path: str) -> None:
            pass

        def start(self) -> None:
            raise cli.WebRunSidecarStartupError(
                "failed to start web-run sidecar: Docker Compose startup timed out "
                "after 30 seconds"
            )

        def stop(self) -> None:
            events.append("sidecar-stop")

    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "codex-rosetta-gateway",
            "--config",
            str(tmp_path),
            "--codex-home",
            str(codex_home),
            "--no-local-mode",
            "--with-web-run",
        ],
    )
    monkeypatch.setattr(cli, "WebRunSidecarSupervisor", FailingSupervisor)
    monkeypatch.setattr(cli, "GatewayConfig", FakeGatewayConfig)
    monkeypatch.setattr(cli, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(
        cli.logger,
        "error",
        lambda message, *args: logged_errors.append(message % args),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert logged_errors == [
        "failed to start web-run sidecar: Docker Compose startup timed out after "
        "30 seconds"
    ]
    assert events == ["sidecar-stop"]
    assert capsys.readouterr().err == ""
