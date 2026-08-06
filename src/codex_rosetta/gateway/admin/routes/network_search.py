"""Admin-only diagnostics for the Codex Search endpoint."""

from __future__ import annotations

import asyncio
import math
import secrets
from typing import Any

from codex_rosetta._vendor.httpserver import JSONResponse, Response

from ...auth import INTERNAL_ADMIN_PRINCIPAL, api_key_principal_var
from ...codex_auxiliary import handle_codex_auxiliary
from ...config import CONFIGURED_RESPONSES_WEB_SEARCH_PROVIDER, GatewayConfig
from ...search_provider_chain import (
    SearchProviderAttemptCategory,
    SearchProviderChainCoordinator,
)
from ...search_provider_candidates import TavilySearchProviderCandidate
from ...search_usage import TavilyUsage, TavilyUsageState
from ...tool_profiles import route_tool_state

SEARCH_TEST_QUERY = "latest python release version"
TAVILY_USAGE_MAX_CONCURRENCY = 8
TAVILY_USAGE_ROW_TIMEOUT_SECONDS = 12.0


def _safe_usage_value(value: Any, *, upper_bound: int | None = None) -> int | None:
    """Return a finite, non-negative integer suitable for the Admin DTO."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    normalized = int(value)
    return min(normalized, upper_bound) if upper_bound is not None else normalized


class _SearchTestRequest:
    """Adapt an Admin request to the public Codex Search handler contract."""

    def __init__(self, request: Any, body: dict[str, Any]) -> None:
        self.app = request.app
        self.headers = {
            "user-agent": "codex-rosetta-admin-search-test",
            "x-request-id": f"admin-search-test-{secrets.token_hex(12)}",
        }
        self._body = body

    def json(self) -> dict[str, Any]:
        """Return the fixed SearchRequest body."""
        return self._body


def _select_search_test_model(config: GatewayConfig) -> str | None:
    """Select a deterministic route that exercises the configured search path."""
    configured_provider = (
        config.web_search["provider"] == CONFIGURED_RESPONSES_WEB_SEARCH_PROVIDER
    )
    for model in sorted(config.models):
        route, _provider_info = config.resolve("openai_responses", model)
        state = route_tool_state(route, "namespace.web.run", "modified")
        if (configured_provider and state != "disabled") or state == "modified":
            return model
    return None


async def test_network_search(request: Any) -> Response:
    """Run the fixed diagnostic through the public ``alpha/search`` handler."""
    config = getattr(request.app, "gateway_config", None)
    if not isinstance(config, GatewayConfig):
        return JSONResponse(
            {"error": "Gateway configuration is unavailable"}, status_code=503
        )
    model = _select_search_test_model(config)
    if model is None:
        return JSONResponse(
            {"error": "No configured model has an enabled web.run search route"},
            status_code=409,
        )
    body = {
        "id": f"admin-search-test-{secrets.token_hex(12)}",
        "model": model,
        "commands": {"search_query": [{"q": SEARCH_TEST_QUERY}]},
        "settings": {
            "allowed_callers": ["direct"],
            "external_web_access": True,
        },
    }
    principal_token = api_key_principal_var.set(INTERNAL_ADMIN_PRINCIPAL)
    try:
        return await handle_codex_auxiliary(
            _SearchTestRequest(request, body), config, "alpha/search"
        )
    finally:
        api_key_principal_var.reset(principal_token)


async def get_network_search_usage(request: Any) -> Response:
    """Return the safe account-plan quota subset for configured Tavily rows."""
    config = getattr(request.app, "gateway_config", None)
    state = getattr(request.app, "tavily_usage_state", None)
    if not isinstance(config, GatewayConfig) or not isinstance(state, TavilyUsageState):
        return JSONResponse(
            {"error": "Gateway search usage state is unavailable"}, status_code=503
        )
    coordinator = getattr(request.app, "search_provider_coordinator", None)
    semaphore = asyncio.Semaphore(TAVILY_USAGE_MAX_CONCURRENCY)

    async def load_entry(row: dict[str, str]) -> dict[str, Any]:
        async with semaphore:
            try:
                usage = await asyncio.wait_for(
                    state.get(row["tavily_api_key"]),
                    timeout=TAVILY_USAGE_ROW_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                usage = TavilyUsage(status="unavailable")
        if usage.proves_search_quota_recovery and isinstance(
            coordinator, SearchProviderChainCoordinator
        ):
            candidate = next(
                (
                    item
                    for item in getattr(config, "web_search_candidates", ())
                    if isinstance(item, TavilySearchProviderCandidate)
                    and item.row_id == row["id"]
                ),
                None,
            )
            if candidate is not None:
                coordinator.clear_cooldown_from_health_evidence(
                    candidate,
                    evidence_started_at=usage.sample_started_at,
                    reason=SearchProviderAttemptCategory.QUOTA_EXHAUSTED,
                )
        safe_limit = _safe_usage_value(usage.limit)
        safe_used = _safe_usage_value(usage.used, upper_bound=safe_limit)
        if usage.status != "ok" or safe_limit is None or safe_used is None:
            status, safe_used, safe_limit, reset_date = "unavailable", None, None, None
        else:
            status, reset_date = "ok", usage.reset_date
        return {
            "id": row["id"],
            "status": status,
            "used": safe_used,
            "limit": safe_limit,
            "reset_date": reset_date,
        }

    tavily_rows = [
        row for row in config.web_search["providers"] if row["provider"] == "tavily"
    ]
    entries = await asyncio.gather(*(load_entry(row) for row in tavily_rows))
    return JSONResponse({"entries": entries})
