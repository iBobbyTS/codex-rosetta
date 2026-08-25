"""Optional JSONL diagnostics for gateway streaming conversions."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TextIO

from codex_rosetta.auto_detect import ProviderType
from codex_rosetta.observability.redaction import SecretRedactor

logger = logging.getLogger("codex-rosetta-gateway")

DEFAULT_MAX_CHARS = 20_000
DEFAULT_TRACE_PATH = "~/.config/codex-rosetta-gateway/log.jsonl"


@dataclass
class StreamTraceConfig:
    """Runtime configuration for optional stream trace logging."""

    enabled: bool = False
    filter: str = ""
    path: str = ""
    max_string_chars: int = DEFAULT_MAX_CHARS

    @classmethod
    def from_mapping(cls, value: Any) -> StreamTraceConfig:
        """Build a trace config from ``server.stream_trace`` config data."""
        if not isinstance(value, dict):
            return cls()

        try:
            max_string_chars = int(value.get("max_string_chars", DEFAULT_MAX_CHARS))
        except TypeError, ValueError:
            max_string_chars = DEFAULT_MAX_CHARS
        if max_string_chars <= 0:
            max_string_chars = DEFAULT_MAX_CHARS

        return cls(
            enabled=bool(value.get("enabled", False)),
            filter=str(value.get("filter", "") or ""),
            path=str(value.get("path", "") or "").strip(),
            max_string_chars=max_string_chars,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable config dict."""
        return {
            "enabled": self.enabled,
            "filter": self.filter,
            "path": self.path,
            "max_string_chars": self.max_string_chars,
        }


@dataclass(frozen=True)
class PreparedStreamTraceUpdate:
    """Fully constructed trace state ready for an assignment-only commit."""

    config: StreamTraceConfig
    redactor: SecretRedactor


