"""Request log for the gateway admin panel.

This module re-exports from :mod:`codex_rosetta.observability.request_log`
for backward compatibility.  New code should import directly from
``codex_rosetta.observability``.
"""

from __future__ import annotations

from codex_rosetta.observability.request_log import (  # noqa: F401
    RequestLog,
    RequestLogEntry,
)

__all__ = ["RequestLog", "RequestLogEntry"]
