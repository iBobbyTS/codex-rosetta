"""Pure preparation contract for private DeepSeek search evidence.

This module validates and serializes a deliberately small evidence manifest.
It performs no filesystem, configuration, credential, client, or runtime work;
the prepared value is consumed by the separate publication section.
"""

from __future__ import annotations

import json
from typing import Final, cast

EVIDENCE_SCHEMA: Final = "codex-rosetta.deepseek-search-evidence"
EVIDENCE_VERSION: Final = 1
EVIDENCE_FILENAME: Final = "summary.json"

MAX_MANIFEST_BYTES: Final = 16_384
MAX_DIRECTORY_CHARACTERS: Final = 1_024
MAX_DIRECTORY_BYTES: Final = 4_096
MAX_SCAN_VALUE_BYTES: Final = 1_048_576
MAX_SCAN_VALUE_COUNT: Final = 32
MAX_COUNTER: Final = 1_000_000_000
MAX_LATENCY_MS: Final = 3_600_000

_PREPARATION_ERROR_MESSAGE: Final = "DeepSeek search evidence preparation failed"
_PREPARED_TOKEN: Final = object()
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


class PreparedEvidencePublication:
    """Immutable validated input for the later filesystem publisher."""

    __slots__ = ("_directory", "_final_path", "_manifest_bytes")
    _directory: str
    _final_path: str
    _manifest_bytes: bytes

    def __init__(
        self,
        token: object,
        manifest_bytes: object,
        directory: object,
        final_path: object,
    ) -> None:
        try:
            if (
                token is not _PREPARED_TOKEN
                or type(manifest_bytes) is not bytes
                or type(directory) is not str
                or type(final_path) is not str
            ):
                raise DeepSeekEvidencePreparationError() from None
            object.__setattr__(self, "_manifest_bytes", manifest_bytes)
            object.__setattr__(self, "_directory", directory)
            object.__setattr__(self, "_final_path", final_path)
        except BaseException as signal:
            _scrub_signal(signal)
            del signal
            raise
        finally:
            del token, manifest_bytes, directory, final_path

    @property
    def manifest_bytes(self) -> bytes:
        """Return the validated deterministic manifest bytes."""
        return self._manifest_bytes

    @property
    def directory(self) -> str:
        """Return the validated evidence directory string."""
        return self._directory

    @property
    def final_path(self) -> str:
        """Return the validated final manifest path."""
        return self._final_path

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("Prepared evidence publication is immutable") from None

    def __repr__(self) -> str:
        return "<PreparedEvidencePublication>"


def _scrub_signal(signal: BaseException) -> None:
    """Detach caller-derived exception data while preserving signal identity."""
    try:
        signal.args = ()
        signal.__cause__ = None
        signal.__context__ = None
    finally:
        del signal


def _keys_are_exact(value: object, expected: frozenset[str]) -> bool:
    """Return whether an exact dict has exactly the expected string keys."""
    try:
        if type(value) is not dict:
            return False
        keys = tuple(dict.keys(value))
        return len(keys) == len(expected) and all(
            type(key) is str and key in expected for key in keys
        )
    except BaseException as signal:
        _scrub_signal(signal)
        del signal
        raise
    finally:
        if "keys" in locals():
            del keys
        del value, expected


def _is_bounded_integer(value: object, maximum: int) -> bool:
    """Validate one exact non-negative integer within a fixed upper bound."""
    try:
        return type(value) is int and 0 <= value <= maximum
    except BaseException as signal:
        _scrub_signal(signal)
        del signal
        raise
    finally:
        del value, maximum


def _is_sha256(value: object) -> bool:
    """Validate one lowercase hexadecimal SHA-256 value."""
    try:
        return (
            type(value) is str
            and len(value) == 64
            and all(character in _HEX_DIGITS for character in value)
        )
    except BaseException as signal:
        _scrub_signal(signal)
        del signal
        raise
    finally:
        del value


