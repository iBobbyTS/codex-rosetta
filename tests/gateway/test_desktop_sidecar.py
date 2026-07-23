"""Process-level tests for the restricted desktop sidecar entry point."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


EVENT_PREFIX = "ROSETTA_DESKTOP/1 "


def _run(action: str, config_dir: Path, codex_home: Path, stdin: str = ""):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "codex_rosetta.gateway.desktop_sidecar",
            action,
            "--config",
            str(config_dir),
            "--codex-home",
            str(codex_home),
        ],
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )


def _event(stdout: str) -> dict[str, object]:
    line = stdout.strip()
    assert line.startswith(EVENT_PREFIX)
    return json.loads(line.removeprefix(EVENT_PREFIX))


def test_probe_and_init_do_not_expose_credentials(tmp_path: Path) -> None:
    config_dir = tmp_path / "gateway"
    codex_home = tmp_path / "codex"
    password = "admin-sentinel-password"

    before = _run("probe", config_dir, codex_home)
    initialized = _run(
        "init",
        config_dir,
        codex_home,
        json.dumps({"command": "init", "admin_password": password}) + "\n",
    )
    after = _run("probe", config_dir, codex_home)

    assert before.returncode == 0
    assert _event(before.stdout)["state"] == "needs_initialization"
    assert initialized.returncode == 0
    assert _event(initialized.stdout)["event"] == "initialized"
    assert password not in initialized.stdout + initialized.stderr
    raw = (config_dir / "config.jsonc").read_text("utf-8")
    data = json.loads(raw)
    assert data["server"]["admin_password"] == password
    gateway_key = data["server"]["api_keys"][0]["key"]
    assert gateway_key not in initialized.stdout + initialized.stderr
    assert _event(after.stdout) == {
        "protocol": 1,
        "event": "probe",
        "state": "ready",
        "port": 8765,
        "local_mode": False,
        "local_mode_confirmed": False,
    }
    assert os.stat(config_dir / "config.jsonc").st_mode & 0o077 == 0


def test_init_rejects_empty_password_and_never_creates_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "gateway"
    result = _run(
        "init",
        config_dir,
        tmp_path / "codex",
        '{"command":"init","admin_password":"  "}\n',
    )

    assert result.returncode == 2
    assert _event(result.stdout)["code"] == "empty_admin_password"
    assert not (config_dir / "config.jsonc").exists()


def test_init_refuses_to_overwrite_existing_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "gateway"
    first = _run(
        "init",
        config_dir,
        tmp_path / "codex",
        '{"command":"init","admin_password":"first"}\n',
    )
    second = _run(
        "init",
        config_dir,
        tmp_path / "codex",
        '{"command":"init","admin_password":"second"}\n',
    )

    assert first.returncode == 0
    assert second.returncode == 2
    assert _event(second.stdout)["code"] == "config_exists"
    assert "second" not in (config_dir / "config.jsonc").read_text("utf-8")


def test_probe_requires_decision_for_preexisting_unconfirmed_local_mode(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "gateway"
    codex_home = tmp_path / "codex"
    initialized = _run(
        "init",
        config_dir,
        codex_home,
        '{"command":"init","admin_password":"test"}\n',
    )
    assert initialized.returncode == 0
    raw_path = config_dir / "config.jsonc"
    data = json.loads(raw_path.read_text("utf-8"))
    data["server"]["local_mode"] = True
    data["server"]["local_mode_confirmed"] = False
    raw_path.write_text(json.dumps(data), encoding="utf-8")

    result = _run("probe", config_dir, codex_home)

    assert result.returncode == 0
    assert _event(result.stdout) == {
        "protocol": 1,
        "event": "probe",
        "state": "needs_local_mode_confirmation",
        "port": 8765,
        "local_mode": True,
        "local_mode_confirmed": False,
    }


def test_serve_binds_loopback_and_shutdowns_over_owned_pipe(tmp_path: Path) -> None:
    config_dir = tmp_path / "gateway"
    codex_home = tmp_path / "codex"
    initialized = _run(
        "init",
        config_dir,
        codex_home,
        '{"command":"init","admin_password":"test"}\n',
    )
    assert initialized.returncode == 0
    raw_path = config_dir / "config.jsonc"
    data = json.loads(raw_path.read_text("utf-8"))
    data["server"]["port"] = 18765
    data["server"]["host"] = "0.0.0.0"
    raw_path.write_text(json.dumps(data), encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "codex_rosetta.gateway.desktop_sidecar",
            "serve",
            "--config",
            str(config_dir),
            "--codex-home",
            str(codex_home),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdin is not None
    ready = _event(process.stdout.readline())
    try:
        assert ready["event"] == "ready"
        assert ready["host"] == "127.0.0.1"
        assert ready["admin_url"] == "http://127.0.0.1:18765/admin"
        with urllib.request.urlopen(str(ready["health_url"]), timeout=3) as response:
            assert response.status == 200
        process.stdin.write('{"command":"shutdown"}\n')
        process.stdin.flush()
        stopped = _event(process.stdout.readline())
        assert stopped["event"] == "stopped"
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
