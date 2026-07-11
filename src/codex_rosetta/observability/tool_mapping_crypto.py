"""Authenticated at-rest protection for executable tool-history mappings.

The gateway's tool-localization mapping is operational state: it must remain
byte-for-byte replayable across restarts, while tokens inside that mapping must
not appear as plaintext in SQLite.  This module owns the narrow cryptographic
boundary for that state.  Diagnostic redaction remains a separate concern.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any


KEY_ENV_VAR = "CODEX_ROSETTA_TOOL_MAPPING_KEY"
KEY_FILENAME = "tool-mapping.key"
PAYLOAD_VERSION = 1
_KEY_BYTES = 32
_NONCE_BYTES = 12
_KEY_FILE_PREFIX = "v1:"


class ToolMappingCryptoError(RuntimeError):
    """Base error for protected tool-mapping persistence."""


class ToolMappingKeyError(ToolMappingCryptoError):
    """The durable tool-mapping key is missing, invalid, or mismatched."""


class ToolMappingIntegrityError(ToolMappingCryptoError):
    """A protected tool-mapping payload failed authentication or validation."""


class ToolMappingCipher:
    """AES-256-GCM protector backed by a durable file or environment key."""

    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_BYTES:
            raise ToolMappingKeyError("Tool-mapping key must decode to 32 bytes")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:  # pragma: no cover - exercised by clean-wheel smoke
            raise ToolMappingCryptoError(
                "Encrypted tool-history persistence requires the gateway extra: "
                "pip install 'codex-rosetta[gateway]'"
            ) from exc
        self._aead = AESGCM(key)
        self.key_id = hashlib.sha256(key).hexdigest()

    @classmethod
    def load(cls, data_dir: Path, *, create: bool) -> ToolMappingCipher:
        """Load the configured durable key, optionally creating a key file.

        The environment override is expected to be managed by the deployment's
        durable secret store.  Its value is never included in errors or logs.
        """
        env_value = os.environ.get(KEY_ENV_VAR)
        if env_value is not None:
            return cls(_decode_key(env_value, source=KEY_ENV_VAR))

        key_path = data_dir / KEY_FILENAME
        if key_path.exists():
            return cls(_read_key_file(key_path))
        if not create:
            raise ToolMappingKeyError(
                f"Encrypted tool-history rows exist but {key_path} is missing"
            )
        return cls(_create_key_file_atomic(data_dir, key_path))

    def encrypt(
        self,
        *,
        original_tool_call: dict[str, Any],
        codex_tool_call: dict[str, Any],
        aad: bytes,
    ) -> tuple[bytes, bytes]:
        """Serialize and authenticate one exact reversible mapping."""
        payload = json.dumps(
            {
                "original_tool_call": original_tool_call,
                "codex_tool_call": codex_tool_call,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        nonce = secrets.token_bytes(_NONCE_BYTES)
        return nonce, self._aead.encrypt(nonce, payload, aad)

    def decrypt(
        self,
        *,
        key_id: str,
        nonce: bytes,
        encrypted_payload: bytes,
        aad: bytes,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Authenticate and deserialize one exact reversible mapping."""
        if key_id != self.key_id:
            raise ToolMappingKeyError(
                "Configured tool-mapping key does not match encrypted database rows"
            )
        if len(nonce) != _NONCE_BYTES:
            raise ToolMappingIntegrityError("Invalid tool-mapping nonce length")
        try:
            payload = self._aead.decrypt(nonce, encrypted_payload, aad)
        except Exception as exc:
            # InvalidTag intentionally stays behind this domain error so neither
            # key material nor ciphertext details can escape into diagnostics.
            raise ToolMappingIntegrityError(
                "Tool-mapping payload authentication failed"
            ) from exc
        try:
            decoded = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise ToolMappingIntegrityError(
                "Tool-mapping payload is not valid authenticated JSON"
            ) from exc
        if not isinstance(decoded, dict):
            raise ToolMappingIntegrityError("Tool-mapping payload must be an object")
        original = decoded.get("original_tool_call")
        codex = decoded.get("codex_tool_call")
        if not isinstance(original, dict) or not isinstance(codex, dict):
            raise ToolMappingIntegrityError(
                "Tool-mapping payload is missing executable call objects"
            )
        return original, codex


def mapping_aad(
    *,
    principal_id: str,
    provider_name: str,
    model: str,
    session_id: str,
    tool_call_id: str,
) -> bytes:
    """Bind ciphertext to its immutable SQLite ownership coordinates."""
    return json.dumps(
        [
            "codex-rosetta-tool-mapping",
            PAYLOAD_VERSION,
            principal_id,
            provider_name,
            model,
            session_id,
            tool_call_id,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _decode_key(value: str, *, source: str) -> bytes:
    try:
        key = base64.b64decode(value.strip(), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ToolMappingKeyError(
            f"{source} must contain one base64-encoded 32-byte key"
        ) from exc
    if len(key) != _KEY_BYTES:
        raise ToolMappingKeyError(
            f"{source} must contain one base64-encoded 32-byte key"
        )
    return key


def _read_key_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ToolMappingKeyError(f"Cannot open tool-mapping key file {path}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ToolMappingKeyError(f"Tool-mapping key path {path} is not a file")
        os.fchmod(fd, 0o600)
        raw = os.read(fd, 4096)
        if os.read(fd, 1):
            raise ToolMappingKeyError(f"Tool-mapping key file {path} is too large")
    finally:
        os.close(fd)
    try:
        text = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ToolMappingKeyError(f"Tool-mapping key file {path} is invalid") from exc
    if not text.startswith(_KEY_FILE_PREFIX):
        raise ToolMappingKeyError(f"Tool-mapping key file {path} has unknown format")
    return _decode_key(text.removeprefix(_KEY_FILE_PREFIX), source=str(path))


def _create_key_file_atomic(data_dir: Path, key_path: Path) -> bytes:
    """Publish one fully-written key without concurrent-writer replacement."""
    key = secrets.token_bytes(_KEY_BYTES)
    encoded = (
        _KEY_FILE_PREFIX + base64.urlsafe_b64encode(key).decode("ascii") + "\n"
    ).encode("ascii")
    temp_path = data_dir / (f".{KEY_FILENAME}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
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
            # A hard-link publish is atomic and never overwrites another
            # process's key.  The temporary inode is fully fsynced first.
            os.link(temp_path, key_path)
            published = True
            os.chmod(key_path, 0o600)
            _fsync_directory(data_dir)
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
