"""Admin account listing and ChatGPT OAuth entry point."""

from __future__ import annotations

from typing import Any

from codex_rosetta._vendor.httpserver import JSONResponse, Response

from ..account_store import AccountStore, get_account_store
from ..chatgpt_oauth import chatgpt_callback, start_chatgpt_login
from ..sub2api import parse_sub2api_credentials
from ._shared import _parse_json_object


def _store(request: Any) -> AccountStore:
    return get_account_store(request.app)


async def get_accounts(request: Any) -> Response:
    """List public account projections; token material is never serialized."""
    return JSONResponse({"accounts": _store(request).list_public()})


async def start_chatgpt(request: Any) -> Response:
    """Start one authenticated ChatGPT login transaction."""
    return await start_chatgpt_login(request)


async def add_sub2api(request: Any) -> Response:
    """Validate and store one user-supplied Sub2API credential export."""
    body = _parse_json_object(request)
    if isinstance(body, Response):
        return body
    try:
        identity, metadata, credentials = parse_sub2api_credentials(
            body.get("auth"), body.get("base_url")
        )
        return JSONResponse(
            {
                "account": _store(request).upsert(
                    provider="sub2api",
                    identity=identity,
                    metadata=metadata,
                    credentials=credentials,
                )
            }
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def delete_account(request: Any, account_id: str) -> Response:
    """Delete one local account and never call the upstream provider."""
    if not _store(request).delete(account_id):
        return JSONResponse({"error": "账号不存在或已删除"}, status_code=404)
    return JSONResponse({"ok": True})


__all__ = [
    "add_sub2api",
    "chatgpt_callback",
    "delete_account",
    "get_accounts",
    "start_chatgpt",
]
