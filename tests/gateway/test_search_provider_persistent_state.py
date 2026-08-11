from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from codex_rosetta.gateway.search_provider_candidates import (
    TavilySearchProviderCandidate,
)
from codex_rosetta.gateway.search_provider_chain import (
    SearchProviderAttemptCategory,
    SearchProviderAttemptError,
    SearchProviderChainCoordinator,
)
from codex_rosetta.gateway.search_usage import TavilyUsage
from codex_rosetta.observability.persistence import PersistenceManager


def candidate(row_id: str, identity: str) -> TavilySearchProviderCandidate:
    return TavilySearchProviderCandidate(
        row_id=row_id,
        api_key=f"key-{row_id}",
        identity=identity,
    )


class UsageState:
    def __init__(self, *samples: TavilyUsage) -> None:
        self.samples = list(samples)
        self.calls: list[tuple[str, bool]] = []

    async def get(
        self, api_key: str, *, refresh: bool = False, **_kwargs: Any
    ) -> TavilyUsage:
        self.calls.append((api_key, refresh))
        return self.samples.pop(0)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_current_provider_survives_restart_and_identity_change_falls_back(
    tmp_path: Path,
) -> None:
    first = candidate("first", "first-identity")
    selected = candidate("selected", "selected-identity")
    persistence = PersistenceManager(str(tmp_path))
    coordinator = SearchProviderChainCoordinator(persistence=persistence)
    coordinator.select_current(selected)
    persistence.close()

    persistence = PersistenceManager(str(tmp_path))
    coordinator = SearchProviderChainCoordinator(persistence=persistence)
    calls: list[str] = []

    async def succeed(item: TavilySearchProviderCandidate) -> str:
        calls.append(item.row_id)
        return item.row_id

    assert run(coordinator.run((first, selected), succeed)) == "selected"
    assert calls == ["selected"]

    changed = candidate("selected", "changed-identity")
    calls.clear()
    assert run(coordinator.run((first, changed), succeed)) == "first"
    assert calls == ["first"]
    persistence.close()


def test_no_persistence_keeps_current_provider_process_local() -> None:
    first = candidate("first", "first-identity")
    second = candidate("second", "second-identity")
    coordinator = SearchProviderChainCoordinator()

    async def select_second(item: TavilySearchProviderCandidate) -> str:
        if item is first:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.UPSTREAM_FAILURE
            )
        return item.row_id

    assert run(coordinator.run((first, second), select_second)) == "second"

    calls: list[str] = []

    async def succeed(item: TavilySearchProviderCandidate) -> str:
        calls.append(item.row_id)
        return item.row_id

    assert run(coordinator.run((first, second), succeed)) == "second"
    assert calls == ["second"]


@pytest.mark.parametrize("available", [1, None])
def test_nonzero_or_unknown_quota_uses_memory_only_cooldown(
    tmp_path: Path, available: int | None
) -> None:
    item = candidate("tavily", "identity")
    usage = UsageState(
        TavilyUsage(status="ok", available_credits=available)
        if available is not None
        else TavilyUsage(status="unavailable")
    )
    persistence = PersistenceManager(str(tmp_path))
    coordinator = SearchProviderChainCoordinator(
        persistence=persistence,
        tavily_usage_state=usage,
    )

    async def fail(_item: TavilySearchProviderCandidate) -> None:
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)

    with pytest.raises(Exception, match="Search unavailable"):
        run(coordinator.run((item,), fail))
    assert coordinator.is_cooling(item)
    persistence.close()

    persistence = PersistenceManager(str(tmp_path))
    restarted = SearchProviderChainCoordinator(persistence=persistence)
    assert not restarted.is_quota_exhausted(item)
    persistence.close()


def test_zero_quota_persists_and_due_positive_refresh_recovers(tmp_path: Path) -> None:
    wall_time = 1_000.0
    item = candidate("tavily", "identity")
    usage = UsageState(
        TavilyUsage(status="ok", available_credits=0),
        TavilyUsage(status="ok", available_credits=1),
    )
    persistence = PersistenceManager(str(tmp_path))
    coordinator = SearchProviderChainCoordinator(
        persistence=persistence,
        tavily_usage_state=usage,
        wall_clock=lambda: wall_time,
    )

    async def fail(_item: TavilySearchProviderCandidate) -> None:
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)

    with pytest.raises(Exception, match="Search unavailable"):
        run(coordinator.run((item,), fail))
    assert coordinator.is_quota_exhausted(item)
    assert usage.calls == [("key-tavily", True)]
    persistence.close()

    persistence = PersistenceManager(str(tmp_path))
    restarted = SearchProviderChainCoordinator(
        persistence=persistence,
        tavily_usage_state=usage,
        wall_clock=lambda: wall_time,
    )
    calls = 0

    async def succeed(_item: TavilySearchProviderCandidate) -> str:
        nonlocal calls
        calls += 1
        return "ok"

    with pytest.raises(Exception, match="Search unavailable"):
        run(restarted.run((item,), succeed))
    assert calls == 0
    assert usage.calls == [("key-tavily", True)]

    wall_time += 3600
    assert run(restarted.run((item,), succeed)) == "ok"
    assert calls == 1
    assert usage.calls == [("key-tavily", True), ("key-tavily", True)]
    assert not restarted.is_quota_exhausted(item)
    persistence.close()


def test_admin_usage_zero_applies_same_persistent_exclusion(tmp_path: Path) -> None:
    item = candidate("tavily", "identity")
    persistence = PersistenceManager(str(tmp_path))
    coordinator = SearchProviderChainCoordinator(
        persistence=persistence,
        wall_clock=lambda: 100.0,
    )

    coordinator.apply_tavily_usage(item, TavilyUsage(status="ok", available_credits=0))

    assert coordinator.is_quota_exhausted(item)
    persistence.close()
