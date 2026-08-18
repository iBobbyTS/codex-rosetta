"""Admin account listing and ChatGPT OAuth entry point."""

from __future__ import annotations

import asyncio
from typing import Any

from codex_rosetta._vendor.httpserver import JSONResponse, Response

from ..account_store import AccountStore, get_account_store
from ..chatgpt_oauth import (
    _metadata_from_claims,
    _metadata_request,
    chatgpt_callback,
    start_chatgpt_login,
)
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


async def refresh_account(request: Any, account_id: str) -> Response:
    """Refresh ChatGPT workspace/subscription metadata from the upstream API."""
    account = _store(request).get_private(account_id)
    if account is None:
        return JSONResponse({"error": "账号不存在或已删除"}, status_code=404)
    if account["provider"] != "chatgpt":
        return JSONResponse({"error": "该账号类型不支持刷新账号信息"}, status_code=400)
    credentials = account["credentials"]
    access_token = credentials.get("access_token", "")
    if not isinstance(access_token, str) or not access_token:
        return JSONResponse({"error": "账号缺少 access token"}, status_code=400)
    claims = _metadata_from_claims(access_token, credentials.get("id_token", ""))
    fetched = await asyncio.to_thread(
        _metadata_request,
        access_token,
        claims.get("account_id", ""),
    )
    if not fetched:
        return JSONResponse(
            {"error": "无法从 ChatGPT 获取账号信息，请稍后重试"}, status_code=502
        )
    metadata = dict(account["metadata"])
    for key in ("name", "email"):
        value = claims.get(key) or fetched.get(key)
        if isinstance(value, str) and value.strip():
            metadata[key] = value.strip()
    for key in ("workspace", "subscription_type"):
        value = fetched.get(key) or claims.get(key)
        if isinstance(value, str) and value.strip():
            metadata[key] = value.strip()
    _store(request).update_metadata(account_id, metadata)
    return JSONResponse(
        {"account": {"id": account_id, "provider": "chatgpt", **metadata}}
    )


__all__ = [
    "add_sub2api",
    "chatgpt_callback",
    "delete_account",
    "get_accounts",
    "refresh_account",
    "start_chatgpt",
]
