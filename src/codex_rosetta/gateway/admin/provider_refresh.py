"""Background availability refresh for special gateway Providers.

The coordinator deliberately owns only freshness, persistence, and request
coordination.  Candidate selection and multiplier policy consume its snapshots
from their existing owners in a later stage.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

from .account_store import get_account_store
from .routes.accounts import (
    _SUB2API_CAPACITY_ENDPOINT,
    _SUB2API_KEYS_ENDPOINT,
    _project_sub2api_capacity_items,
    _project_sub2api_key_items,
    _request_new_api_nonmodel,
)
from .sub2api_client import Sub2APIProviderClient
from ..config import GatewayConfig, load_config_raw, write_config

_SPECIAL_VARIANTS = frozenset({"new_api", "sub2api"})
_NEW_API_RETRIES = {"1m": 5, "5m": 7, "1h": 10}
_SUB2API_RETRIES = 7
_INTERVAL_SECONDS = {
    "30s": 30,
    "1m": 60,
    "5m": 300,
    "10m": 600,
    "1h": 3600,
}
_ACTIVITY_WINDOW_SECONDS = 600
_RETRY_BASE_SECONDS = 1.0


def _variant(provider: Mapping[str, Any]) -> str | None:
    value = provider.get("openai_variant")
    return value if value in _SPECIAL_VARIANTS else None


def _interval(provider: Mapping[str, Any], variant: str) -> int:
    value = provider.get("new_api_aggregation_bin")
    if variant == "new_api":
        return _INTERVAL_SECONDS.get(value, 3600)
    return _INTERVAL_SECONDS.get(value, 300)


def _bucket_start(now: float, interval: int) -> int:
    timestamp = int(now)
    return timestamp - timestamp % interval


def _next_bucket(now: float, interval: int) -> int:
    return _bucket_start(now, interval) + interval


def _new_api_points(payload: Any, group: str) -> list[tuple[int, float]]:
    """Return validated ``(bucket_ts, success_rate)`` points for one group."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        return []
    for item in groups:
        if not isinstance(item, dict) or item.get("group") != group:
            continue
        series = item.get("series")
        if not isinstance(series, list):
            return []
        points: list[tuple[int, float]] = []
        for point in series:
            if not isinstance(point, dict):
                continue
            ts = point.get("ts")
            value = point.get("success_rate")
            if (
                isinstance(ts, bool)
                or not isinstance(ts, int | float)
                or isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(float(ts))
                or not math.isfinite(float(value))
            ):
                continue
            points.append((int(ts), float(value)))
        return points
    return []


