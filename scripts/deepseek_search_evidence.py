"""Preparation and harness publication for private DeepSeek search evidence.

This module validates and serializes a deliberately small evidence manifest.
It also publishes prevalidated exact bytes for an explicit local harness. It
performs no configuration, credential, client, network, or runtime work.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import BinaryIO, Final, cast

EVIDENCE_SCHEMA: Final = "codex-rosetta.deepseek-search-evidence"
EVIDENCE_VERSION: Final = 1
EVIDENCE_FILENAME: Final = "summary.json"

MAX_MANIFEST_BYTES: Final = 16_384
MAX_DIRECTORY_CHARACTERS: Final = 1_024
MAX_COUNTER: Final = 1_000_000_000
MAX_LATENCY_MS: Final = 3_600_000

_PREPARATION_ERROR_MESSAGE: Final = "DeepSeek search evidence preparation failed"
_PUBLICATION_ERROR_MESSAGE: Final = "DeepSeek search evidence publication failed"
_HEX_DIGITS: Final = frozenset("0123456789abcdef")
_ROOT_KEYS: Final = frozenset(
    {
        "schema",
        "version",
        "mode",
        "status",
        "category",
        "execution",
        "provenance",
        "hashes",
        "counts",
        "latency_ms",
        "usage",
    }
)
_EXECUTION_KEYS: Final = frozenset({"provider_family", "execution_mode", "model"})
_PROVENANCE_KEYS: Final = frozenset(
    {
        "implementation_generation",
        "generation_2_live_proof",
        "generation_0_evidence",
    }
)
_HASH_KEYS: Final = frozenset({"request_sha256", "query_sha256", "result_sha256"})
_COUNT_KEYS: Final = frozenset(
    {"upstream_calls", "search_calls", "result_count", "citation_count"}
)
_USAGE_KEYS: Final = frozenset({"input_tokens", "output_tokens", "total_tokens"})


class DeepSeekEvidencePreparationError(ValueError):
    """Static, bounded failure for invalid evidence preparation."""

    def __init__(self) -> None:
        super().__init__(_PREPARATION_ERROR_MESSAGE)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class DeepSeekEvidencePublicationError(RuntimeError):
    """Static failure for private harness evidence publication."""

    def __init__(self) -> None:
        super().__init__(_PUBLICATION_ERROR_MESSAGE)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def _keys_are_exact(value: object, expected: frozenset[str]) -> bool:
    """Return whether an exact dict has exactly the expected string keys."""
    if type(value) is not dict:
        return False
    keys = tuple(dict.keys(value))
    return len(keys) == len(expected) and all(
        type(key) is str and key in expected for key in keys
    )


def _is_bounded_integer(value: object, maximum: int) -> bool:
    """Validate one exact non-negative integer within a fixed upper bound."""
    return type(value) is int and 0 <= value <= maximum


def _is_sha256(value: object) -> bool:
    """Validate one lowercase hexadecimal SHA-256 value."""
    return (
        type(value) is str
        and len(value) == 64
        and all(character in _HEX_DIGITS for character in value)
    )


def _manifest_is_allowed(manifest: object) -> bool:
    """Validate the exact recursive evidence manifest allowlist."""
    if not _keys_are_exact(manifest, _ROOT_KEYS):
        return False
    assert type(manifest) is dict
    execution = dict.get(manifest, "execution")
    provenance = dict.get(manifest, "provenance")
    hashes = dict.get(manifest, "hashes")
    counts = dict.get(manifest, "counts")
    usage = dict.get(manifest, "usage")
    if not all(
        (
            _keys_are_exact(execution, _EXECUTION_KEYS),
            _keys_are_exact(provenance, _PROVENANCE_KEYS),
            _keys_are_exact(hashes, _HASH_KEYS),
            _keys_are_exact(counts, _COUNT_KEYS),
            _keys_are_exact(usage, _USAGE_KEYS),
        )
    ):
        return False
    assert type(execution) is dict
    assert type(provenance) is dict
    assert type(hashes) is dict
    assert type(counts) is dict
    assert type(usage) is dict
    if not (
        dict.get(manifest, "schema") == EVIDENCE_SCHEMA
        and type(dict.get(manifest, "schema")) is str
        and dict.get(manifest, "version") == EVIDENCE_VERSION
        and type(dict.get(manifest, "version")) is int
        and dict.get(manifest, "mode") == "direct"
        and type(dict.get(manifest, "mode")) is str
        and dict.get(manifest, "status") == "completed"
        and type(dict.get(manifest, "status")) is str
        and dict.get(manifest, "category") == "success"
        and type(dict.get(manifest, "category")) is str
        and dict.get(execution, "provider_family") == "DEEPSEEK_NATIVE_RESPONSES"
        and type(dict.get(execution, "provider_family")) is str
        and dict.get(execution, "execution_mode") == "NATIVE_RESPONSES_HOSTED_SEARCH"
        and type(dict.get(execution, "execution_mode")) is str
        and dict.get(execution, "model") == "deepseek-v4-flash"
        and type(dict.get(execution, "model")) is str
        and dict.get(provenance, "implementation_generation") == 2
        and type(dict.get(provenance, "implementation_generation")) is int
        and dict.get(provenance, "generation_2_live_proof") is False
        and dict.get(provenance, "generation_0_evidence") == "referenced-only"
        and type(dict.get(provenance, "generation_0_evidence")) is str
    ):
        return False
    if not all(_is_sha256(dict.get(hashes, key)) for key in _HASH_KEYS):
        return False
    if dict.get(counts, "upstream_calls") != 1:
        return False
    if type(dict.get(counts, "upstream_calls")) is not int:
        return False
    if not all(
        _is_bounded_integer(dict.get(counts, key), MAX_COUNTER)
        for key in _COUNT_KEYS - {"upstream_calls"}
    ):
        return False
    if not _is_bounded_integer(dict.get(manifest, "latency_ms"), MAX_LATENCY_MS):
        return False
    if not all(
        _is_bounded_integer(dict.get(usage, key), MAX_COUNTER) for key in _USAGE_KEYS
    ):
        return False
    return dict.get(usage, "total_tokens") == (
        cast(int, dict.get(usage, "input_tokens"))
        + cast(int, dict.get(usage, "output_tokens"))
    )


def _json_dumps(manifest: object) -> str:
    """Serialize through a narrow injectable stdlib seam."""
    return json.dumps(
        manifest,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _encode_text(value: object, maximum_bytes: int) -> bytes | None:
    """Strictly encode one bounded exact string without normalization."""
    if type(value) is not str or not value or "\x00" in value:
        return None
    try:
        encoded = str.encode(value, "utf-8", "strict")
    except UnicodeError:
        return None
    return encoded if len(encoded) <= maximum_bytes else None


def _serialize_manifest(manifest: object) -> bytes | None:
    """Validate and deterministically encode one bounded manifest."""
    if not _manifest_is_allowed(manifest):
        return None
    assert type(manifest) is dict
    serialized = _json_dumps(manifest)
    return _encode_text(serialized, MAX_MANIFEST_BYTES)


def serialize_evidence_manifest(manifest: object) -> bytes:
    """Return deterministic bytes for one exact evidence manifest.

    Raises:
        DeepSeekEvidencePreparationError: If the manifest is not allowlisted.
    """
    encoded = _serialize_manifest(manifest)
    if encoded is None:
        raise DeepSeekEvidencePreparationError() from None
    return encoded


def _open_temp_file(file_descriptor: int) -> BinaryIO:
    """Open one exclusively created temporary descriptor for binary writing."""
    return os.fdopen(file_descriptor, "wb", closefd=True)


def _fsync_temp_file(stream: BinaryIO) -> None:
    """Synchronize one fully flushed temporary evidence file."""
    os.fsync(stream.fileno())


def _replace_temp(temporary_path: Path, final_path: Path) -> None:
    """Publish one complete temporary file through same-directory replace."""
    os.replace(temporary_path, final_path)


def _close_best_effort(stream: BinaryIO | None) -> None:
    """Best-effort close one publication stream during cleanup."""
    if stream is None:
        return
    try:
        stream.close()
    except Exception:
        pass


def _close_descriptor_best_effort(file_descriptor: int | None) -> None:
    """Best-effort close a descriptor not yet transferred to a stream."""
    if file_descriptor is None:
        return
    try:
        os.close(file_descriptor)
    except Exception:
        pass


def _unlink_best_effort(path: Path | None) -> None:
    """Best-effort remove one known publication path."""
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _rmdir_best_effort(path: Path | None) -> None:
    """Best-effort remove one writer-created directory when it is empty."""
    if path is None:
        return
    try:
        path.rmdir()
    except Exception:
        pass


def _cleanup_private_publication(
    stream: BinaryIO | None,
    file_descriptor: int | None,
    temporary_path: Path | None,
    final_path: Path | None,
    run_directory: Path | None,
) -> None:
    """Best-effort cleanup paths and handles owned by one writer invocation."""
    _close_best_effort(stream)
    _close_descriptor_best_effort(file_descriptor)
    _unlink_best_effort(temporary_path)
    _unlink_best_effort(final_path)
    _rmdir_best_effort(run_directory)


def write_private_evidence_bytes(manifest_bytes: bytes, trusted_parent: str) -> Path:
    """Atomically publish sanitized bytes below one trusted harness parent.

    Args:
        manifest_bytes: Exact prevalidated and presanitized manifest bytes.
        trusted_parent: Existing trusted parent directory selected by the harness.

    Returns:
        The final ``summary.json`` path in a new private run directory.

    Raises:
        DeepSeekEvidencePublicationError: If validation or ordinary I/O fails.
    """
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
    file_descriptor: int | None = None
    stream: BinaryIO | None = None
    ordinary_failure = False
    try:
        run_directory = Path(
            tempfile.mkdtemp(prefix="deepseek-search-", dir=trusted_parent)
        )
        os.chmod(run_directory, 0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".summary-", suffix=".tmp", dir=run_directory
        )
        file_descriptor = descriptor
        temporary_path = Path(temporary_name)
        os.chmod(temporary_path, 0o600)
        final_path = run_directory / EVIDENCE_FILENAME

        stream = _open_temp_file(file_descriptor)
        file_descriptor = None
        written = stream.write(manifest_bytes)
        if written != len(manifest_bytes):
            raise OSError("short evidence write")
        stream.flush()
        _fsync_temp_file(stream)
        stream.close()
        stream = None
        _replace_temp(temporary_path, final_path)
    except Exception:
        _cleanup_private_publication(
            stream, file_descriptor, temporary_path, final_path, run_directory
        )
        ordinary_failure = True

    if ordinary_failure or final_path is None:
        raise DeepSeekEvidencePublicationError() from None
    return final_path


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
