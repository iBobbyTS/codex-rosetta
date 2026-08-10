"""Trusted-local evidence serialization and atomic publication for the smoke CLI.

This script is an offline harness seam, never imported by production runtime.
It accepts an already-normalized manifest and uses private permissions plus an
atomic same-directory replace.  Errors are intentionally ordinary and static.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Final

EVIDENCE_SCHEMA: Final = "codex-rosetta.deepseek-search-evidence"
EVIDENCE_VERSION: Final = 1
EVIDENCE_FILENAME: Final = "summary.json"
MAX_MANIFEST_BYTES: Final = 16_384
MAX_DIRECTORY_CHARACTERS: Final = 1_024
MAX_COUNTER: Final = 1_000_000_000
MAX_LATENCY_MS: Final = 3_600_000

_PREPARATION_ERROR = "DeepSeek search evidence preparation failed"
_PUBLICATION_ERROR = "DeepSeek search evidence publication failed"


class DeepSeekEvidencePreparationError(ValueError):
    """Static failure for an invalid normalized manifest."""

    def __init__(self) -> None:
        super().__init__(_PREPARATION_ERROR)


class DeepSeekEvidencePublicationError(RuntimeError):
    """Static failure for ordinary local publication I/O."""

    def __init__(self) -> None:
        super().__init__(_PUBLICATION_ERROR)


def _valid_manifest(manifest: object) -> bool:
    if type(manifest) is not dict:
        return False
    # The offline smoke builder owns the semantic fields; this seam only keeps
    # bytes finite and JSON-safe, avoiding a second parser/validation framework.
    try:
        encoded = json.dumps(
            manifest,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    except TypeError, ValueError, UnicodeError:
        return False
    return bool(encoded) and len(encoded) <= MAX_MANIFEST_BYTES


def serialize_evidence_manifest(manifest: object) -> bytes:
    """Serialize one finite normalized manifest deterministically."""
    if not _valid_manifest(manifest):
        raise DeepSeekEvidencePreparationError() from None
    return json.dumps(
        manifest,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def write_private_evidence_bytes(manifest_bytes: bytes, trusted_parent: str) -> Path:
    """Atomically publish bytes in a new private run directory."""
    if (
        type(manifest_bytes) is not bytes
        or not manifest_bytes
        or len(manifest_bytes) > MAX_MANIFEST_BYTES
    ):
        raise DeepSeekEvidencePublicationError() from None
    if (
        type(trusted_parent) is not str
        or not trusted_parent
        or len(trusted_parent) > MAX_DIRECTORY_CHARACTERS
        or "\x00" in trusted_parent
    ):
        raise DeepSeekEvidencePublicationError() from None
    run_directory: Path | None = None
    temporary_path: Path | None = None
    final_path: Path | None = None
    try:
        run_directory = Path(
            tempfile.mkdtemp(prefix="deepseek-search-", dir=trusted_parent)
        )
        os.chmod(run_directory, 0o700)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".summary-", suffix=".tmp", dir=run_directory
        )
        temporary_path = Path(temporary_name)
        final_path = run_directory / EVIDENCE_FILENAME
        try:
            os.chmod(temporary_path, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(manifest_bytes)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            os.close(fd) if fd >= 0 else None
            raise
        os.replace(temporary_path, final_path)
        return final_path
    except Exception:
        for path in (temporary_path, final_path):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        if run_directory is not None:
            try:
                run_directory.rmdir()
            except OSError:
                pass
        raise DeepSeekEvidencePublicationError() from None


__all__ = [
    "DeepSeekEvidencePreparationError",
    "DeepSeekEvidencePublicationError",
    "EVIDENCE_FILENAME",
    "EVIDENCE_SCHEMA",
    "EVIDENCE_VERSION",
    "MAX_COUNTER",
    "MAX_DIRECTORY_CHARACTERS",
    "MAX_LATENCY_MS",
    "MAX_MANIFEST_BYTES",
    "serialize_evidence_manifest",
    "write_private_evidence_bytes",
]