class ProviderRefreshCoordinator:
    """Coordinate persisted special-provider snapshots and request barriers."""

    def __init__(
        self,
        app: Any,
        config: GatewayConfig,
        config_path: str | None,
        *,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.app = app
        self.config = config
        self.config_path = config_path
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep
        self._activity: dict[str, float] = {}
        self._locks = {name: asyncio.Lock() for name in config._all_raw_providers}
        self._inflight: dict[str, asyncio.Task[bool]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._next_due: dict[str, float] = {}
        self._load_snapshots()

    def _load_snapshots(self) -> None:
        for name, provider in self.config._all_raw_providers.items():
            value = provider.get("availability_snapshot")
            if isinstance(value, dict):
                self._snapshots[name] = value

    def sync_config(self, config: GatewayConfig) -> None:
        """Adopt a hot-reloaded config while retaining in-memory snapshots."""
        self.config = config
        for name in config._all_raw_providers:
            self._locks.setdefault(name, asyncio.Lock())

    @property
    def snapshots(self) -> dict[str, dict[str, Any]]:
        """Return a defensive snapshot mapping for selection consumers."""
        return {name: dict(value) for name, value in self._snapshots.items()}

    def snapshot_for(self, provider: str, credential: str) -> dict[str, Any] | None:
        value = self._snapshots.get(provider, {}).get("credentials", {}).get(credential)
        return dict(value) if isinstance(value, dict) else None

    def mark_group_activity(self, group_name: str | None) -> None:
        """Record the latest model-group request for the configured providers."""
        if not group_name:
            return
        now = self._clock()
        self._activity[group_name] = now

    def _provider_active(self, provider_name: str, now: float) -> bool:
        for group_name, last in self._activity.items():
            if now - last > _ACTIVITY_WINDOW_SECONDS:
                continue
            group = self.config.model_group_candidates.get(group_name, ())
            if any(candidate.provider_name == provider_name for candidate in group):
                return True
        return False

    def _provider_due(self, name: str, now: float) -> bool:
        provider = self.config._all_raw_providers.get(name)
        variant = _variant(provider or {})
        if variant is None:
            return False
        interval = _interval(provider or {}, variant)
        if variant == "new_api":
            target = _bucket_start(now, interval)
            credentials = self._snapshots.get(name, {}).get("credentials", {})
            if not credentials:
                return True
            return any(
                int(value.get("timestamp", -1)) < target
                for value in credentials.values()
                if isinstance(value, dict)
            )
        return now >= self._next_due.get(name, 0.0)

    async def start(self) -> None:
        """Start one scheduler task per configured special Provider."""
        for name, provider in self.config._all_raw_providers.items():
            if _variant(provider) is not None and name not in self._tasks:
                self._tasks[name] = asyncio.create_task(self._provider_loop(name))

    async def close(self) -> None:
        """Cancel scheduler and in-flight refresh tasks."""
        tasks = [*self._tasks.values(), *self._inflight.values()]
        self._tasks.clear()
        self._inflight.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def before_request(self, group_name: str | None) -> None:
        """Wait for every active overdue Provider before route resolution."""
        current_config = getattr(self.app, "gateway_config", self.config)
        if current_config is not self.config:
            self.sync_config(current_config)
        self.mark_group_activity(group_name)
        now = self._clock()
        due = [
            name
            for name in self.config._all_raw_providers
            if self._provider_active(name, now) and self._provider_due(name, now)
        ]
        await asyncio.gather(*(self.refresh_provider(name) for name in due))

    async def refresh_provider(self, name: str) -> bool:
        """Run or await one shared Provider refresh."""
        provider = self.config._all_raw_providers.get(name)
        if _variant(provider or {}) is None:
            return False
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            task = self._inflight.get(name)
            if task is None:
                task = asyncio.create_task(self._refresh(name))
                self._inflight[name] = task
        try:
            return await task
        finally:
            async with lock:
                if self._inflight.get(name) is task and task.done():
                    self._inflight.pop(name, None)

    async def _provider_loop(self, name: str) -> None:
        provider = self.config._all_raw_providers[name]
        variant = _variant(provider)
        assert variant is not None
        while True:
            interval = _interval(provider, variant)
            if variant == "new_api":
                delay = max(0.0, _next_bucket(self._clock(), interval) - self._clock())
            else:
                due = self._next_due.setdefault(name, self._monotonic() + interval)
                delay = max(0.0, due - self._monotonic())
            await self._sleep(delay)
            now = self._clock()
            if self._provider_active(name, now) and self._provider_due(name, now):
                await self.refresh_provider(name)
            if variant == "sub2api":
                self._next_due[name] = self._monotonic() + interval

    async def _refresh(self, name: str) -> bool:
        provider = self.config._all_raw_providers[name]
        variant = _variant(provider)
        if variant == "new_api":
            return await self._refresh_new_api(name, provider)
        if variant == "sub2api":
            return await self._refresh_sub2api(name, provider)
        return False

    async def _refresh_new_api(self, name: str, provider: Mapping[str, Any]) -> bool:
        interval = _interval(provider, "new_api")
        bin_name = provider.get("new_api_aggregation_bin")
        retries = _NEW_API_RETRIES.get(bin_name, 10)
        target = _bucket_start(self._clock(), interval)
        transport = getattr(self.app, "transport", None)
        if transport is None:
            return False
        refreshed: dict[str, dict[str, Any]] = {}
        entries = provider.get("api_keys")
        if not isinstance(entries, list):
            return False
        expected_entries = [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("new_api_group"), str)
            and bool(entry.get("new_api_group"))
            and isinstance(entry.get("new_api_model"), str)
            and bool(entry.get("new_api_model"))
        ]
        if not expected_entries:
            return False
        for attempt in range(retries):
            if attempt and self._clock() >= target + interval:
                return False
            refreshed.clear()
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                group = entry.get("new_api_group")
                model = entry.get("new_api_model")
                if (
                    not isinstance(group, str)
                    or not group
                    or not isinstance(model, str)
                    or not model
                ):
                    continue
                try:
                    response = await _request_new_api_nonmodel(
                        transport,
                        str(
                            provider.get("current_base_url")
                            or provider.get("base_urls", [""])[0]
                        ),
                        "/api/perf-metrics?"
                        + urlencode({"model": model, "hours": "24"}),
                        str(entry.get("key", "")),
                    )
                    payload = (
                        response.body if 200 <= response.status_code < 300 else None
                    )
                    points = _new_api_points(payload, group)
                    match = next(
                        ((ts, rate) for ts, rate in points if ts == target), None
                    )
                    if match is not None:
                        refreshed[str(entry.get("uuid", entry.get("id")))] = {
                            "value": match[1],
                            "timestamp": match[0],
                            "kind": "success_rate",
                        }
                except Exception:
                    continue
            if len(refreshed) == len(expected_entries):
                await self._persist(name, refreshed)
                return True
            if self._clock() >= target + interval:
                break
            if attempt + 1 < retries:
                await self._sleep(_RETRY_BASE_SECONDS * (2**attempt))
        return False

    async def _refresh_sub2api(self, name: str, provider: Mapping[str, Any]) -> bool:
        account_id = provider.get("sub2api_account_id")
        base_urls = provider.get("base_urls")
        current = provider.get("current_base_url")
        if (
            not isinstance(account_id, str)
            or not isinstance(base_urls, list)
            or not isinstance(current, str)
        ):
            return False
        store = get_account_store(self.app)
        client = Sub2APIProviderClient(
            store,
            account_id,
            base_urls,
            current_base_url=current,
            provider_id=name,
            persist_current_url=lambda _id, url: self._persist_current_url(name, url),
        )
        interval = _interval(provider, "sub2api")
        round_due = self._next_due.get(name, self._monotonic() + interval)
        entries = provider.get("api_keys")
        if not isinstance(entries, list):
            return False
        for attempt in range(_SUB2API_RETRIES):
            if attempt and self._monotonic() >= round_due + interval:
                return False
            try:
                keys_response = await client.request(_SUB2API_KEYS_ENDPOINT)
                capacity_response = await client.request(_SUB2API_CAPACITY_ENDPOINT)
                if (
                    keys_response.status_code != 200
                    or capacity_response.status_code != 200
                ):
                    raise RuntimeError("Sub2API refresh failed")
                keys = _project_sub2api_key_items(keys_response.json())
                capacity = _project_sub2api_capacity_items(capacity_response.json())
                by_group = {item["group_id"]: item for item in capacity}
                by_name = {str(item["name"]): item for item in keys}
                refreshed: dict[str, dict[str, Any]] = {}
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    item = by_name.get(str(entry.get("id")))
                    if item is None:
                        continue
                    cap = by_group.get(int(item["group_id"]))
                    if cap is None:
                        continue
                    refreshed[str(entry.get("uuid", entry.get("id")))] = {
                        "value": cap["concurrency_max"] - cap["concurrency_used"],
                        "used": cap["concurrency_used"],
                        "maximum": cap["concurrency_max"],
                        "timestamp": int(self._clock()),
                        "kind": "available_concurrency",
                    }
                await self._persist(name, refreshed)
                return True
            except Exception:
                if self._monotonic() >= round_due + interval:
                    break
                if attempt + 1 < _SUB2API_RETRIES:
                    await self._sleep(_RETRY_BASE_SECONDS * (2**attempt))
        return False

    async def _persist_current_url(self, name: str, url: str) -> None:
        if self.config_path is None:
            return
        document = load_config_raw(self.config_path)
        provider = document.get("providers", {}).get(name)
        if isinstance(provider, dict):
            provider["current_base_url"] = url
            write_config(self.config_path, document)

    async def _persist(self, name: str, credentials: dict[str, dict[str, Any]]) -> None:
        previous = self._snapshots.get(name, {}).get("credentials", {})
        merged_credentials = {
            **(previous if isinstance(previous, dict) else {}),
            **credentials,
        }
        snapshot = {
            "updated_at": int(self._clock()),
            "credentials": merged_credentials,
        }
        self._snapshots[name] = snapshot
        if self.config_path is None:
            self.config._all_raw_providers[name]["availability_snapshot"] = snapshot
            return
        document = load_config_raw(self.config_path)
        providers = document.get("providers")
        provider = providers.get(name) if isinstance(providers, dict) else None
        if not isinstance(provider, dict):
            return
        provider["availability_snapshot"] = snapshot
        write_config(self.config_path, document)


__all__ = ["ProviderRefreshCoordinator"]
