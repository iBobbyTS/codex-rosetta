"""Admin-only diagnostics for the Codex Search endpoint."""

from __future__ import annotations

import secrets
from typing import Any

from codex_rosetta._vendor.httpserver import JSONResponse, Response

from ...auth import INTERNAL_ADMIN_PRINCIPAL, api_key_principal_var
from ...codex_auxiliary import handle_codex_auxiliary
from ...config import CONFIGURED_RESPONSES_WEB_SEARCH_PROVIDER, GatewayConfig
from ...tool_profiles import route_tool_state

SEARCH_TEST_QUERY = "latest python release version"


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
