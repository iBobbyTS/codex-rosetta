"""Windows end-to-end smoke coverage for the gateway console entry point."""

from __future__ import annotations

import os
import hashlib
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="the console-entry-point smoke test targets Windows"
)


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _gateway_entry_point() -> str | None:
    """Resolve the installed launcher even when the active shell PATH is stale."""
    candidates = [shutil.which("codex-rosetta-gateway")]
    scripts_dir = Path(sys.executable).parent / "Scripts"
    candidates.append(str(scripts_dir / "codex-rosetta-gateway.exe"))
    candidates.append(str(scripts_dir / "codex-rosetta-gateway"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _snapshot_tree(path: Path) -> tuple[tuple[str, int, str], ...]:
    """Capture regular-file size and digest without exposing file contents."""
    if not path.exists():
        return ()
    entries: list[tuple[str, int, str]] = []
    for current, directories, files in os.walk(path):
        current_path = Path(current)
        for name in sorted(files):
            item = current_path / name
            try:
                stat = item.stat()
                if not item.is_file():
                    continue
                digest = hashlib.sha256()
                with item.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError:
                continue
            entries.append((str(item.relative_to(path)), stat.st_size, digest.hexdigest()))
    return tuple(sorted(entries))


def _descendant_pids(root_pid: int) -> set[int]:
    """Return a console launcher PID and any Python child it owns."""
    query_env = os.environ.copy()
    query_env.setdefault("SystemRoot", r"C:\Windows")
    query_env.setdefault("ComSpec", r"C:\Windows\System32\cmd.exe")
    try:
        result = subprocess.run(
            ["wmic", "process", "get", "ProcessId,ParentProcessId", "/format:csv"],
            capture_output=True,
            text=True,
            check=False,
            env=query_env,
        )
    except OSError:
        result = subprocess.CompletedProcess([], 1, "", "")
    if result.returncode != 0:
        result = subprocess.run(
            [
                os.environ.get(
                    "WINDIR", r"C:\Windows"
                )
                + r"\System32\WindowsPowerShell\v1.0\powershell.exe",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | "
                "ForEach-Object { \"$($_.ProcessId),$($_.ParentProcessId)\" }",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=query_env,
        )
    relationships: dict[int, int] = {}
    for line in result.stdout.splitlines():
        fields = [field.strip() for field in line.split(",") if field.strip()]
        if len(fields) < 2 or not fields[-2].isdigit() or not fields[-1].isdigit():
            continue
        relationships[int(fields[-2])] = int(fields[-1])
    owned = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent_pid in relationships.items():
            if parent_pid in owned and pid not in owned:
                owned.add(pid)
                changed = True
    return owned


def _port_owner_pid(port: int) -> int | None:
    """Return the Windows PID listening on a loopback TCP port."""
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        check=False,
    )
    suffix = f":{port}"
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[0].upper() == "TCP":
            local_address, state, pid = fields[1], fields[3], fields[4]
            if state.upper() == "LISTENING" and local_address.endswith(suffix):
                try:
                    return int(pid)
                except ValueError:
                    return None
    return None


def _health_live(port: int, expected_pids: set[int]) -> bool:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/health/live", method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=0.5) as response:
            owner_pid = _port_owner_pid(port)
            return response.status == 200 and owner_pid in expected_pids
    except (OSError, urllib.error.URLError):
        return False


def _terminate_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    """Terminate a child with bounded waits, escalating only when needed."""
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        return process.communicate(timeout=5)
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def test_windows_console_entry_point_reaches_liveness_in_isolated_home(
    tmp_path: Path,
) -> None:
    """The real Windows launcher starts and persists only inside the test home."""
    entry_point = _gateway_entry_point()
    if entry_point is None:
        pytest.skip("codex-rosetta-gateway console entry point is not installed")

    runtime_root = tmp_path / "gateway-runtime"
    home = runtime_root / "home"
    user_profile = runtime_root / "user-profile"
    codex_home = runtime_root / "codex-home"
    config_dir = runtime_root / "config"
    temp_dir = runtime_root / "tmp"
    for directory in (home, user_profile, codex_home, config_dir, temp_dir):
        directory.mkdir(parents=True)

    real_codex_home = Path(
        os.environ.get("CODEX_HOME") or (Path.home() / ".codex")
    ).resolve()
    real_codex_before = _snapshot_tree(real_codex_home)
    port = _free_loopback_port()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(user_profile),
            "CODEX_HOME": str(codex_home),
            "TEMP": str(temp_dir),
            "TMP": str(temp_dir),
            "PYTHONPATH": str(Path.cwd() / "src"),
        }
    )
    command = [
        entry_point,
        "--config",
        str(config_dir),
        "--codex-home",
        str(codex_home),
        "--port",
        str(port),
        "--no-local-mode",
        "--log-level",
        "stats",
    ]
    process = subprocess.Popen(
        command,
        cwd=Path.cwd(),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout = ""
    stderr = ""
    try:
        deadline = time.monotonic() + 20.0
        live = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=5)
                pytest.fail(
                    "gateway exited before /health/live: "
                    f"returncode={process.returncode}\nstdout={stdout}\nstderr={stderr}"
                )
            if _health_live(port, _descendant_pids(process.pid)):
                live = True
                break
            time.sleep(0.1)

        assert live, "gateway did not return HTTP 200 from /health/live within 20s"
        assert process.poll() is None, "gateway exited after becoming live"

        config_path = config_dir / "config.jsonc"
        assert config_path.is_file(), "config was not written to the isolated directory"
        assert str(config_dir).lower() in str(config_path.resolve()).lower()

        stdout, stderr = _terminate_process(process)
        assert process.returncode is not None
        assert "ModuleNotFoundError: No module named 'fcntl'" not in stderr
        assert "Traceback" not in stderr

        second = subprocess.Popen(
            command,
            cwd=Path.cwd(),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            second_deadline = time.monotonic() + 20.0
            while time.monotonic() < second_deadline:
                if second.poll() is not None:
                    second_stdout, second_stderr = second.communicate(timeout=5)
                    pytest.fail(
                        "gateway failed to restart from existing config: "
                        f"returncode={second.returncode}\n"
                        f"stdout={second_stdout}\nstderr={second_stderr}"
                    )
                if _health_live(port, _descendant_pids(second.pid)):
                    break
                time.sleep(0.1)
            else:
                pytest.fail("gateway did not return HTTP 200 after config restart")
            assert second.poll() is None
        finally:
            second_stdout, second_stderr = _terminate_process(second)
            assert "ModuleNotFoundError: No module named 'fcntl'" not in second_stderr
            assert "Traceback" not in second_stderr
    finally:
        if process.poll() is None:
            _terminate_process(process)

    assert _snapshot_tree(real_codex_home) == real_codex_before
