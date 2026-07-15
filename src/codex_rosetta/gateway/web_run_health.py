"""Shared bounded health state for the optional ``web-run`` sidecar."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from codex_rosetta._vendor.httpclient import AsyncClient

from .transport.http.transport import request_bounded_response

WEB_RUN_HEALTH_MAX_BYTES = 64 * 1024
WEB_RUN_HEALTH_TIMEOUT_SECONDS = 2.0
WEB_RUN_HEALTH_TTL_SECONDS = 5.0


@dataclass(frozen=True)
class WebRunHealthStatus:
    """Credential-free sidecar readiness exposed to Admin and routing."""

    configured: bool
    service_online: bool
    browser_ready: bool | None

    def as_dict(self) -> dict[str, bool | None]:
        """Return the stable Admin response shape."""
        return {
            "configured": self.configured,
            "service_online": self.service_online,
            "browser_ready": self.browser_ready,
        }


class WebRunHealthState:
    """Cache and coalesce bounded sidecar health probes."""

    def __init__(
        self,
        *,
        ttl_seconds: float = WEB_RUN_HEALTH_TTL_SECONDS,
        timeout_seconds: float = WEB_RUN_HEALTH_TIMEOUT_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._timeout_seconds = timeout_seconds
        self._monotonic = monotonic
        self._cache_key: str | None = None
        self._cached_status: WebRunHealthStatus | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def invalidate(self) -> None:
        """Expire the cached status after a configuration activation."""
        self._cache_key = None
        self._cached_status = None
        self._expires_at = 0.0

    async def status(self, base_url: str | None) -> WebRunHealthStatus:
        """Return cached readiness, refreshing once per TTL when configured."""
        normalized_url = str(base_url or "").strip().rstrip("/")
        if not normalized_url:
            return WebRunHealthStatus(False, False, None)

        cached = self._fresh_status(normalized_url)
        if cached is not None:
            return cached

        async with self._lock:
            cached = self._fresh_status(normalized_url)
            if cached is not None:
                return cached
            status = await self._probe(normalized_url)
            self._cache_key = normalized_url
            self._cached_status = status
            self._expires_at = self._monotonic() + self._ttl_seconds
            return status

    def _fresh_status(self, base_url: str) -> WebRunHealthStatus | None:
        if (
            self._cache_key == base_url
            and self._cached_status is not None
            and self._monotonic() < self._expires_at
        ):
            return self._cached_status
        return None

    async def _probe(self, base_url: str) -> WebRunHealthStatus:
        try:
            async with AsyncClient(timeout=self._timeout_seconds) as client:
                response = await request_bounded_response(
                    client,
                    "GET",
                    f"{base_url}/health",
                    max_success_bytes=WEB_RUN_HEALTH_MAX_BYTES,
                    max_error_bytes=WEB_RUN_HEALTH_MAX_BYTES,
                )
            body: Any = response.json()
        except Exception:
            return WebRunHealthStatus(True, False, None)

        service_online = (
            response.status_code == 200
            and isinstance(body, dict)
            and body.get("status") == "ok"
        )
        browser_ready = body.get("browser_ready") if service_online else None
        if not isinstance(browser_ready, bool):
            browser_ready = None
        return WebRunHealthStatus(True, service_online, browser_ready)


__all__ = [
    "WEB_RUN_HEALTH_MAX_BYTES",
    "WEB_RUN_HEALTH_TIMEOUT_SECONDS",
    "WEB_RUN_HEALTH_TTL_SECONDS",
    "WebRunHealthState",
    "WebRunHealthStatus",
]