def _manifest_is_allowed(manifest: object) -> bool:
    """Validate the exact recursive evidence manifest allowlist."""
    execution: object = None
    provenance: object = None
    hashes: object = None
    counts: object = None
    usage: object = None
    try:
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
            and dict.get(execution, "execution_mode")
            == "NATIVE_RESPONSES_HOSTED_SEARCH"
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
            _is_bounded_integer(dict.get(usage, key), MAX_COUNTER)
            for key in _USAGE_KEYS
        ):
            return False
        return cast(int, dict.get(usage, "total_tokens")) == (
            cast(int, dict.get(usage, "input_tokens"))
            + cast(int, dict.get(usage, "output_tokens"))
        )
    except BaseException as signal:
        _scrub_signal(signal)
        del signal
        raise
    finally:
        del manifest, execution, provenance, hashes, counts, usage


def _json_dumps(manifest: object) -> str:
    """Serialize through a narrow injectable stdlib seam."""
    try:
        return json.dumps(
            manifest,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except BaseException as signal:
        _scrub_signal(signal)
        del signal
        raise
    finally:
        del manifest


def _encode_text(value: object, maximum_bytes: int) -> bytes | None:
    """Strictly encode one bounded exact string without normalization."""
    encoded: bytes | None = None
    try:
        if type(value) is not str or not value or "\x00" in value:
            return None
        encoded = str.encode(value, "utf-8", "strict")
        if len(encoded) > maximum_bytes:
            return None
        return encoded
    except UnicodeError:
        return None
    except BaseException as signal:
        _scrub_signal(signal)
        del signal
        raise
    finally:
        del value, maximum_bytes, encoded


def _serialize_manifest(manifest: object) -> bytes | None:
    """Validate and deterministically encode one bounded manifest."""
    serialized: str | None = None
    encoded: bytes | None = None
    try:
        if not _manifest_is_allowed(manifest):
            return None
        assert type(manifest) is dict
        serialized = _json_dumps(manifest)
        encoded = _encode_text(serialized, MAX_MANIFEST_BYTES)
        return encoded
    except Exception as error:
        if isinstance(error, MemoryError):
            _scrub_signal(error)
            del error
            raise
        return None
    except BaseException as signal:
        _scrub_signal(signal)
        del signal
        raise
    finally:
        del manifest, serialized, encoded


def serialize_evidence_manifest(manifest: object) -> bytes:
    """Return deterministic bytes for one exact evidence manifest.

    Raises:
        DeepSeekEvidencePreparationError: If the manifest is not allowlisted.
    """
    encoded: bytes | None = None
    try:
        encoded = _serialize_manifest(manifest)
    except BaseException as signal:
        _scrub_signal(signal)
        del signal
        raise
    finally:
        del manifest
    if encoded is None:
        raise DeepSeekEvidencePreparationError() from None
    return encoded


def _encode_scan_values(values: object) -> tuple[bytes, ...] | None:
    """Strictly encode one bounded tuple of protected scan values."""
    encoded_values: list[bytes] | None = None
    encoded: bytes | None = None
    value: object = None
    try:
        if (
            type(values) is not tuple
            or not values
            or len(values) > MAX_SCAN_VALUE_COUNT
        ):
            return None
        encoded_values = []
        for value in values:
            encoded = _encode_text(value, MAX_SCAN_VALUE_BYTES)
            if encoded is None:
                return None
            encoded_values.append(encoded)
            encoded = None
        return tuple(encoded_values)
    except Exception as error:
        if isinstance(error, MemoryError):
            _scrub_signal(error)
            del error
            raise
        return None
    except BaseException as signal:
        _scrub_signal(signal)
        del signal
        raise
    finally:
        if encoded_values is not None:
            encoded_values.clear()
        del values, encoded_values, encoded, value


def _prepare_paths(directory: object) -> tuple[str, str, bytes, bytes] | None:
    """Validate and encode the directory and exact final summary path."""
    final_path: str | None = None
    encoded_directory: bytes | None = None
    encoded_final_path: bytes | None = None
    try:
        if (
            type(directory) is not str
            or len(directory) > MAX_DIRECTORY_CHARACTERS
            or directory.endswith("/")
        ):
            return None
        encoded_directory = _encode_text(directory, MAX_DIRECTORY_BYTES)
        if encoded_directory is None:
            return None
        final_path = f"{directory}/{EVIDENCE_FILENAME}"
        encoded_final_path = _encode_text(
            final_path, MAX_DIRECTORY_BYTES + len(EVIDENCE_FILENAME) + 1
        )
        if encoded_final_path is None:
            return None
        return directory, final_path, encoded_directory, encoded_final_path
    except Exception as error:
        if isinstance(error, MemoryError):
            _scrub_signal(error)
            del error
            raise
        return None
    except BaseException as signal:
        _scrub_signal(signal)
        del signal
        raise
    finally:
        del directory, final_path, encoded_directory, encoded_final_path


def _contains_collision(targets: object, protected: object) -> bool:
    """Return whether any exact protected bytes occur in any target."""
    try:
        if type(targets) is not tuple or type(protected) is not tuple:
            return True
        if not all(type(item) is bytes for item in targets + protected):
            return True
        byte_targets = cast(tuple[bytes, ...], targets)
        byte_protected = cast(tuple[bytes, ...], protected)
        return any(
            needle in target for target in byte_targets for needle in byte_protected
        )
    except BaseException as signal:
        _scrub_signal(signal)
        del signal
        raise
    finally:
        del targets, protected


def prepare_evidence_publication(
    manifest: object,
    directory: object,
    *,
    protected_tokens: object,
    protected_bodies: object,
) -> PreparedEvidencePublication:
    """Validate manifest, paths, and three collision targets without I/O.

    Raises:
        DeepSeekEvidencePreparationError: If any value is invalid or collides.
    """
    encoded_manifest: bytes | None = None
    paths: tuple[str, str, bytes, bytes] | None = None
    encoded_tokens: tuple[bytes, ...] | None = None
    encoded_bodies: tuple[bytes, ...] | None = None
    prepared: PreparedEvidencePublication | None = None
    validated_directory: str | None = None
    final_path: str | None = None
    encoded_directory: bytes | None = None
    encoded_final_path: bytes | None = None
    targets: tuple[bytes, ...] | None = None
    protected: tuple[bytes, ...] | None = None
    failed = False
    try:
        encoded_manifest = _serialize_manifest(manifest)
        paths = _prepare_paths(directory)
        encoded_tokens = _encode_scan_values(protected_tokens)
        encoded_bodies = _encode_scan_values(protected_bodies)
        if (
            encoded_manifest is None
            or paths is None
            or encoded_tokens is None
            or encoded_bodies is None
        ):
            failed = True
        else:
            validated_directory, final_path, encoded_directory, encoded_final_path = (
                paths
            )
            targets = (encoded_manifest, encoded_directory, encoded_final_path)
            protected = encoded_tokens + encoded_bodies
            if _contains_collision(targets, protected):
                failed = True
            else:
                prepared = PreparedEvidencePublication(
                    _PREPARED_TOKEN,
                    encoded_manifest,
                    validated_directory,
                    final_path,
                )
    except Exception as error:
        if isinstance(error, MemoryError):
            _scrub_signal(error)
            del error
            raise
        failed = True
    except BaseException as signal:
        _scrub_signal(signal)
        del signal
        raise
    finally:
        del (
            manifest,
            directory,
            protected_tokens,
            protected_bodies,
            encoded_manifest,
            paths,
            encoded_tokens,
            encoded_bodies,
            validated_directory,
            final_path,
            encoded_directory,
            encoded_final_path,
            targets,
            protected,
        )
    if failed or prepared is None:
        del prepared
        raise DeepSeekEvidencePreparationError() from None
    return prepared


__all__ = [
    "DeepSeekEvidencePreparationError",
    "EVIDENCE_FILENAME",
    "EVIDENCE_SCHEMA",
    "EVIDENCE_VERSION",
    "MAX_COUNTER",
    "MAX_DIRECTORY_BYTES",
    "MAX_DIRECTORY_CHARACTERS",
    "MAX_LATENCY_MS",
    "MAX_MANIFEST_BYTES",
    "MAX_SCAN_VALUE_BYTES",
    "MAX_SCAN_VALUE_COUNT",
    "PreparedEvidencePublication",
    "prepare_evidence_publication",
    "serialize_evidence_manifest",
]
