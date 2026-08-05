import asyncio
import threading
import time
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from codex_rosetta.gateway import (
    search_provider_chain_state as search_provider_chain_state_module,
)
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
    SearchProviderChainUnavailableReason,
    SearchProviderRequestFailover,
    SearchProviderRequestFailoverReason,
    SearchProviderStateCapacityUnavailable,
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


class NaturalClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return time.monotonic()


def candidate(
    row_id: str, identity: str, *, api_key: str | None = None
) -> TavilySearchProviderCandidate:
    return TavilySearchProviderCandidate(
        row_id=row_id,
        api_key=api_key or f"private-{row_id}",
        identity=identity,
    )


def run(coro: Awaitable[Any]) -> Any:
    return asyncio.run(coro)


def format_traceback_with_locals(error: BaseException) -> str:
    traceback_frame = error.__traceback__
    while (
        traceback_frame is not None
        and traceback_frame.tb_frame.f_code.co_filename == __file__
    ):
        traceback_frame = traceback_frame.tb_next
    return "".join(
        traceback.TracebackException(
            type(error),
            error,
            traceback_frame,
            capture_locals=True,
        ).format()
    )


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
        assert coordinator._state._waiters == {}
        assert coordinator._state._protection_counts == {}

    run(scenario())


def test_reservation_release_is_idempotent_and_never_leaves_negative_inflight() -> None:
    async def scenario() -> None:
        item = candidate("shared", "exact-identity")
        coordinator = SearchProviderChainCoordinator(state_capacity=1)
        state = coordinator._state
        reservation, cooling_reason = await state.reserve(item)
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
        assert coordinator._state._protections == {}
        assert coordinator._state._protection_counts == {}

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


def test_protected_cooldown_naturally_expires_and_wakes_capacity_waiter() -> None:
    async def scenario() -> None:
        clock = NaturalClock()
        coordinator = SearchProviderChainCoordinator(
            clock=clock,
            cooldown_seconds=0.05,
            state_capacity=1,
        )
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
        assert runner_started.is_set() is False
        assert task.done() is False

        async with asyncio.timeout(1):
            assert await task == "ok"
        assert coordinator.cooldown_reason(protected) is None
        assert clock.calls <= 8

    run(scenario())


def test_cancelled_waiter_allows_same_state_to_wait_in_a_new_asyncio_run() -> None:
    coordinator = SearchProviderChainCoordinator()
    state = coordinator._state
    item = candidate("shared", "exact-identity")

    async def fill_and_cancel_waiter() -> list[Any]:
        reservations: list[Any] = []
        for _ in range(MAX_ACTIVE_ATTEMPTS_PER_CANDIDATE):
            reservation, cooling_reason = await state.reserve(item)
            assert reservation is not None
            assert cooling_reason is None
            reservations.append(reservation)

        waiter = asyncio.create_task(state.reserve(item))
        await wait_until(lambda: len(state._waiters) == 1)
        waiter.cancel("old-loop-waiter")
        with pytest.raises(asyncio.CancelledError, match="old-loop-waiter"):
            await waiter
        assert state._waiters == {}
        return reservations

    reservations = run(fill_and_cancel_waiter())

    async def reuse_in_new_loop() -> None:
        waiter = asyncio.create_task(state.reserve(item))
        await wait_until(lambda: len(state._waiters) == 1)
        state.release(reservations.pop())
        reservation, cooling_reason = await waiter
        assert reservation is not None
        assert cooling_reason is None
        state.release(reservation)

    run(reuse_in_new_loop())
    for reservation in reservations:
        state.release(reservation)
    assert state._entries == {}
    assert state._waiters == {}


