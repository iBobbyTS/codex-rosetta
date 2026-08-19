"""Account-aware Sub2API requests with transparent refresh and URL rotation."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import weakref
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from codex_rosetta._vendor.httpclient import AsyncClient

from .._ordered_failover import OrderedFailoverCoordinator
from ..transport.http.transport import request_bounded_response
from .account_store import AccountStore

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
_CDN_MARKERS = ("网站请求超时", "回源请求被中断", ">502<")


class Sub2APIRefreshError(RuntimeError):
    """Raised when a stored refresh token cannot produce new credentials."""


class _Sub2APIURLFailure(RuntimeError):
    def __init__(self, response: Any):
        super().__init__("Sub2API URL failed during token refresh")
        self.response = response


class Sub2APIAccountClient:
    """Send one Sub2API request against a caller-selected URL."""

    _lock_guard = threading.Lock()
    _refresh_locks: weakref.WeakKeyDictionary[AccountStore, dict[str, asyncio.Lock]] = (
        weakref.WeakKeyDictionary()
    )

    def __init__(self, store: AccountStore, account_id: str, *, timeout: float = 30.0):
        self.store = store
        self.account_id = account_id
        self.timeout = timeout
        with self._lock_guard:
            account_locks = self._refresh_locks.setdefault(store, {})
            self._refresh_lock = account_locks.setdefault(account_id, asyncio.Lock())

    async def request(
        self,
        base_url: str,
        endpoint: str,
        *,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        user_agent: str | None = None,
        **kwargs: Any,
    ) -> Any:
        account = self.store.get_private(self.account_id)
        if account is None or account["provider"] != "sub2api":
            raise ValueError("Sub2API account not found")
        credentials = dict(account["credentials"])
        if _expires_at_is_past(credentials.get("expires_at")):
            credentials = await self._refresh(base_url, credentials, user_agent)
        response = await self._send(
            base_url, endpoint, method, credentials, headers, user_agent, kwargs
        )
        if response.status_code == 401:
            credentials = await self._refresh(base_url, credentials, user_agent)
            response = await self._send(
                base_url, endpoint, method, credentials, headers, user_agent, kwargs
            )
        return response

    async def _send(
        self,
        base_url: str,
        endpoint: str,
        method: str,
        credentials: dict[str, Any],
        headers: Mapping[str, str] | None,
        user_agent: str | None,
        kwargs: dict[str, Any],
    ) -> Any:
        request_headers = {
            str(key): str(value) for key, value in (headers or {}).items()
        }
        for key in tuple(request_headers):
            if key.lower() in {"authorization", "user-agent"}:
                del request_headers[key]
        request_headers["Authorization"] = f"Bearer {credentials['access_token']}"
        request_headers["User-Agent"] = user_agent or DEFAULT_USER_AGENT
        async with AsyncClient(timeout=self.timeout) as client:
            return await request_bounded_response(
                client,
                method,
                f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}",
                headers=request_headers,
                **kwargs,
            )

    async def _refresh(
        self,
        base_url: str,
        credentials: dict[str, Any],
        user_agent: str | None,
    ) -> dict[str, Any]:
        async with self._refresh_lock:
            latest = self.store.get_private(self.account_id)
            if latest is not None:
                latest_credentials = latest["credentials"]
                if latest_credentials.get("access_token") != credentials.get(
                    "access_token"
                ) and not _expires_at_is_past(latest_credentials.get("expires_at")):
                    return dict(latest_credentials)
            async with AsyncClient(timeout=self.timeout) as client:
                response = await request_bounded_response(
                    client,
                    "POST",
                    f"{base_url.rstrip('/')}/api/v1/auth/refresh",
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": user_agent or DEFAULT_USER_AGENT,
                    },
                    json={"refresh_token": credentials.get("refresh_token", "")},
                )
        if _is_url_failure(response):
            raise _Sub2APIURLFailure(response)
        if response.status_code != 200:
            raise Sub2APIRefreshError(
                f"Sub2API token refresh failed ({response.status_code})"
            )
        try:
            payload = response.json()
            if payload.get("code") not in (0, "0", None):
                raise ValueError("refresh response code is not successful")
            data = payload["data"]
            access_token = data["access_token"]
            refresh_token = data["refresh_token"]
            expires_in = int(data["expires_in"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise Sub2APIRefreshError(
                "Sub2API token refresh response is invalid"
            ) from exc
        updated = {
            **credentials,
            "access_token": str(access_token),
            "refresh_token": str(refresh_token),
            "expires_at": str(int(time.time() * 1000) + expires_in * 1000),
        }
        if not self.store.update_credentials(self.account_id, updated):
            raise Sub2APIRefreshError(
                "Sub2API account disappeared during token refresh"
            )
        return updated


class Sub2APIProviderClient:
    """Shared provider-level client that owns 502/CDN URL rotation."""

    def __init__(
        self,
        store: AccountStore,
        account_id: str,
        base_urls: Sequence[str],
        *,
        persist_current_url: Callable[[str, str], Awaitable[None]],
        provider_id: str = "sub2api",
        current_base_url: str | None = None,
        timeout: float = 30.0,
    ):
        urls = tuple(
            url.rstrip("/") for url in base_urls if isinstance(url, str) and url.strip()
        )
        if not urls or len(set(urls)) != len(urls):
            raise ValueError("Sub2API base URLs must be non-empty and unique")
        current = (current_base_url or urls[0]).rstrip("/")
        if current not in urls:
            raise ValueError("current_base_url must be one of base_urls")
        self.account_id = account_id
        self.provider_id = provider_id
        self._persist_current_url = persist_current_url
        self._urls = OrderedFailoverCoordinator(urls, current)
        self._account = Sub2APIAccountClient(store, account_id, timeout=timeout)

    @property
    def current_base_url(self) -> str:
        return self._urls.current

    async def request(self, endpoint: str, **kwargs: Any) -> Any:
        await self._urls.wait()
        while True:
            url = self._urls.current
            observation = self._urls.observe()
            try:
                response = await self._account.request(url, endpoint, **kwargs)
            except _Sub2APIURLFailure as exc:
                response = exc.response
            if not _is_url_failure(response):
                return response
            claimed, _waited = await self._urls.claim_observation_with_waited(
                observation
            )
            if not claimed:
                await self._urls.wait()
                continue
            try:
                self._urls.mark_failed(url)
                next_url = self._urls.next_available_after(url)
                if next_url is None:
                    return response
                await self._persist_current_url(self.provider_id, next_url)
                self._urls.set_current(next_url)
            finally:
                await self._urls.publish()


def _expires_at_is_past(value: Any) -> bool:
    try:
        return int(str(value)) <= int(time.time() * 1000)
    except TypeError, ValueError:
        return False


def _is_url_failure(response: Any) -> bool:
    if response.status_code == 502:
        return True
    if response.status_code == 503:
        return False
    try:
        text = response.content.decode("utf-8", errors="replace")
    except AttributeError:
        return False
    return all(marker in text for marker in _CDN_MARKERS)


__all__ = [
    "DEFAULT_USER_AGENT",
    "Sub2APIAccountClient",
    "Sub2APIProviderClient",
    "Sub2APIRefreshError",
]
