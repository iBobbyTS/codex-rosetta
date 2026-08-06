"""Tavily account-usage caching for the authenticated Admin API."""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .web_search import TavilyCredentialCollisionError, TavilyHTTPClient
from .transport._base import UpstreamSafetyError

TAVILY_USAGE_CACHE_SECONDS = 300.0
TAVILY_USAGE_FETCH_TIMEOUT_SECONDS = 10.0
# One SearchRequest may contain four advanced searches at two credits each.
TAVILY_QUOTA_RECOVERY_MIN_CREDITS = 8
# Four complete generations of the 32-row configured provider chain.
TAVILY_USAGE_STATE_CAPACITY = 128


@dataclass(frozen=True)
class TavilyUsage:
    """Safe subset of Tavily account-plan usage."""

    status: str
    used: int | None = None
    limit: int | None = None
    reset_date: str | None = None
    sample_started_at: float | None = None
    available_credits: int | None = None

    @property
    def proves_search_quota_recovery(self) -> bool:
        """Return whether this fresh sample can fund one maximum-size request."""

        return (
            self.status == "ok"
            and self.sample_started_at is not None
            and self.available_credits is not None
            and self.available_credits >= TAVILY_QUOTA_RECOVERY_MIN_CREDITS
        )


class TavilyUsageState:
    """Cache and coalesce Tavily usage calls by non-reversible key digest."""

    def __init__(
        self,
        *,
        ttl_seconds: float = TAVILY_USAGE_CACHE_SECONDS,
        state_capacity: int = TAVILY_USAGE_STATE_CAPACITY,
        monotonic: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = date.today,
    ) -> None:
        if state_capacity <= 0:
            raise ValueError("state_capacity must be positive")
        self._ttl_seconds = ttl_seconds
        self._state_capacity = state_capacity
        self._monotonic = monotonic
        self._today = today
        self._cache: OrderedDict[str, tuple[float, TavilyUsage]] = OrderedDict()
        self._inflight: dict[str, asyncio.Task[TavilyUsage]] = {}
        self._lock = asyncio.Lock()
        self._capacity_changed = asyncio.Event()

    async def get(
        self,
        api_key: str,
        *,
        fetcher: Callable[[], Awaitable[dict[str, Any]]] | None = None,
    ) -> TavilyUsage:
        """Return cached account-plan usage, coalescing concurrent cache misses."""
        digest = hashlib.sha256(api_key.encode()).hexdigest()
        while True:
            capacity_changed: asyncio.Event | None = None
            async with self._lock:
                self._sweep_expired_cache_locked()
                cached = self._cache.get(digest)
                if cached is not None:
                    self._cache.move_to_end(digest)
                    return cached[1]
                task = self._inflight.get(digest)
                if task is None:
                    self._make_cache_room_locked(digest)
                    if len(self._state_keys_locked()) < self._state_capacity:
                        task = asyncio.create_task(
                            self._fetch_and_store(digest, api_key, fetcher=fetcher),
                            name="tavily-usage",
                        )
                        self._inflight[digest] = task
                    else:
                        capacity_changed = self._capacity_changed
            if capacity_changed is not None:
                await capacity_changed.wait()
                continue
            assert task is not None
            return await asyncio.shield(task)

    async def _fetch_and_store(
        self,
        digest: str,
        api_key: str,
        *,
        fetcher: Callable[[], Awaitable[dict[str, Any]]] | None,
    ) -> TavilyUsage:
        """Own one fetch and publish its cache result before releasing waiters."""
        task = asyncio.current_task()
        try:
            result = await self._fetch(api_key, fetcher=fetcher)
        except BaseException:
            async with self._lock:
                if self._inflight.get(digest) is task:
                    self._inflight.pop(digest, None)
                    self._signal_capacity_change_locked()
            raise
        async with self._lock:
            self._cache[digest] = (self._monotonic() + self._ttl_seconds, result)
            self._cache.move_to_end(digest)
            if self._inflight.get(digest) is task:
                self._inflight.pop(digest, None)
            self._trim_cache_locked(retained_digest=digest)
            self._signal_capacity_change_locked()
        return result

    def _sweep_expired_cache_locked(self) -> None:
        """Remove every expired credential digest during ordinary access."""
        now = self._monotonic()
        expired = [
            digest
            for digest, (deadline, _usage) in self._cache.items()
            if deadline <= now
        ]
        for digest in expired:
            self._cache.pop(digest, None)
        if expired:
            self._signal_capacity_change_locked()

    def _signal_capacity_change_locked(self) -> None:
        """Wake capacity admission after protected state becomes reusable."""
        self._capacity_changed.set()
        self._capacity_changed = asyncio.Event()

    def _make_cache_room_locked(self, retained_digest: str) -> None:
        """Evict only completed cache entries until the shared budget has room."""
        while len(self._state_keys_locked()) >= self._state_capacity and self._cache:
            oldest = next(iter(self._cache))
            if oldest == retained_digest and len(self._cache) == 1:
                break
            self._cache.pop(oldest, None)

    def _trim_cache_locked(self, *, retained_digest: str) -> None:
        """Trim completed entries only when publication exceeds the budget."""
        while len(self._state_keys_locked()) > self._state_capacity and self._cache:
            oldest = next(iter(self._cache))
            if oldest == retained_digest and len(self._cache) == 1:
                break
            self._cache.pop(oldest, None)

    def _state_keys_locked(self) -> set[str]:
        return set(self._cache) | set(self._inflight)

    async def _fetch(
        self,
        api_key: str,
        *,
        fetcher: Callable[[], Awaitable[dict[str, Any]]] | None,
    ) -> TavilyUsage:
        sample_started_at = self._monotonic()
        try:
            payload = (
                await fetcher()
                if fetcher is not None
                else await TavilyHTTPClient(
                    api_key, timeout=TAVILY_USAGE_FETCH_TIMEOUT_SECONDS
                ).usage()
            )
            account = payload.get("account")
            if not isinstance(account, dict):
                return TavilyUsage(
                    status="unavailable", sample_started_at=sample_started_at
                )
            used = account.get("plan_usage")
            limit = account.get("plan_limit")
            used_value = _safe_nonnegative_integer(used)
            limit_value = _safe_nonnegative_integer(limit)
            if used_value is None or limit_value is None:
                return TavilyUsage(
                    status="unavailable", sample_started_at=sample_started_at
                )
            # A provider can briefly report usage above its nominal plan limit;
            # never expose an invalid progress value in the Admin DTO.
            used_value = min(used_value, limit_value)
            available_credits = _available_credits(
                payload, used=used_value, limit=limit_value
            )
            return TavilyUsage(
                status="ok",
                used=used_value,
                limit=limit_value,
                reset_date=_next_month_start(self._today()).isoformat(),
                sample_started_at=sample_started_at,
                available_credits=available_credits,
            )
        except (TavilyCredentialCollisionError, UpstreamSafetyError):  # fmt: skip
            # Credential-collision and other local safety decisions must retain
            # their established fail-closed boundary; do not turn them into a
            # misleading ``unavailable`` usage sample.
            raise
        except Exception:
            return TavilyUsage(
                status="unavailable", sample_started_at=sample_started_at
            )


