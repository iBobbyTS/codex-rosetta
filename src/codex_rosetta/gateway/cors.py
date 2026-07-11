"""Shared browser CORS policy for Gateway and Admin responses."""

from __future__ import annotations

from typing import Any


def is_admin_path(path: str) -> bool:
    """Return whether *path* belongs to the Admin HTML/API surface."""
    return path == "/admin" or path.startswith("/admin/")


def is_admin_origin_allowed(request: Any) -> bool:
    """Return whether the request Origin is in the live Admin allowlist."""
    origin = request.headers.get("origin")
    origins = tuple(getattr(request.app, "admin_cors_origins", ()))
    return bool(origin and origin in origins)


def apply_cors_headers(request: Any, response: Any) -> Any:
    """Apply the route-specific live CORS policy to *response*."""
    if is_admin_path(request.path):
        if not is_admin_origin_allowed(request):
            return response
        response.headers["Access-Control-Allow-Origin"] = request.headers["origin"]
        response.headers["Vary"] = "Origin"
    else:
        response.headers["Access-Control-Allow-Origin"] = "*"

    response.headers["Access-Control-Allow-Methods"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response
