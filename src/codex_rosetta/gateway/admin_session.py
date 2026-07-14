"""Durable secret storage for browser Admin sessions."""

from __future__ import annotations

import base64
import binascii
import os
import secrets
import stat
from pathlib import Path

ADMIN_SESSION_SECRET_FILENAME = "admin-session.key"

_KEY_BYTES = 32
_KEY_FILE_PREFIX = "v1:"
_MAX_KEY_FILE_BYTES = 4096


class AdminSessionSecretError(RuntimeError):
    """Raised when the durable Admin session secret cannot be loaded safely."""


def load_or_create_admin_session_secret(config_path: str | None) -> bytes:
    """Return the Admin session secret for one Gateway configuration.

    A configured Gateway persists the secret beside ``config.jsonc`` so browser
    sessions survive process restarts. Programmatic apps without a config path
    receive an ephemeral per-process secret and do not write into a guessed
    directory.
    """
    if config_path is None:
        return secrets.token_bytes(_KEY_BYTES)

    config_dir = Path(os.path.dirname(os.path.abspath(config_path)))
    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    key_path = config_dir / ADMIN_SESSION_SECRET_FILENAME
    if key_path.exists():
        return _read_key_file(key_path)
    return _create_key_file_atomic(config_dir, key_path)


def _decode_key(value: str, *, source: str) -> bytes:
    try:
        key = base64.b64decode(value.strip(), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AdminSessionSecretError(
            f"{source} must contain one base64-encoded 32-byte Admin session secret"
        ) from exc
    if len(key) != _KEY_BYTES:
        raise AdminSessionSecretError(
            f"{source} must contain one base64-encoded 32-byte Admin session secret"
        )
    return key


def _read_key_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise AdminSessionSecretError(
            f"Cannot open Admin session secret file {path}"
        ) from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise AdminSessionSecretError(
                f"Admin session secret path {path} is not a regular file"
            )
        os.fchmod(fd, 0o600)
        raw = os.read(fd, _MAX_KEY_FILE_BYTES)
        if os.read(fd, 1):
            raise AdminSessionSecretError(
                f"Admin session secret file {path} is too large"
            )
    finally:
        os.close(fd)

    try:
        text = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise AdminSessionSecretError(
            f"Admin session secret file {path} is invalid"
        ) from exc
    if not text.startswith(_KEY_FILE_PREFIX):
        raise AdminSessionSecretError(
            f"Admin session secret file {path} has an unknown format"
        )
    return _decode_key(text.removeprefix(_KEY_FILE_PREFIX), source=str(path))


def _create_key_file_atomic(config_dir: Path, key_path: Path) -> bytes:
    """Publish one fully written secret without replacing a concurrent writer."""
    key = secrets.token_bytes(_KEY_BYTES)
    encoded = (
        _KEY_FILE_PREFIX + base64.urlsafe_b64encode(key).decode("ascii") + "\n"
    ).encode("ascii")
    temp_path = config_dir / (
        f".{ADMIN_SESSION_SECRET_FILENAME}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temp_path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)

    published = False
    try:
        try:
            os.link(temp_path, key_path)
            published = True
            os.chmod(key_path, 0o600)
            _fsync_directory(config_dir)
        except FileExistsError:
            pass
    finally:
        temp_path.unlink(missing_ok=True)

    if published:
        return key
    return _read_key_file(key_path)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