def test_release_wakes_waiter_owned_by_another_event_loop_thread() -> None:
    coordinator = SearchProviderChainCoordinator(state_capacity=1)
    active = candidate("active", "active-identity")
    waiting = candidate("waiting", "waiting-identity")
    active_started = threading.Event()
    active_loop_ready = threading.Event()
    active_loop: asyncio.AbstractEventLoop | None = None
    active_release: asyncio.Future[None] | None = None
    results: dict[str, str] = {}
    errors: list[Exception] = []

    def run_active() -> None:
        async def scenario() -> None:
            nonlocal active_loop, active_release
            active_loop = asyncio.get_running_loop()
            active_loop.set_debug(True)
            active_release = active_loop.create_future()
            active_loop_ready.set()

            async def runner(_item: TavilySearchProviderCandidate) -> str:
                active_started.set()
                assert active_release is not None
                await active_release
                return "active"

            results["active"] = await coordinator.run((active,), runner)

        try:
            asyncio.run(scenario())
        except Exception as error:
            errors.append(error)

    def run_waiter() -> None:
        async def scenario() -> None:
            asyncio.get_running_loop().set_debug(True)

            async def runner(_item: TavilySearchProviderCandidate) -> str:
                return "waiting"

            results["waiting"] = await coordinator.run((waiting,), runner)

        try:
            asyncio.run(scenario())
        except Exception as error:
            errors.append(error)

    active_thread = threading.Thread(target=run_active)
    waiter_thread = threading.Thread(target=run_waiter)
    active_thread.start()
    assert active_loop_ready.wait(1)
    assert active_started.wait(1)
    waiter_thread.start()

    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        with coordinator._state._lock:
            if coordinator._state._waiters:
                break
        time.sleep(0.001)
    else:
        pytest.fail("cross-loop waiter was not registered")

    assert active_loop is not None
    assert active_release is not None
    active_loop.call_soon_threadsafe(active_release.set_result, None)
    active_thread.join(1)
    waiter_thread.join(1)

    assert active_thread.is_alive() is False
    assert waiter_thread.is_alive() is False
    assert errors == []
    assert results == {"active": "active", "waiting": "waiting"}


def test_closed_waiter_loop_does_not_override_release_result() -> None:
    async def reserve_active() -> tuple[Any, Any]:
        coordinator = SearchProviderChainCoordinator(state_capacity=1)
        item = candidate("active", "active-identity")
        reservation, cooling_reason = await coordinator._state.reserve(item)
        assert reservation is not None
        assert cooling_reason is None
        return coordinator, reservation

    coordinator, reservation = run(reserve_active())
    state = coordinator._state
    closed_loop = asyncio.new_event_loop()
    closed_future = closed_loop.create_future()
    closed_future.cancel()
    closed_loop.close()
    with state._lock:
        state._next_waiter += 1
        waiter = search_provider_chain_state_module._CapacityWaiter(
            state._next_waiter,
            closed_loop,
            closed_future,
        )
        state._waiters[waiter.token] = waiter

    state.release(reservation)

    assert state._entries == {}
    assert state._reservations == {}
    assert state._waiters == {}


def test_active_chain_protection_is_reference_counted_and_release_wakes_waiter() -> (
    None
):
    async def scenario() -> None:
        coordinator = SearchProviderChainCoordinator(state_capacity=1)
        state = coordinator._state
        protected = candidate("protected", "protected-identity")
        newcomer = candidate("new", "new-identity")
        coordinator.mark_failed(
            protected,
            SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR),
        )
        first = state.protect((protected,))
        second = state.protect((protected,))
        waiter = asyncio.create_task(state.reserve(newcomer))
        await wait_until(lambda: len(state._waiters) == 1)

        state.release_protection(first)
        await asyncio.sleep(0)
        assert waiter.done() is False
        await wait_until(lambda: len(state._waiters) == 1)

        state.release_protection(second)
        reservation, cooling_reason = await waiter
        assert reservation is not None
        assert cooling_reason is None
        state.release(reservation)
        assert state._protection_counts == {}

    run(scenario())


def test_external_mark_failed_cannot_reclaim_active_chain_cooldown() -> None:
    async def scenario() -> None:
        clock = Clock()
        coordinator = SearchProviderChainCoordinator(clock=clock, state_capacity=2)
        state = coordinator._state
        protected = candidate("protected", "protected-identity")
        active = candidate("active", "active-identity")
        external_identity = "synthetic-external-private-identity"
        external_api_key = "synthetic-external-private-key"
        raw_error = "synthetic-external-raw-provider-error"
        external = candidate("external", external_identity, api_key=external_api_key)
        failure = SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)
        coordinator.mark_failed(protected, failure)
        active_started = asyncio.Event()
        release_active = asyncio.Event()

        async def runner(item: TavilySearchProviderCandidate) -> str:
            assert item is active
            active_started.set()
            await release_active.wait()
            return "ok"

        task = asyncio.create_task(coordinator.run((protected, active), runner))
        await active_started.wait()

        try:
            raise RuntimeError(raw_error)
        except RuntimeError as raw_cause:
            try:
                raise failure from raw_cause
            except SearchProviderAttemptError as active_failure:
                with pytest.raises(SearchProviderStateCapacityUnavailable) as caught:
                    coordinator.mark_failed(external, active_failure)

        capacity_error = caught.value
        assert str(capacity_error) == "Search provider state capacity unavailable"
        assert capacity_error.__context__ is failure
        assert capacity_error.__suppress_context__ is True
        protected_key = state.key(protected)
        active_key = state.key(active)
        assert set(state._entries) == {protected_key, active_key}
        assert state._entries[protected_key].cooldown_reason == (
            SearchProviderAttemptCategory.HTTP_ERROR
        )
        assert state._entries[protected_key].inflight == 0
        assert state._entries[active_key].cooldown_reason is None
        assert state._entries[active_key].inflight == 1
        assert state.key(external) not in state._entries
        assert tuple(state._reservations.values()) == (active_key,)
        assert state._protection_counts == {protected_key: 1, active_key: 1}
        assert coordinator.is_cooling(protected) is True
        assert coordinator.is_cooling(external) is False
        default_traceback = "".join(traceback.format_exception(capacity_error))
        locals_traceback = format_traceback_with_locals(capacity_error)
        for formatted in (default_traceback, locals_traceback):
            assert str(capacity_error) in formatted
            for secret in (external_identity, external_api_key, raw_error):
                assert secret not in formatted

        release_active.set()
        assert await task == "ok"
        assert coordinator.is_cooling(protected) is True

    run(scenario())


