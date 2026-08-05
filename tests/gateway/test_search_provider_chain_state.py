import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from codex_rosetta.gateway.search_provider_candidates import (
    TavilySearchProviderCandidate,
)
from codex_rosetta.gateway.search_provider_chain import (
    DEFAULT_SEARCH_PROVIDER_COOLDOWN_SECONDS,
    SearchProviderAttemptCategory,
    SearchProviderAttemptError,
    SearchProviderBudgetExceeded,
    SearchProviderBudgetReason,
    SearchProviderChainCoordinator,
    SearchProviderChainUnavailable,
    SearchProviderRequestFailover,
    SearchProviderRequestFailoverReason,
)
from codex_rosetta.gateway.search_provider_chain_state import (
    MAX_ACTIVE_ATTEMPTS_PER_CANDIDATE,
)


class Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.value


def candidate(row_id: str, identity: str) -> TavilySearchProviderCandidate:
    return TavilySearchProviderCandidate(
        row_id=row_id,
        api_key=f"private-{row_id}",
        identity=identity,
    )


def run(coro: Awaitable[Any]) -> Any:
    return asyncio.run(coro)


async def wait_until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0)


@pytest.mark.parametrize("state_capacity", [0, -1, True, 1.5])
def test_state_capacity_must_be_a_fixed_positive_integer(state_capacity: Any) -> None:
    with pytest.raises(ValueError, match="state_capacity must be a positive integer"):
        SearchProviderChainCoordinator(state_capacity=state_capacity)


def test_four_exact_identity_attempts_run_and_fifth_waits_for_any_completion() -> None:
    async def scenario() -> None:
        item = candidate("shared", "exact-identity")
        coordinator = SearchProviderChainCoordinator()
        releases = [asyncio.Event() for _ in range(5)]
        started: list[int] = []

        async def runner(_item: TavilySearchProviderCandidate) -> int:
            attempt = len(started)
            started.append(attempt)
            await releases[attempt].wait()
            return attempt

        tasks = [
            asyncio.create_task(coordinator.run((item,), runner)) for _ in range(5)
        ]
        await wait_until(lambda: len(started) == MAX_ACTIVE_ATTEMPTS_PER_CANDIDATE)
        assert len(started) == 4
        assert tasks[4].done() is False

        releases[2].set()
        assert await tasks[2] == 2
        await wait_until(lambda: len(started) == 5)
        assert started == [0, 1, 2, 3, 4]

        for index in (0, 1, 3, 4):
            releases[index].set()
        assert await asyncio.gather(tasks[0], tasks[1], tasks[3], tasks[4]) == [
            0,
            1,
            3,
            4,
        ]

    run(scenario())


def test_cancelled_capacity_waiter_does_not_cancel_shared_notification_or_inflight() -> (
    None
):
    async def scenario() -> None:
        item = candidate("shared", "exact-identity")
        coordinator = SearchProviderChainCoordinator()
        releases = [asyncio.Event() for _ in range(5)]
        started: list[int] = []

        async def runner(_item: TavilySearchProviderCandidate) -> int:
            attempt = len(started)
            started.append(attempt)
            await releases[attempt].wait()
            return attempt

        active = [
            asyncio.create_task(coordinator.run((item,), runner)) for _ in range(4)
        ]
        await wait_until(lambda: len(started) == 4)
        cancelled_waiter = asyncio.create_task(coordinator.run((item,), runner))
        surviving_waiter = asyncio.create_task(coordinator.run((item,), runner))
        await asyncio.sleep(0)
        cancelled_waiter.cancel("capacity-waiter-cancel")
        with pytest.raises(asyncio.CancelledError) as caught:
            await cancelled_waiter
        assert caught.value.args == ("capacity-waiter-cancel",)
        assert len(started) == 4

        releases[1].set()
        assert await active[1] == 1
        await wait_until(lambda: len(started) == 5)
        assert surviving_waiter.done() is False

        for index in (0, 2, 3, 4):
            releases[index].set()
        assert await asyncio.gather(active[0], active[2], active[3]) == [0, 2, 3]
        assert await surviving_waiter == 4

    run(scenario())


def test_reservation_release_is_idempotent_and_never_leaves_negative_inflight() -> None:
    async def scenario() -> None:
        item = candidate("shared", "exact-identity")
        coordinator = SearchProviderChainCoordinator(state_capacity=1)
        state = coordinator._state
        protected_keys = state.keys_for((item,))
        reservation, cooling_reason = await state.reserve(item, protected_keys)
        assert reservation is not None
        assert cooling_reason is None

        state.release(reservation)
        state.release(reservation)

        assert state._entries == {}
        assert state._reservations == {}

    run(scenario())


@pytest.mark.parametrize(
    "terminal",
    ["success", "attempt", "request", "unknown", "budget", "cancel"],
)
def test_every_runner_terminal_path_releases_reservation(terminal: str) -> None:
    async def scenario() -> None:
        coordinator = SearchProviderChainCoordinator(state_capacity=1)
        first = candidate("first", "first-identity")
        following = candidate("following", "following-identity")

        async def terminal_runner(_item: TavilySearchProviderCandidate) -> str:
            if terminal == "success":
                return "first-result"
            if terminal == "attempt":
                raise SearchProviderAttemptError(
                    SearchProviderAttemptCategory.HTTP_ERROR
                )
            if terminal == "request":
                raise SearchProviderRequestFailover(
                    SearchProviderRequestFailoverReason.REQUEST_REJECTED
                )
            if terminal == "unknown":
                raise RuntimeError("private-upstream-detail")
            if terminal == "budget":
                raise SearchProviderBudgetExceeded(
                    SearchProviderBudgetReason.DEADLINE_EXCEEDED
                )
            raise asyncio.CancelledError("runner-cancel")

        if terminal == "success":
            assert await coordinator.run((first,), terminal_runner) == "first-result"
        elif terminal in {"attempt", "request"}:
            with pytest.raises(SearchProviderChainUnavailable):
                await coordinator.run((first,), terminal_runner)
        elif terminal == "unknown":
            with pytest.raises(RuntimeError, match="private-upstream-detail"):
                await coordinator.run((first,), terminal_runner)
        elif terminal == "budget":
            with pytest.raises(SearchProviderBudgetExceeded):
                await coordinator.run((first,), terminal_runner)
        else:
            with pytest.raises(asyncio.CancelledError, match="runner-cancel"):
                await coordinator.run((first,), terminal_runner)

        async def following_runner(_item: TavilySearchProviderCandidate) -> str:
            return "following-result"

        assert (
            await coordinator.run((following,), following_runner) == "following-result"
        )

    run(scenario())


