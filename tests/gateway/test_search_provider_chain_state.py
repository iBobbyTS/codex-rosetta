from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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


class Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def candidate(row_id: str, identity: str) -> TavilySearchProviderCandidate:
    return TavilySearchProviderCandidate(
        row_id=row_id,
        api_key=f"private-{row_id}",
        identity=identity,
    )


@pytest.mark.parametrize("state_capacity", [0, -1, True, 1.5])
def test_state_capacity_must_be_a_positive_integer(state_capacity: Any) -> None:
    with pytest.raises(ValueError, match="state_capacity must be a positive integer"):
        SearchProviderChainCoordinator(state_capacity=state_capacity)


def test_cooldown_is_exact_to_row_and_identity_and_expires_lazily() -> None:
    clock = Clock()
    coordinator = SearchProviderChainCoordinator(
        cooldown_seconds=60,
        clock=clock,
    )
    failed = candidate("row", "identity-a")
    changed = candidate("row", "identity-b")

    coordinator.mark_failed(
        failed,
        SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR),
    )

    assert (
        coordinator.cooldown_reason(failed) is SearchProviderAttemptCategory.HTTP_ERROR
    )
    assert coordinator.cooldown_reason(changed) is None
    clock.value = 160.0
    assert coordinator.cooldown_reason(failed) is None


def test_capacity_evicts_oldest_cooldown_without_waiters() -> None:
    clock = Clock()
    coordinator = SearchProviderChainCoordinator(
        cooldown_seconds=60,
        state_capacity=2,
        clock=clock,
    )
    first = candidate("first", "identity-first")
    second = candidate("second", "identity-second")
    third = candidate("third", "identity-third")
    failure = SearchProviderAttemptError(SearchProviderAttemptCategory.CONNECTION_ERROR)

    coordinator.mark_failed(first, failure)
    clock.value += 1
    coordinator.mark_failed(second, failure)
    clock.value += 1
    coordinator.mark_failed(third, failure)

    assert coordinator.cooldown_reason(first) is None
    assert (
        coordinator.cooldown_reason(second)
        is SearchProviderAttemptCategory.CONNECTION_ERROR
    )
    assert (
        coordinator.cooldown_reason(third)
        is SearchProviderAttemptCategory.CONNECTION_ERROR
    )


def test_health_evidence_clears_only_matching_fresh_quota_state() -> None:
    clock = Clock()
    coordinator = SearchProviderChainCoordinator(clock=clock)
    row = candidate("row", "identity")
    coordinator.mark_failed(
        row,
        SearchProviderAttemptError(
            SearchProviderAttemptCategory.HTTP_ERROR,
            quota_exhausted=True,
        ),
    )

    assert not coordinator.clear_cooldown_from_health_evidence(
        row,
        reason=SearchProviderAttemptCategory.QUOTA_EXHAUSTED,
        evidence_started_at=100.0,
    )
    clock.value = 101.0
    assert coordinator.clear_cooldown_from_health_evidence(
        row,
        reason=SearchProviderAttemptCategory.QUOTA_EXHAUSTED,
        evidence_started_at=100.5,
    )
    assert coordinator.cooldown_reason(row) is None


def test_ordinary_failure_is_not_cleared_by_quota_health_evidence() -> None:
    clock = Clock()
    coordinator = SearchProviderChainCoordinator(clock=clock)
    row = candidate("row", "identity")
    coordinator.mark_failed(
        row,
        SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR),
    )
    clock.value = 101.0

    assert not coordinator.clear_cooldown_from_health_evidence(
        row,
        reason=SearchProviderAttemptCategory.QUOTA_EXHAUSTED,
        evidence_started_at=100.5,
    )
    assert coordinator.cooldown_reason(row) is SearchProviderAttemptCategory.HTTP_ERROR


def test_process_local_state_is_safe_for_parallel_status_updates() -> None:
    coordinator = SearchProviderChainCoordinator()
    rows = [candidate(f"row-{index}", f"identity-{index}") for index in range(16)]
    failure = SearchProviderAttemptError(SearchProviderAttemptCategory.UPSTREAM_FAILURE)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda item: coordinator.mark_failed(item, failure), rows))

    assert all(coordinator.is_cooling(item) for item in rows)
