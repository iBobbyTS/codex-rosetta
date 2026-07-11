"""Gateway API key authentication — before-request hook.

Validates incoming requests against the gateway's configured API keys.
The agent-facing API surface uses OpenAI Responses-compatible Bearer
authentication:

- ``Authorization: Bearer <key>``

Supports multiple API keys with stable principal IDs and labels for tracking.
"""

from __future__ import annotations

import contextvars
import hmac
from dataclasses import dataclass
from typing import Any

from codex_rosetta._vendor.httpserver import JSONResponse, Response

from .cors import apply_cors_headers

# Per-request API key label — set by auth hook, read by proxy handler.
api_key_label_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "api_key_label", default=None
)

# Stable authenticated principal for request-scoped state isolation.  The value
# is the configured ``server.api_keys[].id`` and never a label or raw key.
api_key_principal_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "api_key_principal", default=None
)

INTERNAL_ADMIN_PRINCIPAL = "__admin_internal__"

# Paths that never require authentication
_PUBLIC_PATHS = frozenset({"/health"})


@dataclass(frozen=True)
class PreparedAuthConfig:
    """Fully constructed auth state ready for an assignment-only commit."""

    principals: dict[str, str]
    labels: dict[str, str]
    admin_password: str | None
    admin_token: str | None


def _extract_key(request: Any) -> str | None:
    """Extract an OpenAI-compatible Bearer token from the request."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def _error_for_path(path: str, status: int, message: str) -> Response:
    """Return an OpenAI-compatible error response."""
    return JSONResponse(
        {
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "code": "invalid_api_key",
            }
        },
        status_code=status,
    )


def _is_protected_api_path(path: str) -> bool:
    """Return whether gateway API-key auth applies to *path*.

    The entire OpenAI-compatible ``/v1`` namespace fails closed so newly
    registered, unknown, and removed endpoints cannot bypass authentication.
    """
    return path == "/v1" or path.startswith("/v1/")


def check_admin_auth(request: Any, auth_state: AuthState) -> Response | None:
    """Authenticate admin panel requests.

    Returns ``None`` to allow the request, or a 401 response to block it.
    Unauthenticated HTML page requests are allowed through so the JS
    login UI can render.
    """
    path = request.path

    # Login and auth-check endpoints are always accessible
    if path in ("/admin/api/login", "/admin/api/auth-check"):
        return None

    # Browser preflight never carries the actual Admin token. Origin
    # authorization is enforced by the strict CORS preflight route.
    if getattr(request, "method", "") == "OPTIONS" and path.startswith("/admin/api/"):
        return None

    # Check X-Admin-Token header
    admin_token = request.headers.get("x-admin-token", "")
    if (
        admin_token
        and auth_state.admin_token
        and hmac.compare_digest(admin_token, auth_state.admin_token)
    ):
        return None

    # Block unauthenticated API calls
    if path.startswith("/admin/api/"):
        return JSONResponse({"error": "Admin authentication required"}, status_code=401)

    # HTML page requests pass through — JS handles login UI
    return None


class AuthState:
    """Mutable state container for auth hook — allows hot-reload from admin."""

    def __init__(
        self,
        principals: dict[str, str],
        labels: dict[str, str],
        internal_token: str | None,
        admin_password: str | None = None,
    ) -> None:
        self.internal_token = internal_token
        self.principals: dict[str, str] = {}
        self.labels: dict[str, str] = {}
        self.admin_password: str | None = None
        self.admin_token: str | None = None
        self.update_config(principals, labels, admin_password)

    def prepare_update(
        self,
        principals: dict[str, str],
        labels: dict[str, str],
        admin_password: str | None,
    ) -> PreparedAuthConfig:
        """Build replacement credentials without mutating live auth state."""
        admin_token = None
        if admin_password and self.internal_token:
            import hashlib

            admin_token = hmac.new(
                self.internal_token.encode(),
                admin_password.encode(),
                hashlib.sha256,
            ).hexdigest()
        return PreparedAuthConfig(
            principals=dict(principals),
            labels=dict(labels),
            admin_password=admin_password,
            admin_token=admin_token,
        )

    def commit_update(self, prepared: PreparedAuthConfig) -> None:
        """Commit a prepared credential replacement using assignments only."""
        self.principals = prepared.principals
        self.labels = prepared.labels
        self.admin_password = prepared.admin_password
        self.admin_token = prepared.admin_token

    def update_config(
        self,
        principals: dict[str, str],
        labels: dict[str, str],
        admin_password: str | None,
    ) -> None:
        """Replace hot-reloadable credentials and rebuild the Admin token."""
        self.commit_update(self.prepare_update(principals, labels, admin_password))


def create_auth_hook(auth_state: AuthState) -> Any:
    """Return a before-request hook that validates API keys.

    The hook reads from ``auth_state`` which can be mutated by the admin
    panel's hot-reload logic.
    """

    async def auth_hook(request: Any) -> Response | None:
        # Reset request-local identity before every auth decision.
        api_key_label_var.set(None)
        api_key_principal_var.set(None)

        path = request.path

        # Public paths skip auth
        if path in _PUBLIC_PATHS:
            return None

        # Admin panel auth is a separate concern from API key auth
        if path.startswith("/admin"):
            response = check_admin_auth(request, auth_state)
            if response is not None:
                apply_cors_headers(request, response)
            return response

        if not _is_protected_api_path(path):
            return None

        # Browser preflight carries the requested Authorization header name,
        # not the API credential. The wildcard CORS route authorizes the
        # browser origin; the subsequent real request is still authenticated.
        if getattr(request, "method", "") == "OPTIONS":
            return None

        key = _extract_key(request)

        # Check internal token first (admin panel test requests)
        if (
            key
            and auth_state.internal_token
            and hmac.compare_digest(key, auth_state.internal_token)
        ):
            api_key_label_var.set("internal")
            api_key_principal_var.set(INTERNAL_ADMIN_PRINCIPAL)
            return None

        matched_key = next(
            (
                configured_key
                for configured_key in auth_state.principals
                if key is not None and hmac.compare_digest(key, configured_key)
            ),
            None,
        )
        if matched_key is None:
            response = _error_for_path(path, 401, "Invalid or missing API key")
            return apply_cors_headers(request, response)

        # Attach display label and stable principal without exposing the raw key.
        api_key_label_var.set(auth_state.labels.get(matched_key, ""))
        api_key_principal_var.set(auth_state.principals[matched_key])
        return None

    return auth_hook
