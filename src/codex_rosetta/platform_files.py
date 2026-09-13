"""Cross-platform primitives for private durable files."""

from __future__ import annotations

import contextlib
import os
import stat
import subprocess
import time
import logging
from collections.abc import Iterator

_LOG = logging.getLogger(__name__)


@contextlib.contextmanager
def exclusive_lock(file_obj: object, *, timeout: float = 30.0) -> Iterator[None]:
    """Hold an exclusive lock on an already-open file."""
    if os.name == "nt":
        import msvcrt

        deadline = time.monotonic() + timeout
        while True:
            file_obj.seek(0)
            try:
                msvcrt.locking(file_obj.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out acquiring Windows file lock")
                time.sleep(0.05)
        try:
            yield
        finally:
            file_obj.seek(0)
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(file_obj, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(file_obj, fcntl.LOCK_UN)


def set_private_file(fd: int) -> None:
    if os.name != "nt":
        os.fchmod(fd, 0o600)


def set_private_path(path: str | os.PathLike[str]) -> None:
    if os.name != "nt":
        os.chmod(path, 0o600)
    else:
        _set_windows_owner_acl(path)


def set_private_directory(path: str | os.PathLike[str]) -> None:
    if os.name != "nt":
        os.chmod(path, 0o700)
    else:
        _set_windows_owner_acl(path)


def _set_windows_owner_acl(path: str | os.PathLike[str]) -> None:
    """Remove inherited ACLs and grant full control to the current user."""
    user = os.environ.get("USERNAME")
    if not user:
        _LOG.warning("Windows private ACL skipped for %s: USERNAME unavailable", path)
        return
    domain = os.environ.get("USERDOMAIN")
    principal = f"{domain}\\{user}" if domain else user
    # Reset to a predictable DACL, remove inheritance, then grant only the
    # resolved interactive user. ``/grant:r`` replaces that user's ACE.
    try:
        result = subprocess.run(
        [
            "icacls",
            os.fspath(path),
            "/reset",
        ],
        capture_output=True,
        text=True,
            check=False,
        )
    except OSError as exc:
        _LOG.warning("Windows private ACL skipped for %s: %s", path, exc)
        return
    if result.returncode != 0:
        _LOG.warning("Windows private ACL reset failed for %s: %s", path, result.stderr)
        return
    try:
        result = subprocess.run(
            [
                "icacls",
                os.fspath(path),
                "/inheritance:r",
                "/grant:r",
                f"{principal}:F",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _LOG.warning("Windows private ACL grant skipped for %s: %s", path, exc)
        return
    if result.returncode != 0:
        _LOG.warning("Windows private ACL grant failed for %s: %s", path, result.stderr)


def fsync_directory(path: str | os.PathLike[str]) -> None:
    """Sync directory metadata on POSIX; explicitly unsupported on Windows."""
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def open_regular_readonly(path: str | os.PathLike[str]) -> int:
    path = os.fspath(path)
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise OSError(f"unsafe non-regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags)


def exclusive_create_flags() -> int:
    return os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)


def open_lock_file(path: str | os.PathLike[str]) -> object:
    """Open a private lock file with one byte available to msvcrt locking."""
    path = os.fspath(path)
    if os.path.lexists(path) and os.path.islink(path):
        raise OSError(f"unsafe lock path: {path}")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        set_private_file(fd)
        if os.path.getsize(path) == 0:
            os.write(fd, b"\0")
            os.fsync(fd)
        set_private_path(path)
        return os.fdopen(fd, "r+b")
    except Exception:
        os.close(fd)
        raise
