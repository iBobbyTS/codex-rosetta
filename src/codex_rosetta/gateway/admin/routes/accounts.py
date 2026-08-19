"""Admin account listing and ChatGPT OAuth entry point."""

from __future__ import annotations

import asyncio
import math
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
from ..sub2api_client import Sub2APIProviderClient
from ...transport.provider_info import ProviderInfo
from ._shared import _parse_json_object


_SUB2API_KEYS_ENDPOINT = (
    "/api/v1/keys?page=1&page_size=100&sort_by=created_at&sort_order=desc"
)


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


def _project_sub2api_key_items(payload: Any) -> list[dict[str, Any]]:
    """Return the minimal Provider-editor projection from one keys response."""
    if not isinstance(payload, dict):
        raise ValueError("Sub2API keys response is invalid")
    success_code = payload.get("code")
    if (
        isinstance(success_code, bool)
        or not isinstance(success_code, int)
        or success_code != 0
    ):
        raise ValueError("Sub2API keys response is invalid")
    data = payload.get("data")
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("Sub2API keys response is invalid")

    projected: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Sub2API keys response is invalid")
        item_id = item.get("id")
        name = item.get("name")
        key = item.get("key")
        group_id = item.get("group_id")
        routes = item.get("group_routes")
        if (
            (isinstance(item_id, bool) or not isinstance(item_id, int | str))
            or (isinstance(item_id, str) and not item_id.strip())
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(key, str)
            or not key
            or (isinstance(group_id, bool) or not isinstance(group_id, int | str))
            or (isinstance(group_id, str) and not group_id.strip())
            or not isinstance(routes, list)
        ):
            raise ValueError("Sub2API keys response is invalid")

        rate_multiplier: int | float | None = None
        for route in routes:
            if not isinstance(route, dict) or not isinstance(
                route.get("enabled"), bool
            ):
                raise ValueError("Sub2API keys response is invalid")
            group = route.get("group")
            if not isinstance(group, dict) or (
                isinstance(group.get("id"), bool)
                or not isinstance(group.get("id"), int | str)
            ):
                raise ValueError("Sub2API keys response is invalid")
            if route["enabled"] is not True or group["id"] != group_id:
                continue
            multiplier = group.get("rate_multiplier")
            if (
                isinstance(multiplier, bool)
                or not isinstance(multiplier, int | float)
                or not math.isfinite(multiplier)
            ):
                raise ValueError("Sub2API keys response is invalid")
            rate_multiplier = multiplier
            break
        projected.append(
            {
                "id": item_id,
                "name": name,
                "key": key,
                "rate_multiplier": rate_multiplier,
                # Sub2API does not expose the editor's available metric yet.
                # Keep the response shape explicit without projecting upstream
                # fields that are not part of the Admin contract.
                "current_concurrency": None,
            }
        )
    return projected


def _project_new_api_pricing(payload: Any) -> dict[str, int | float]:
    """Validate and preserve the ordered New API ``group_ratio`` mapping."""
    if not isinstance(payload, dict):
        raise ValueError("New API pricing response is invalid")
    ratios = payload.get("group_ratio")
    if not isinstance(ratios, dict) or not ratios:
        raise ValueError("New API pricing response is invalid")
    projected: dict[str, int | float] = {}
    for group, ratio in ratios.items():
        if (
            not isinstance(group, str)
            or not group.strip()
            or isinstance(ratio, bool)
            or not isinstance(ratio, int | float)
            or not math.isfinite(ratio)
        ):
            raise ValueError("New API pricing response is invalid")
        projected[group] = ratio
    return projected


def _pricing_provider_info(base_url: str, bearer_key: str) -> ProviderInfo:
    """Build a transport descriptor for one draft New API pricing request."""
    sentinel = "__codex_rosetta_no_bearer__"
    has_bearer = bool(bearer_key)

    def auth_header(token: str) -> dict[str, str]:
        if not has_bearer:
            return {}
        return {"Authorization": f"Bearer {token}"}

    return ProviderInfo(
        name="new_api_pricing",
        api_key=bearer_key or sentinel,
        base_url=base_url,
        auth_header_fn=auth_header,
        url_template="{base_url}/",
        auto_rotate_credentials=False,
    )


async def get_new_api_pricing(request: Any, **kwargs: Any) -> Response:
    """Fetch ordered pricing groups from a draft New API base URL."""
    body = _parse_json_object(request)
    if isinstance(body, Response):
        return body
    base_url = body.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        return JSONResponse(
            {"error": "'base_url' must be a non-empty string"}, status_code=400
        )
    base_url = base_url.strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        return JSONResponse(
            {"error": "'base_url' must be an http(s) URL"}, status_code=400
        )
    bearer_key = body.get("bearer_key", body.get("api_key", ""))
    if not isinstance(bearer_key, str):
        return JSONResponse({"error": "'bearer_key' must be a string"}, status_code=400)

    transport = getattr(request.app, "transport", None)
    if transport is None:
        return JSONResponse(
            {"error": "Pricing transport is unavailable"}, status_code=502
        )
    try:
        response = await transport.send_passthrough(
            _pricing_provider_info(base_url, bearer_key.strip()),
            f"{base_url}/api/pricing",
            {},
            method="GET",
        )
    except Exception:
        return JSONResponse(
            {"error": "Unable to fetch New API pricing"}, status_code=502
        )
    if not 200 <= response.status_code < 300:
        return JSONResponse(
            {"error": f"New API pricing request failed (HTTP {response.status_code})"},
            status_code=502,
        )
    try:
        group_ratio = _project_new_api_pricing(response.body)
    except OverflowError, TypeError, ValueError:
        return JSONResponse(
            {"error": "New API pricing response is invalid"}, status_code=502
        )
    return JSONResponse({"group_ratio": group_ratio})


async def get_sub2api_keys(request: Any, **kwargs: Any) -> Response:
    """Fetch one bound account's keys through an existing runtime Provider."""
    body = _parse_json_object(request)
    if isinstance(body, Response):
        return body
    account_id = body.get("account_id")
    if not isinstance(account_id, str) or not account_id.strip():
        return JSONResponse(
            {"error": "'account_id' must be a non-empty string"}, status_code=400
        )
    account_id = account_id.strip()

    provider_name = request.path_params["name"]
    runtime_provider = request.app.gateway_config.providers.get(provider_name)
    if runtime_provider is None:
        return JSONResponse({"error": "Provider not found"}, status_code=404)

    store = _store(request)
    account = store.get_private(account_id)
    if account is None:
        return JSONResponse({"error": "Sub2API account not found"}, status_code=404)
    if account["provider"] != "sub2api":
        return JSONResponse(
            {"error": "Account is not a Sub2API account"}, status_code=400
        )

    client = Sub2APIProviderClient(
        store,
        account_id,
        runtime_provider.base_urls,
        current_base_url=runtime_provider.base_url,
        provider_id=provider_name,
        persist_current_url=lambda _provider_id, url: runtime_provider.select_base_url(
            url
        ),
    )
    try:
        response = await client.request(
            _SUB2API_KEYS_ENDPOINT,
            user_agent=request.headers.get("user-agent"),
        )
        if response.status_code != 200:
            return JSONResponse(
                {"error": "Unable to fetch Sub2API keys"}, status_code=502
            )
        items = _project_sub2api_key_items(response.json())
    except Exception:
        return JSONResponse({"error": "Unable to fetch Sub2API keys"}, status_code=502)
    return JSONResponse({"items": items})


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
    "get_new_api_pricing",
    "get_sub2api_keys",
    "refresh_account",
    "start_chatgpt",
]