def test_mutable_chain_append_cannot_escape_active_protection_snapshot() -> None:
    async def scenario() -> None:
        coordinator = SearchProviderChainCoordinator(state_capacity=2)
        protected = candidate("protected", "protected-identity")
        active = candidate("active", "active-identity")
        late = candidate("late", "late-identity")
        external = candidate("external", "external-identity")
        failure = SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)
        coordinator.mark_failed(protected, failure)
        active_started = asyncio.Event()
        release_active = asyncio.Event()
        calls: list[str] = []

        async def runner(item: TavilySearchProviderCandidate) -> str:
            calls.append(item.row_id)
            if item is active:
                active_started.set()
                await release_active.wait()
                raise SearchProviderRequestFailover(
                    SearchProviderRequestFailoverReason.LOCAL_UNAVAILABLE
                )
            return "late-result"

        chain = [protected, active]
        task = asyncio.create_task(coordinator.run(chain, runner))
        await active_started.wait()
        chain.append(late)

        with pytest.raises(SearchProviderStateCapacityUnavailable):
            coordinator.mark_failed(external, failure)
        assert coordinator.is_cooling(protected) is True

        release_active.set()
        with pytest.raises(SearchProviderChainUnavailable) as caught:
            await task
        assert (
            caught.value.reason
            is SearchProviderChainUnavailableReason.ALL_ATTEMPTS_FAILED
        )
        assert calls == ["active"]
        assert coordinator.is_cooling(protected) is True
        assert coordinator.is_cooling(late) is False

    run(scenario())


def test_mutable_chain_replace_cannot_change_entry_snapshot() -> None:
    async def scenario() -> None:
        coordinator = SearchProviderChainCoordinator(state_capacity=2)
        late = candidate("late", "late-identity")
        active = candidate("active", "active-identity")
        pending = candidate("pending", "pending-identity")
        external = candidate("external", "external-identity")
        failure = SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)
        coordinator.mark_failed(late, failure)
        active_started = asyncio.Event()
        release_active = asyncio.Event()
        calls: list[str] = []

        async def runner(item: TavilySearchProviderCandidate) -> str:
            calls.append(item.row_id)
            if item is active:
                active_started.set()
                await release_active.wait()
                raise SearchProviderRequestFailover(
                    SearchProviderRequestFailoverReason.LOCAL_UNAVAILABLE
                )
            assert item is pending
            return "snapshot-result"

        chain = [late, active, pending]
        task = asyncio.create_task(coordinator.run(chain, runner))
        await active_started.wait()
        chain[2] = late

        with pytest.raises(SearchProviderStateCapacityUnavailable):
            coordinator.mark_failed(external, failure)
        assert coordinator.is_cooling(late) is True

        release_active.set()
        assert await task == "snapshot-result"
        assert calls == ["active", "pending"]
        assert coordinator.is_cooling(late) is True
        assert coordinator.is_cooling(external) is False

    run(scenario())


def test_synchronous_mark_failed_fails_closed_when_inflight_owns_capacity() -> None:
    async def scenario() -> None:
        coordinator = SearchProviderChainCoordinator(state_capacity=1)
        active = candidate("active", "active-identity")
        external = candidate("external", "external-identity")
        active_started = asyncio.Event()
        release_active = asyncio.Event()

        async def runner(_item: TavilySearchProviderCandidate) -> str:
            active_started.set()
            await release_active.wait()
            return "ok"

        task = asyncio.create_task(coordinator.run((active,), runner))
        await active_started.wait()
        with pytest.raises(
            SearchProviderStateCapacityUnavailable,
            match="^Search provider state capacity unavailable$",
        ):
            coordinator.mark_failed(
                external,
                SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR),
            )
        assert len(coordinator._state._entries) == 1
        assert coordinator.is_cooling(external) is False

        release_active.set()
        assert await task == "ok"

    run(scenario())
