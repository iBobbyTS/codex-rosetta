"""Validated request-log retention policy shared by all runtime owners."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

DEFAULT_SUCCESS_MAX = 50_000
DEFAULT_ERROR_MAX = 10_000
MAX_REQUEST_LOG_RETENTION = 1_000_000


def validate_retention_cap(value: Any, *, field: str) -> int:
    """Validate one request-log retention cap and return it unchanged."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    if value > MAX_REQUEST_LOG_RETENTION:
        raise ValueError(f"{field} must be at most {MAX_REQUEST_LOG_RETENTION}")
    return value


def _optional_env_cap(name: str, environ: Mapping[str, str]) -> int | None:
    raw = environ.get(name)
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"environment variable {name} must be an integer") from None
    return validate_retention_cap(value, field=f"environment variable {name}")


def resolve_request_log_caps(
    request_log: Any,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[int, int]:
    """Resolve and validate success/error caps with environment precedence."""
    if request_log is None:
        request_log = {}
    if not isinstance(request_log, Mapping):
        raise ValueError("config: server.request_log must be an object")

    unsupported = set(request_log) - {"success_max", "error_max"}
    if unsupported:
        raise ValueError(
            "config: server.request_log contains unsupported fields: "
            f"{sorted(unsupported)}"
        )

    configured: dict[str, int] = {}
    for key in ("success_max", "error_max"):
        if key in request_log:
            configured[key] = validate_retention_cap(
                request_log[key],
                field=f"config: server.request_log.{key}",
            )

    active_environ = os.environ if environ is None else environ
    success_env = _optional_env_cap("REQUEST_LOG_SUCCESS_MAX", active_environ)
    error_env = _optional_env_cap("REQUEST_LOG_ERROR_MAX", active_environ)

    success = success_env
    if success is None:
        success = configured.get("success_max")
    error = error_env
    if error is None:
        error = configured.get("error_max")

    return (
        DEFAULT_SUCCESS_MAX if success is None else success,
        DEFAULT_ERROR_MAX if error is None else error,
    )
