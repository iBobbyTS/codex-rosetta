"""Public gateway health payload presentation."""

from __future__ import annotations

from typing import Any

from codex_rosetta.observability.metrics import MetricsCollector


def build_health_payload(metrics: MetricsCollector) -> dict[str, Any]:
    """Build the public operational health payload with token-safe errors."""
    snapshot = metrics.snapshot()
    provider_health = metrics.redact_sensitive(metrics.provider_health_snapshot())

    return {
        "status": "degraded" if metrics.any_critical_provider() else "ok",
        "uptime_seconds": snapshot["uptime_seconds"],
        "requests_total": snapshot["total_requests"],
        "errors_last_hour": metrics.errors_last_hour(),
        "providers": provider_health,
    }


def build_readiness_payload(
    metrics: MetricsCollector,
) -> tuple[dict[str, Any], int]:
    """Build the public readiness payload and its HTTP status code."""
    if not metrics.any_critical_provider():
        return {"status": "ready"}, 200
    provider_health = metrics.redact_sensitive(metrics.provider_health_snapshot())
    return {"status": "not_ready", "providers": provider_health}, 503
