"""Security and durability tests for config persistence."""

from __future__ import annotations

import json
import os
import stat

import pytest

import codex_rosetta.gateway.config as config_module
from codex_rosetta.gateway.config import (
    ConfigConflictError,
    load_config_raw,
    write_config,
)


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_write_config_creates_private_files_and_directory(tmp_path):
    directory = tmp_path / "new" / "gateway"
    path = directory / "config.jsonc"
    write_config(str(path), {"value": 1})

    assert json.loads(path.read_text()) == {"value": 1}
    assert _mode(directory) == 0o700
    assert _mode(path) == 0o600
    assert _mode(directory / "config.jsonc.lock") == 0o600


def test_write_config_keeps_private_backup(tmp_path):
    path = tmp_path / "config.jsonc"
    write_config(str(path), {"value": 1})
    document = load_config_raw(str(path))
    document["value"] = 2
    write_config(str(path), document)

    backup = tmp_path / "config.jsonc.bak"
    assert json.loads(backup.read_text()) == {"value": 1}
    assert _mode(backup) == 0o600
    assert _mode(path) == 0o600


def test_write_config_rejects_lost_update(tmp_path):
    path = tmp_path / "config.jsonc"
    write_config(str(path), {"value": 1})
    first = load_config_raw(str(path))
    second = load_config_raw(str(path))
    first["value"] = 2
    write_config(str(path), first)

    second["value"] = 3
    with pytest.raises(ConfigConflictError, match="changed on disk"):
        write_config(str(path), second)

    assert json.loads(path.read_text()) == {"value": 2}


def test_write_config_tightens_existing_permissions(tmp_path):
    path = tmp_path / "config.jsonc"
    path.write_text('{"value": 1}')
    os.chmod(path, 0o644)
    document = load_config_raw(str(path))
    write_config(str(path), document)
    assert _mode(path) == 0o600


def test_write_config_fsyncs_before_activation_and_restores_on_failure(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "config.jsonc"
    original = b'{"value": 1}\n'
    path.write_bytes(original)
    calls = 0
    activated = False

    def fail_first_fsync(_path: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated fsync failure")

    def activate() -> None:
        nonlocal activated
        activated = True

    monkeypatch.setattr(config_module, "_fsync_directory", fail_first_fsync)

    with pytest.raises(OSError, match="simulated fsync failure"):
        write_config(str(path), {"value": 2}, activate=activate)

    assert activated is False
    assert path.read_bytes() == original
    assert calls == 2
