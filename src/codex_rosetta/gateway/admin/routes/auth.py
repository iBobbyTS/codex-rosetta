"""Admin authentication route handlers."""

from __future__ import annotations

import hmac
from typing import Any

from codex_rosetta._vendor.httpserver import JSONResponse, Response

from ..static import load_admin_html
from ._shared import _parse_json_object

# Cached HTML — loaded once on first request.
_admin_html: str | None = None


async def serve_admin_html(request: Any) -> Response:
    """Serve the admin panel SPA."""
    global _admin_html
    if _admin_html is None:
        _admin_html = load_admin_html()
    return Response(
        body=_admin_html,
        status_code=200,
        content_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Content-Security-Policy": "frame-ancestors 'none'",
            "X-Frame-Options": "DENY",
        },
    )


def _get_client_ip(request: Any) -> str:
    """Return the direct peer address used by the login rate limiter.

    Forwarded headers are intentionally ignored because the gateway has no
    trusted-proxy configuration.  Accepting them from arbitrary clients would
    let an attacker rotate a header value to bypass lockout.
    """
    addr = getattr(request, "client_addr", None)
    if addr:
        return str(addr[0])
    return "unknown"


async def admin_login(request: Any) -> Response:
    """Validate admin password and return a session token."""
    auth_state = request.app.auth_state
    limiter = request.app.admin_runtime_state.login_limiter
    if not auth_state.admin_password:
        return JSONResponse({"error": "Admin password not configured"}, status_code=400)

    ip = _get_client_ip(request)
    blocked, retry_after = limiter.check(ip)
    if blocked:
        return JSONResponse(
            {
                "error": f"Too many failed attempts. Try again in {int(retry_after) + 1}s."
            },
            status_code=429,
        )

    body = _parse_json_object(request)
    if isinstance(body, Response):
        return body

    password = body.get("password", "")
    if not isinstance(password, str) or not hmac.compare_digest(
        password, auth_state.admin_password
    ):
        limiter.record_failure(ip)
        blocked, retry_after = limiter.check(ip)
        resp: dict[str, Any] = {"error": "Invalid password"}
        if blocked:
            resp["error"] = (
                f"Too many failed attempts. Locked for {int(retry_after) + 1}s."
            )
        return JSONResponse(resp, status_code=401)

    limiter.clear(ip)
    return JSONResponse({"ok": True, "token": auth_state.admin_token})


async def admin_check(request: Any) -> Response:
    """Check whether admin auth is required (before loading config)."""
    auth_state = request.app.auth_state
    requires_auth = bool(auth_state.admin_password)
    return JSONResponse({"requires_auth": requires_auth})