def test_expired_cooldown_is_pruned_before_capacity_reclamation() -> None:
    clock = Clock()
    coordinator = SearchProviderChainCoordinator(clock=clock, state_capacity=2)
    expired = candidate("expired", "expired-identity")
    retained = candidate("retained", "retained-identity")
    newcomer = candidate("new", "new-identity")
    failure = SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)
    coordinator.mark_failed(expired, failure)
    clock.value += 1
    coordinator.mark_failed(retained, failure)
    clock.value += DEFAULT_SEARCH_PROVIDER_COOLDOWN_SECONDS - 0.5

    async def runner(_item: TavilySearchProviderCandidate) -> str:
        return "ok"

    assert run(coordinator.run((newcomer,), runner)) == "ok"
    assert coordinator.is_cooling(expired) is False
    assert coordinator.is_cooling(retained) is True


def test_capacity_reclaims_oldest_non_chain_non_inflight_cooldown() -> None:
    clock = Clock()
    coordinator = SearchProviderChainCoordinator(clock=clock, state_capacity=2)
    oldest = candidate("oldest", "oldest-identity")
    newer = candidate("newer", "newer-identity")
    newcomer = candidate("new", "new-identity")
    failure = SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)
    coordinator.mark_failed(oldest, failure)
    clock.value += 1
    coordinator.mark_failed(newer, failure)

    async def runner(_item: TavilySearchProviderCandidate) -> str:
        return "ok"

    assert run(coordinator.run((newcomer,), runner)) == "ok"
    assert coordinator.is_cooling(oldest) is False
    assert coordinator.is_cooling(newer) is True


def test_current_chain_cooldown_is_protected_during_reclamation() -> None:
    clock = Clock()
    coordinator = SearchProviderChainCoordinator(clock=clock, state_capacity=2)
    outside_chain = candidate("outside", "outside-identity")
    protected = candidate("protected", "protected-identity")
    newcomer = candidate("new", "new-identity")
    failure = SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)
    coordinator.mark_failed(outside_chain, failure)
    clock.value += 1
    coordinator.mark_failed(protected, failure)

    async def runner(item: TavilySearchProviderCandidate) -> str:
        assert item is newcomer
        return "ok"

    assert run(coordinator.run((protected, newcomer), runner)) == "ok"
    assert coordinator.is_cooling(outside_chain) is False
    assert coordinator.is_cooling(protected) is True


def test_inflight_entry_is_not_reclaimed_and_release_wakes_capacity_waiter() -> None:
    async def scenario() -> None:
        clock = Clock()
        coordinator = SearchProviderChainCoordinator(clock=clock, state_capacity=1)
        active = candidate("active", "active-identity")
        waiting = candidate("waiting", "waiting-identity")
        release = asyncio.Event()
        active_started = asyncio.Event()
        waiting_started = asyncio.Event()

        async def active_runner(_item: TavilySearchProviderCandidate) -> str:
            active_started.set()
            await release.wait()
            return "active"

        async def waiting_runner(_item: TavilySearchProviderCandidate) -> str:
            waiting_started.set()
            return "waiting"

        active_task = asyncio.create_task(coordinator.run((active,), active_runner))
        await active_started.wait()
        waiting_task = asyncio.create_task(coordinator.run((waiting,), waiting_runner))
        await asyncio.sleep(0)
        clock_reads = clock.calls
        for _ in range(3):
            await asyncio.sleep(0)
        assert waiting_started.is_set() is False
        assert waiting_task.done() is False
        assert clock.calls == clock_reads

        release.set()
        assert await active_task == "active"
        assert await waiting_task == "waiting"

    run(scenario())


def test_no_reclaimable_entry_waits_for_rotated_capacity_event_without_polling() -> (
    None
):
    async def scenario() -> None:
        clock = Clock()
        coordinator = SearchProviderChainCoordinator(clock=clock, state_capacity=1)
        protected = candidate("protected", "protected-identity")
        newcomer = candidate("new", "new-identity")
        coordinator.mark_failed(
            protected,
            SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR),
        )
        runner_started = asyncio.Event()

        async def runner(item: TavilySearchProviderCandidate) -> str:
            assert item is newcomer
            runner_started.set()
            return "ok"

        task = asyncio.create_task(coordinator.run((protected, newcomer), runner))
        await asyncio.sleep(0)
        clock_reads = clock.calls
        for _ in range(3):
            await asyncio.sleep(0)
        assert runner_started.is_set() is False
        assert task.done() is False
        assert clock.calls == clock_reads

        clock.value += DEFAULT_SEARCH_PROVIDER_COOLDOWN_SECONDS
        assert coordinator.cooldown_reason(protected) is None
        assert await task == "ok"

    run(scenario())
