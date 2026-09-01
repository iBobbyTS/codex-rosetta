"""Reusable observability layer for LLM proxy servers.

This package provides framework-agnostic building blocks for metrics
collection, request logging, and SQLite persistence. Any HTTP proxy built on top of ``codex-rosetta`` can import
from here — no dependency on the gateway's config system or HTTP
server.

Typical usage::

    from codex_rosetta.observability import (
        MetricsCollector,
        PersistenceManager,
        RequestLog,
        RequestLogEntry,
    )

    metrics = MetricsCollector()
    persistence = PersistenceManager("/var/data/myproxy")
    request_log = RequestLog(persistence=persistence)
"""

from __future__ import annotations

from .metrics import MetricsCollector
from .persistence import (
    CompactionMappingCapacityError,
    PersistenceManager,
)
from .request_log import RequestLog, RequestLogEntry
from .tool_history_store import ToolHistoryCapacityError, ToolHistoryConflictError
from .retention import (
    DEFAULT_ERROR_MAX,
    DEFAULT_SUCCESS_MAX,
    MAX_REQUEST_LOG_RETENTION,
    resolve_request_log_caps,
    validate_retention_cap,
)

__all__ = [
    "DEFAULT_ERROR_MAX",
    "DEFAULT_SUCCESS_MAX",
    "MAX_REQUEST_LOG_RETENTION",
    "MetricsCollector",
    "CompactionMappingCapacityError",
    "PersistenceManager",
    "RequestLog",
    "RequestLogEntry",
    "ToolHistoryCapacityError",
    "ToolHistoryConflictError",
    "resolve_request_log_caps",
    "validate_retention_cap",
]