class _StreamTraceWriteHealth:
    """Concurrency-safe outage notifications for one configured trace path."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._active = True
        self._outage = False

    def deactivate(self) -> None:
        """Silence events from loggers retained after a path replacement."""
        with self._lock:
            self._active = False
            self._outage = False

    def record_failure(self, error: OSError) -> None:
        """Report only the first failure in the current outage cycle."""
        with self._lock:
            if not self._active or self._outage:
                return
            self._outage = True
            logger.warning("Stream trace writing paused after failure: %s", error)

    def record_success(self) -> None:
        """Report only the first successful write after an outage."""
        with self._lock:
            if not self._active or not self._outage:
                return
            self._outage = False
            logger.warning("Stream trace writing resumed: %s", self.path)


class StreamTraceState:
    """Mutable stream trace settings used by the running gateway."""

    def __init__(
        self,
        config: StreamTraceConfig | None = None,
        *,
        token_values: Iterable[str] = (),
    ) -> None:
        self._state_lock = threading.Lock()
        self._config = config or StreamTraceConfig()
        self._write_health = _StreamTraceWriteHealth(
            _resolve_trace_path(self._config.path)
        )
        self._redactor = SecretRedactor(token_values)

    @property
    def config(self) -> StreamTraceConfig:
        """Return the current runtime trace configuration."""
        with self._state_lock:
            return self._config

    @config.setter
    def config(self, config: StreamTraceConfig) -> None:
        """Assign trace settings and silently reset health when the path changes."""
        path = _resolve_trace_path(config.path)
        with self._state_lock:
            self._config = config
            if path == self._write_health.path:
                return
            self._write_health.deactivate()
            self._write_health = _StreamTraceWriteHealth(path)

    def prepare_update(
        self,
        config: StreamTraceConfig,
        *,
        token_values: Iterable[str] | None = None,
    ) -> PreparedStreamTraceUpdate:
        """Construct replacement trace state without mutating live settings."""
        redactor = (
            SecretRedactor(token_values) if token_values is not None else self._redactor
        )
        return PreparedStreamTraceUpdate(config=config, redactor=redactor)

    def commit_update(self, prepared: PreparedStreamTraceUpdate) -> None:
        """Commit prepared trace settings using assignments only."""
        self.config = prepared.config
        self._redactor = prepared.redactor

    def update(
        self,
        config: StreamTraceConfig,
        *,
        token_values: Iterable[str] | None = None,
    ) -> None:
        """Apply new settings without restarting the gateway."""
        self.commit_update(self.prepare_update(config, token_values=token_values))

    def create_logger(
        self,
        *,
        request_id: str | None,
        request_log_id: str | None,
        model: str,
        source_provider: ProviderType,
        target_provider: ProviderType,
        provider_name: str,
        force: bool = False,
    ) -> StreamTraceLogger | None:
        """Create a trace logger for one stream if current settings match."""
        with self._state_lock:
            config = self._config
            redactor = self._redactor
            write_health = self._write_health
        if not config.enabled:
            return None

        if not force and not _matches_filter(
            config.filter,
            model=model,
            source_provider=source_provider,
            target_provider=target_provider,
            provider_name=provider_name,
        ):
            return None

        return StreamTraceLogger(
            path=_resolve_trace_path(config.path),
            request_id=request_id,
            request_log_id=request_log_id,
            model=model,
            source_provider=source_provider,
            target_provider=target_provider,
            provider_name=provider_name,
            max_string_chars=config.max_string_chars,
            redactor=redactor,
            write_health=write_health,
        )


class StreamTraceLogger:
    """Write per-stream conversion diagnostics to an external JSONL file."""

    def __init__(
        self,
        *,
        path: Path,
        request_id: str | None,
        request_log_id: str | None,
        model: str,
        source_provider: ProviderType,
        target_provider: ProviderType,
        provider_name: str,
        max_string_chars: int = DEFAULT_MAX_CHARS,
        redactor: SecretRedactor | None = None,
        write_health: _StreamTraceWriteHealth | None = None,
    ) -> None:
        self.path = path
        self.request_id = request_id
        self.request_log_id = request_log_id
        self.model = model
        self.source_provider = source_provider
        self.target_provider = target_provider
        self.provider_name = provider_name
        self.max_string_chars = max_string_chars
        self._redactor = redactor or SecretRedactor()
        self._write_health = write_health or _StreamTraceWriteHealth(path)
        self._defer_response = False
        self._pending_response_file: TextIO | None = None

    def defer_response_diagnostics(self) -> None:
        """Hold subsequent response records until the request is proven safe."""
        if self._defer_response:
            raise RuntimeError("Stream response diagnostics are already deferred")
        self._defer_response = True
        self._open_pending_response_file()

    def _open_pending_response_file(self) -> TextIO | None:
        """Open a deferred spool while keeping later trace attempts retryable."""
        try:
            self._ensure_parent_directory()
            pending_file = tempfile.TemporaryFile(
                mode="w+",
                encoding="utf-8",
                newline="",
                dir=self.path.parent,
            )
        except OSError as exc:
            self._write_health.record_failure(exc)
            return None
        self._pending_response_file = pending_file
        return pending_file

    def finish_response_diagnostics(
        self,
        *,
        safe: bool,
    ) -> None:
        """Release a completed response batch or discard incomplete diagnostics."""
        if not self._defer_response:
            return
        pending_file = self._pending_response_file
        self._defer_response = False
        self._pending_response_file = None
        if pending_file is None:
            return
        try:
            if safe:
                try:
                    pending_file.flush()
                    pending_file.seek(0)
                except OSError as exc:
                    self._write_health.record_failure(exc)
                else:
                    self._append_file(pending_file)
        finally:
            try:
                pending_file.close()
            except OSError:
                pass

    def log(
        self,
        stage: str,
        data: Any,
        *,
        chunk_index: int | None = None,
        response_redaction: Literal["exact", "protocol_fields"] = "exact",
    ) -> None:
        """Append one trace record to the JSONL file."""
        use_protocol_fields = (
            self._defer_response or response_redaction == "protocol_fields"
        )
        redacted_data = _truncate(
            self._redactor.redact_protocol_diagnostic(data)
            if use_protocol_fields
            else self._redactor.redact(data),
            self.max_string_chars,
        )
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": self.request_id,
            "request_log_id": self.request_log_id,
            "model": self.model,
            "source_provider": self.source_provider,
            "target_provider": self.target_provider,
            "provider_name": self.provider_name,
            "chunk_index": chunk_index,
            "stage": stage,
            "data": redacted_data,
        }
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        if self._defer_response:
            pending_file = self._pending_response_file
            if pending_file is None:
                pending_file = self._open_pending_response_file()
                if pending_file is None:
                    return
            try:
                pending_file.write(line)
            except OSError as exc:
                self._pending_response_file = None
                try:
                    pending_file.close()
                except OSError:
                    pass
                self._write_health.record_failure(exc)
            else:
                self._write_health.record_success()
            return
        self._append_lines([line])

    def log_full(self, stage: str, data: Any) -> None:
        """Append a redacted, non-truncated diagnostic record.

        This is intentionally separate from ``log`` because the enabled trace
        mode keeps the original request body complete instead of truncating it.
        """
        if self._defer_response:
            return

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": self.request_id,
            "request_log_id": self.request_log_id,
            "model": self.model,
            "source_provider": self.source_provider,
            "target_provider": self.target_provider,
            "provider_name": self.provider_name,
            "chunk_index": None,
            "stage": stage,
            "data": self._redactor.redact(data),
        }
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        self._append_lines([line])

    def _append_lines(self, lines: list[str]) -> None:
        """Append a prepared record batch to the configured JSONL path."""
        try:
            self._ensure_parent_directory()
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write("".join(lines))
        except OSError as exc:
            self._write_health.record_failure(exc)
        else:
            self._write_health.record_success()

    def _append_file(self, source: TextIO) -> None:
        """Append a prepared trace spool without materializing it in memory."""
        try:
            self._ensure_parent_directory()
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as target:
                while chunk := source.read(1_048_576):
                    target.write(chunk)
        except OSError as exc:
            self._write_health.record_failure(exc)
        else:
            self._write_health.record_success()

    def _ensure_parent_directory(self) -> None:
        """Create the owner-only trace directory when it does not yet exist."""
        parent_existed = self.path.parent.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not parent_existed:
            os.chmod(self.path.parent, 0o700)


def _matches_filter(
    filter_value: str,
    *,
    model: str,
    source_provider: ProviderType,
    target_provider: ProviderType,
    provider_name: str,
) -> bool:
    filter_value = filter_value.strip()
    if not filter_value:
        return True

    haystack = " ".join(
        [model, str(source_provider), str(target_provider), provider_name]
    ).lower()
    needles = [part.strip().lower() for part in filter_value.split(",")]
    return any(needle and needle in haystack for needle in needles)


def _resolve_trace_path(path: str | None) -> Path:
    return Path(str(path or "").strip() or DEFAULT_TRACE_PATH).expanduser()


def _truncate(value: Any, max_string_chars: int) -> Any:
    if isinstance(value, str):
        if len(value) <= max_string_chars:
            return value
        remaining = len(value) - max_string_chars
        return f"{value[:max_string_chars]}...[{remaining} more chars]"
    if isinstance(value, list):
        return [_truncate(item, max_string_chars) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _truncate(item, max_string_chars) for key, item in value.items()
        }
    return value
