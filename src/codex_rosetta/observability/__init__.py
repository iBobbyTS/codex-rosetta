"""Reusable observability layer for LLM proxy servers.

This package provides framework-agnostic building blocks for metrics
collection, request logging, SQLite persistence, and on-demand
profiling.  Any HTTP proxy built on top of ``codex-rosetta`` can import
from here — no dependency on the gateway's config system or HTTP
server.

Typical usage::

    from codex_rosetta.observability import (
        MetricsCollector,
        PersistenceManager,
        ProfilerState,
        RequestLog,
        RequestLogEntry,
    )

    metrics = MetricsCollector()
    persistence = PersistenceManager("/var/data/myproxy")
    request_log = RequestLog(persistence=persistence)
    profiler = ProfilerState()
"""

from __future__ import annotations

from .error_dump import (
    compress_body,
    compute_body_hash,
    decompress_body,
    dump_error,
    offload_images,
)
from .metrics import MetricsCollector
from .persistence import (
    CompactionMappingCapacityError,
    PersistenceManager,
    ToolMappingCapacityError,
)
from .profiling import ProfilerState
from .request_log import RequestLog, RequestLogEntry
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
    "ProfilerState",
    "RequestLog",
    "RequestLogEntry",
    "ToolMappingCapacityError",
    "compress_body",
    "compute_body_hash",
    "decompress_body",
    "dump_error",
    "offload_images",
    "resolve_request_log_caps",
    "validate_retention_cap",
]