def _available_credits(payload: dict[str, Any], *, used: int, limit: int) -> int | None:
    """Compute a conservative usable-credit bound from optional Tavily limits."""

    account = payload["account"]
    account_available = max(0, limit - used)
    paygo, paygo_valid = _optional_usage_pair(account, "paygo_usage", "paygo_limit")
    if not paygo_valid:
        return None
    if paygo is not None:
        account_available += max(0, paygo[1] - paygo[0])

    key = payload.get("key")
    if key is None:
        return account_available
    if not isinstance(key, dict):
        return None
    key_pair, key_pair_valid = _optional_usage_pair(key, "usage", "limit")
    if not key_pair_valid:
        return None
    if key_pair is None:
        return account_available
    return min(account_available, max(0, key_pair[1] - key_pair[0]))


def _optional_usage_pair(
    value: dict[str, Any], used_name: str, limit_name: str
) -> tuple[tuple[int, int] | None, bool]:
    """Parse an optional usage pair and return its independent validity flag."""

    pair = (value.get(used_name), value.get(limit_name))
    if pair == (None, None):
        return None, True
    normalized = tuple(_safe_nonnegative_integer(item) for item in pair)
    if any(item is None for item in normalized):
        return None, False
    pair_used, pair_limit = normalized
    assert isinstance(pair_used, int) and isinstance(pair_limit, int)
    return (pair_used, pair_limit), True


def _safe_nonnegative_integer(value: Any) -> int | None:
    """Normalize finite non-negative numeric usage values for safe DTOs."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return int(value)


def _next_month_start(value: date) -> date:
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)
