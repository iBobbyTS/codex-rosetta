"""Read-only Admin tools catalog route."""

from __future__ import annotations

from typing import Any

from codex_rosetta._vendor.httpserver import JSONResponse, Response

from ..tool_catalog import load_tool_catalog


async def get_tool_catalog(request: Any) -> Response:
    """Return the immutable tools catalog bundled with the package."""
    return JSONResponse(load_tool_catalog())
