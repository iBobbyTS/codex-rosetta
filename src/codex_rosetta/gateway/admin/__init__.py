"""Admin panel for the codex-rosetta gateway."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from codex_rosetta.observability import (
    MetricsCollector,
    PersistenceManager,
    RequestLog,
)

from ..stream_trace import StreamTraceState
from .runtime import AdminRuntimeState

if TYPE_CHECKING:
    from ..config import GatewayConfig

__all__ = ["setup_admin", "MetricsCollector", "RequestLog", "PersistenceManager"]

logger = logging.getLogger("codex-rosetta-gateway")


def _resolve_log_caps(config: GatewayConfig) -> tuple[int, int]:
    """Return request-log caps validated during config construction."""
    return (
        config.request_log_success_max,
        config.request_log_error_max,
    )


def setup_admin(
    app: Any,
    config: GatewayConfig,
    config_path: str | None,
) -> None:
    """Initialize admin panel state on the app.

    Routes are registered separately via ``register_admin_routes`` before
    calling this function.
    """
    token_values = set(config.token_values)
    internal_token = getattr(app, "internal_token", None)
    if internal_token:
        token_values.add(internal_token)
    metrics = MetricsCollector()
    metrics.update_token_values(token_values)

    # Set up SQLite persistence alongside the config file
    persistence: PersistenceManager | None = None
    if config_path:
        data_dir = os.path.join(os.path.dirname(config_path), "data")
        success_max, error_max = _resolve_log_caps(config)
        persistence = PersistenceManager(
            data_dir,
            success_max=success_max,
            error_max=error_max,
            token_values=token_values,
        )

        # Restore persisted metrics counters
        saved_metrics = persistence.load_metrics()
        if saved_metrics:
            metrics.load_counters(saved_metrics)
            logger.info(
                "Loaded metrics from disk (total_requests=%d)",
                metrics.total_requests,
            )

    # Backfill target_provider_name for legacy log entries
    if persistence is not None:
        model_to_provider = {model: config.models[model] for model in config.models}
        backfilled = persistence.backfill_provider_names(model_to_provider)
        if backfilled:
            logger.info(
                "Backfilled target_provider_name for %d log entries",
                backfilled,
            )

    # Request log delegates to persistence when available
    request_log = RequestLog(persistence=persistence)

    # On-demand deep profiling state
    from codex_rosetta.observability import ProfilerState

    profiler_state = ProfilerState()

    app.metrics = metrics
    app.request_log = request_log
    app.persistence = persistence
    app.gateway_config = config
    app.config_path = config_path
    app.profiler_state = profiler_state
    app.stream_trace_state = StreamTraceState(
        config.stream_trace, token_values=token_values
    )
    app.admin_runtime_state = AdminRuntimeState()
