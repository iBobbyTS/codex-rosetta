"""Platform-file contract tests."""

from __future__ import annotations

import os
import multiprocessing
import time
from pathlib import Path

import pytest

from codex_rosetta.platform_files import (
    exclusive_lock,
    fsync_directory,
    open_lock_file,
)


def test_lock_file_always_has_lockable_byte(tmp_path: Path) -> None:
    path = tmp_path / "config.lock"
    lock = open_lock_file(path)
    try:
        assert path.stat().st_size >= 1
        with exclusive_lock(lock, timeout=0.1):
            pass
    finally:
        lock.close()


def _hold_lock(path: str, ready: object, release: object) -> None:
    lock = open_lock_file(path)
    with exclusive_lock(lock):
        ready.put("locked")
        release.get(timeout=10)
    lock.close()


def test_subprocess_lock_competition_and_release(tmp_path: Path) -> None:
    path = tmp_path / "config.lock"
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    release = context.Queue()
    process = context.Process(target=_hold_lock, args=(str(path), ready, release))
    process.start()
    try:
        assert ready.get(timeout=10) == "locked"
        contender = open_lock_file(path)
        try:
            with pytest.raises(TimeoutError):
                with exclusive_lock(contender, timeout=0.2):
                    pass
            release.put("release")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    with exclusive_lock(contender, timeout=0.2):
                        break
                except TimeoutError:
                    continue
            else:
                pytest.fail("lock was not released by subprocess")
        finally:
            contender.close()
    finally:
        if process.is_alive():
            release.put("release")
        process.join(timeout=10)
        assert process.exitcode == 0


def test_directory_fsync_contract(tmp_path: Path) -> None:
    fsync_directory(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL/reparse oracle")
def test_windows_lock_reparse_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.lock"
    target.write_bytes(b"\0")
    link = tmp_path / "link.lock"
    link.symlink_to(target)
    with pytest.raises(OSError):
        open_lock_file(link)


@pytest.mark.skipif(os.name != "nt", reason="Windows bounded lock oracle")
def test_windows_lock_timeout_and_retry(tmp_path: Path) -> None:
    path = tmp_path / "config.lock"
    first = open_lock_file(path)
    second = open_lock_file(path)
    try:
        with exclusive_lock(first):
            started = time.monotonic()
            with pytest.raises(TimeoutError):
                with exclusive_lock(second, timeout=0.2):
                    pass
            assert time.monotonic() - started < 2
    finally:
        first.close()
        second.close()
