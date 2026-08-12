import asyncio
import gc
import math
import time
import traceback
import weakref
from collections.abc import Awaitable
from typing import Any

import pytest

from codex_rosetta.gateway import search_provider_chain as search_provider_chain_module
from codex_rosetta.gateway import (
    search_provider_chain_state as search_provider_chain_state_module,
)
from codex_rosetta.gateway.search_provider_candidates import (
    DeepSeekNativeResponsesSearchProviderCandidate,
    TavilySearchProviderCandidate,
)
from codex_rosetta.gateway.search_provider_chain import (
    DEFAULT_SEARCH_PROVIDER_COOLDOWN_SECONDS,
    MAX_SEARCH_PROVIDER_EXTERNAL_CALLS,
    SEARCH_PROVIDER_REQUEST_TIMEOUT_SECONDS,
    SearchProviderAttemptCategory,
    SearchProviderAttemptError,
    SearchProviderBudgetExceeded,
    SearchProviderBudgetReason,
    SearchProviderChainUnavailable,
    SearchProviderChainUnavailableReason,
    SearchProviderChainCoordinator,
    SearchProviderRequestBudget,
    SearchProviderRequestFailover,
    SearchProviderRequestFailoverReason,
)
from codex_rosetta.gateway.search_usage import TavilyUsage


class Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.value


def run(coro: Awaitable[Any]) -> Any:
    return asyncio.run(coro)


def _deepseek_candidate(row_id: str) -> DeepSeekNativeResponsesSearchProviderCandidate:
    return DeepSeekNativeResponsesSearchProviderCandidate(
        row_id=row_id,
        deepseek_provider="official",
        provider_info=object(),
        identity=f"identity-{row_id}",
    )


def test_deepseek_attempt_failure_cools_once_and_tries_next_candidate():
    first = _deepseek_candidate("deepseek")
    second = TavilySearchProviderCandidate("tavily", api_key="secret", identity="two")
    coordinator = SearchProviderChainCoordinator()
    calls = []

    async def runner(candidate):
        calls.append(candidate.row_id)
        if candidate is first:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.CONNECTION_ERROR
            )
        return "ok"

    assert run(coordinator.run((first, second), runner)) == "ok"
    assert calls == ["deepseek", "tavily"]
    assert (
        coordinator.cooldown_reason(first)
        is SearchProviderAttemptCategory.CONNECTION_ERROR
    )
    assert not coordinator.is_cooling(second)


def test_deepseek_unknown_control_signal_is_neutral_and_does_not_fail_over():
    first = _deepseek_candidate("deepseek")
    second = TavilySearchProviderCandidate("tavily", api_key="secret", identity="two")
    coordinator = SearchProviderChainCoordinator()
    signal = MemoryError("stop")
    calls = []

    async def runner(candidate):
        calls.append(candidate.row_id)
        raise signal

    with pytest.raises(MemoryError) as caught:
        run(coordinator.run((first, second), runner))

    assert caught.value is signal
    assert calls == ["deepseek"]
    assert not coordinator.is_cooling(first)
    assert not coordinator.is_cooling(second)


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


def test_budget_defaults_are_fixed() -> None:
    assert SEARCH_PROVIDER_REQUEST_TIMEOUT_SECONDS == 300.0
    assert MAX_SEARCH_PROVIDER_EXTERNAL_CALLS == 32


@pytest.mark.parametrize(
    ("timeout_seconds", "max_external_calls"), [(0, 1), (-1, 1), (1, 0), (1, -1)]
)
def test_budget_rejects_non_positive_limits(
    timeout_seconds: float, max_external_calls: int
) -> None:
    with pytest.raises(ValueError):
        SearchProviderRequestBudget(
            timeout_seconds=timeout_seconds, max_external_calls=max_external_calls
        )


@pytest.mark.parametrize("timeout_seconds", [math.nan, math.inf, -math.inf])
def test_budget_rejects_non_finite_timeout(timeout_seconds: float) -> None:
    with pytest.raises(ValueError):
        SearchProviderRequestBudget(timeout_seconds=timeout_seconds)


@pytest.mark.parametrize("max_external_calls", [True, 1.5, math.nan, math.inf])
def test_budget_rejects_non_integer_external_call_limit(
    max_external_calls: Any,
) -> None:
    with pytest.raises(ValueError):
        SearchProviderRequestBudget(max_external_calls=max_external_calls)


@pytest.mark.parametrize("initial_clock", [math.nan, math.inf, -math.inf])
def test_budget_rejects_non_finite_initial_clock(initial_clock: float) -> None:
    with pytest.raises(ValueError):
        SearchProviderRequestBudget(clock=lambda: initial_clock)


def test_budget_deadline_is_frozen_and_run_does_not_count_calls() -> None:
    clock = Clock()
    budget = SearchProviderRequestBudget(timeout_seconds=5, clock=clock)
    assert clock.calls == 1
    started = False

    async def operation() -> str:
        nonlocal started
        started = True
        return "ok"

    assert run(budget.run(operation)) == "ok"
    assert budget.external_calls == 0
    assert budget.deadline == 105.0
    clock.value = 105.0
    started = False
    with pytest.raises(SearchProviderBudgetExceeded) as caught:
        run(budget.run(operation))
    assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED
    assert started is False


@pytest.mark.parametrize("completed_at", [105.0, 105.001])
def test_external_call_rejects_completion_at_or_after_absolute_deadline(
    completed_at: float,
) -> None:
    clock = Clock()
    budget = SearchProviderRequestBudget(timeout_seconds=5, clock=clock)

    async def operation() -> str:
        clock.value = completed_at
        return "late"

    with pytest.raises(SearchProviderBudgetExceeded) as caught:
        run(budget.run_external_call(operation))

    assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED
    assert budget.external_calls == 1


def test_budget_deadline_wins_over_and_observes_late_operation_error() -> None:
    async def scenario() -> None:
        clock = Clock()
        budget = SearchProviderRequestBudget(timeout_seconds=5, clock=clock)
        loop = asyncio.get_running_loop()
        unhandled: list[dict[str, object]] = []
        original_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))

        async def operation() -> None:
            clock.value = budget.deadline
            raise RuntimeError("late-secret")

        try:
            with pytest.raises(SearchProviderBudgetExceeded) as caught:
                await budget.run(operation)
            assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED
            await asyncio.sleep(0)
            assert unhandled == []
        finally:
            loop.set_exception_handler(original_handler)

    run(scenario())


def test_budget_rejects_result_after_event_loop_starvation() -> None:
    async def operation() -> str:
        time.sleep(0.01)
        return "late"

    with pytest.raises(SearchProviderBudgetExceeded) as caught:
        run(SearchProviderRequestBudget(timeout_seconds=0.001).run(operation))

    assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED


@pytest.mark.parametrize(
    ("completed_at", "deadline_wins"),
    [(104.0, False), (105.0, True), (105.001, True), (math.nan, True), (99.0, True)],
)
@pytest.mark.parametrize(
    "factory_failure",
    [
        None,
        RuntimeError("factory-secret"),
        TimeoutError("factory-timeout"),
        asyncio.CancelledError("factory-cancel"),
    ],
)
def test_sync_factory_completion_uses_absolute_deadline_owner(
    completed_at: float,
    deadline_wins: bool,
    factory_failure: BaseException | None,
) -> None:
    clock = Clock()
    budget = SearchProviderRequestBudget(timeout_seconds=5, clock=clock)
    factory_calls = 0
    body_calls = 0

    async def body() -> str:
        nonlocal body_calls
        body_calls += 1
        return "ok"

    def operation() -> Awaitable[str]:
        nonlocal factory_calls
        factory_calls += 1
        clock.value = completed_at
        if factory_failure is not None:
            raise factory_failure
        return body()

    if deadline_wins:
        with pytest.raises(SearchProviderBudgetExceeded) as caught:
            run(budget.run(operation))
        assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED
    elif factory_failure is not None:
        with pytest.raises(type(factory_failure)) as caught:
            run(budget.run(operation))
        assert caught.value is factory_failure
    else:
        assert run(budget.run(operation)) == "ok"

    assert factory_calls == 1
    assert body_calls == (0 if factory_failure is not None else 1)


@pytest.mark.parametrize(
    "factory_failure",
    [
        None,
        RuntimeError("factory-secret"),
        TimeoutError("factory-timeout"),
        asyncio.CancelledError("factory-cancel"),
    ],
)
def test_sync_factory_real_deadline_owns_late_completion(
    factory_failure: BaseException | None,
) -> None:
    async def body() -> str:
        return "late"

    def operation() -> Awaitable[str]:
        time.sleep(0.01)
        if factory_failure is not None:
            raise factory_failure
        return body()

    with pytest.raises(SearchProviderBudgetExceeded) as caught:
        run(SearchProviderRequestBudget(timeout_seconds=0.001).run(operation))

    assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED


def test_sync_factory_external_call_stays_charged_when_deadline_wins() -> None:
    clock = Clock()
    budget = SearchProviderRequestBudget(timeout_seconds=5, clock=clock)
    failure = RuntimeError("factory-secret")

    def operation() -> Awaitable[None]:
        clock.value = budget.deadline
        raise failure

    with pytest.raises(SearchProviderBudgetExceeded) as caught:
        run(budget.run_external_call(operation))

    assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED
    assert budget.external_calls == 1


@pytest.mark.parametrize("completed_at", [104.0, 105.0])
def test_sync_factory_non_awaitable_respects_deadline_owner(
    completed_at: float,
) -> None:
    clock = Clock()
    budget = SearchProviderRequestBudget(timeout_seconds=5, clock=clock)

    def operation() -> Any:
        clock.value = completed_at
        return object()

    expected_error = (
        TypeError if completed_at < budget.deadline else SearchProviderBudgetExceeded
    )
    with pytest.raises(expected_error) as caught:
        run(budget.run(operation))
    if isinstance(caught.value, SearchProviderBudgetExceeded):
        assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED


def test_external_call_limit_allows_exactly_32_operations() -> None:
    budget = SearchProviderRequestBudget()
    calls = 0

    async def operation() -> None:
        nonlocal calls
        calls += 1

    for _ in range(MAX_SEARCH_PROVIDER_EXTERNAL_CALLS):
        run(budget.run_external_call(operation))
    with pytest.raises(SearchProviderBudgetExceeded) as caught:
        run(budget.run_external_call(operation))

    assert (
        caught.value.reason is SearchProviderBudgetReason.EXTERNAL_CALL_LIMIT_EXCEEDED
    )
    assert calls == MAX_SEARCH_PROVIDER_EXTERNAL_CALLS
    assert budget.external_calls == MAX_SEARCH_PROVIDER_EXTERNAL_CALLS


def test_sync_factory_and_returned_body_run_once_per_admitted_call() -> None:
    budget = SearchProviderRequestBudget()
    factory_calls = 0
    body_calls = 0

    async def body() -> None:
        nonlocal body_calls
        body_calls += 1

    def operation() -> Awaitable[None]:
        nonlocal factory_calls
        factory_calls += 1
        return body()

    for _ in range(MAX_SEARCH_PROVIDER_EXTERNAL_CALLS):
        run(budget.run_external_call(operation))
    with pytest.raises(SearchProviderBudgetExceeded) as caught:
        run(budget.run_external_call(operation))

    assert (
        caught.value.reason is SearchProviderBudgetReason.EXTERNAL_CALL_LIMIT_EXCEEDED
    )
    assert factory_calls == MAX_SEARCH_PROVIDER_EXTERNAL_CALLS
    assert body_calls == MAX_SEARCH_PROVIDER_EXTERNAL_CALLS


def test_sync_factory_and_returned_body_share_budget_owned_child() -> None:
    async def scenario() -> None:
        caller = asyncio.current_task()
        factory_task: asyncio.Task[Any] | None = None
        body_task: asyncio.Task[Any] | None = None

        async def body() -> None:
            nonlocal body_task
            body_task = asyncio.current_task()

        def operation() -> Awaitable[None]:
            nonlocal factory_task
            factory_task = asyncio.current_task()
            return body()

        await SearchProviderRequestBudget().run(operation)

        assert factory_task is not caller
        assert factory_task is body_task

    run(scenario())


def test_preexpired_budget_does_not_invoke_sync_factory_or_body() -> None:
    clock = Clock()
    budget = SearchProviderRequestBudget(timeout_seconds=1, clock=clock)
    clock.value = budget.deadline
    factory_calls = 0
    body_calls = 0

    async def body() -> None:
        nonlocal body_calls
        body_calls += 1

    def operation() -> Awaitable[None]:
        nonlocal factory_calls
        factory_calls += 1
        return body()

    with pytest.raises(SearchProviderBudgetExceeded) as caught:
        run(budget.run_external_call(operation))

    assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED
    assert budget.external_calls == 0
    assert factory_calls == 0
    assert body_calls == 0


def test_budget_times_out_operation_but_propagates_cancel_and_unknown_errors() -> None:
    async def blocked() -> None:
        await asyncio.Event().wait()

    with pytest.raises(SearchProviderBudgetExceeded) as caught:
        run(SearchProviderRequestBudget(timeout_seconds=0.001).run(blocked))
    assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED

    for failure in (
        TimeoutError("operation timeout"),
        asyncio.CancelledError(),
        RuntimeError("secret"),
    ):

        async def failing(error: BaseException = failure) -> None:
            raise error

        with pytest.raises(type(failure)) as propagated:
            run(SearchProviderRequestBudget().run(failing))
        assert propagated.value is failure


def test_budget_deadline_rejects_result_from_cancellation_resistant_operation() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        finished = asyncio.Event()

        async def operation() -> str:
            try:
                await asyncio.Event().wait()
                raise AssertionError("unreachable")
            except asyncio.CancelledError:
                await release.wait()
                finished.set()
                return "returned-after-budget-cancel"

        async with asyncio.timeout(0.1):
            with pytest.raises(SearchProviderBudgetExceeded) as caught:
                await SearchProviderRequestBudget(timeout_seconds=0.001).run(operation)
            assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED
            release.set()
            await finished.wait()

    run(scenario())


def test_budget_observes_replacement_error_after_deadline_cancellation() -> None:
    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        unhandled: list[dict[str, object]] = []
        original_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))

        async def operation() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise RuntimeError("replacement-detail")

        try:
            with pytest.raises(SearchProviderBudgetExceeded) as caught:
                await SearchProviderRequestBudget(timeout_seconds=0.001).run(operation)
            assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED
            await asyncio.sleep(0)
            assert unhandled == []
        finally:
            loop.set_exception_handler(original_handler)

    run(scenario())


def test_external_cancellation_cancels_operation_and_remains_external() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def operation() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        caller = asyncio.create_task(SearchProviderRequestBudget().run(operation))
        await started.wait()
        caller.cancel("external-cancel")
        with pytest.raises(asyncio.CancelledError) as caught:
            await caller
        assert caught.value.args == ("external-cancel",)
        await cancelled.wait()

    run(scenario())


@pytest.mark.parametrize("terminal_owner", ["budget", "outer"])
@pytest.mark.parametrize("late_outcome", ["success", "error", "cancel"])
def test_detached_cancellation_resistant_operation_is_retained_until_observed(
    terminal_owner: str,
    late_outcome: str,
) -> None:
    async def scenario() -> None:
        assert search_provider_chain_module._DETACHED_OPERATION_FUTURES == set()
        loop = asyncio.get_running_loop()
        unhandled: list[dict[str, object]] = []
        original_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
        operation_started = asyncio.Event()
        cancellation_resisted = asyncio.Event()
        child_refs: list[weakref.ReferenceType[asyncio.Task[Any]]] = []
        release_refs: list[weakref.ReferenceType[asyncio.Event]] = []

        async def operation() -> str:
            child = asyncio.current_task()
            assert child is not None
            release = asyncio.Event()
            child_refs.append(weakref.ref(child))
            release_refs.append(weakref.ref(release))
            operation_started.set()
            try:
                await asyncio.Event().wait()
                raise AssertionError("unreachable")
            except asyncio.CancelledError:
                cancellation_resisted.set()
                await release.wait()
            if late_outcome == "error":
                raise RuntimeError("late-private-detail")
            if late_outcome == "cancel":
                raise asyncio.CancelledError("late-private-cancel")
            return "late-private-success"

        try:
            if terminal_owner == "budget":
                try:
                    await SearchProviderRequestBudget(timeout_seconds=0.001).run(
                        operation
                    )
                except SearchProviderBudgetExceeded as error:
                    assert error.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED
                else:
                    pytest.fail("budget deadline did not own the terminal result")
            else:
                caller = asyncio.create_task(
                    SearchProviderRequestBudget().run(operation)
                )
                await operation_started.wait()
                caller.cancel("outer-owner")
                try:
                    await caller
                except asyncio.CancelledError as error:
                    assert error.args == ("outer-owner",)
                else:
                    pytest.fail("outer cancellation did not own the terminal result")
                del caller

            await cancellation_resisted.wait()
            assert len(child_refs) == 1
            assert len(release_refs) == 1
            child_ref = child_refs[0]
            release_ref = release_refs[0]
            assert (
                child_ref() in search_provider_chain_module._DETACHED_OPERATION_FUTURES
            )

            gc.collect()
            await asyncio.sleep(0)

            assert child_ref() is not None
            assert (
                child_ref() in search_provider_chain_module._DETACHED_OPERATION_FUTURES
            )
            assert unhandled == []

            release = release_ref()
            assert release is not None
            release.set()
            del release
            for _ in range(3):
                await asyncio.sleep(0)

            assert search_provider_chain_module._DETACHED_OPERATION_FUTURES == set()
            assert unhandled == []
            gc.collect()
            assert child_ref() is None
        finally:
            release = release_refs[0]() if release_refs else None
            if release is not None:
                release.set()
            await asyncio.sleep(0)
            loop.set_exception_handler(original_handler)

    run(scenario())


def test_external_call_checks_deadline_before_charging_or_starting() -> None:
    clock = Clock()
    budget = SearchProviderRequestBudget(timeout_seconds=1, clock=clock)
    clock.value += 1
    started = False

    async def operation() -> None:
        nonlocal started
        started = True

    with pytest.raises(SearchProviderBudgetExceeded) as caught:
        run(budget.run_external_call(operation))

    assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED
    assert budget.external_calls == 0
    assert started is False


@pytest.mark.parametrize("bad_clock", [math.nan, math.inf, -math.inf, 99.0])
def test_invalid_runtime_clock_fails_before_operation_or_count(
    bad_clock: float,
) -> None:
    clock = Clock()
    budget = SearchProviderRequestBudget(timeout_seconds=5, clock=clock)
    clock.value = bad_clock
    started = False

    async def operation() -> None:
        nonlocal started
        started = True

    with pytest.raises(SearchProviderBudgetExceeded) as caught:
        run(budget.run_external_call(operation))

    assert caught.value.reason is SearchProviderBudgetReason.DEADLINE_EXCEEDED
    assert budget.external_calls == 0
    assert started is False
    summary = budget.summary()
    assert summary["elapsed_seconds"] == 0.0
    assert summary["deadline_seconds"] == 5.0


def test_external_call_starts_after_single_successful_deadline_admission() -> None:
    clock_values = iter((100.0, 104.0, 104.5))
    clock_reads: list[float] = []

    def crossing_clock() -> float:
        value = next(clock_values)
        clock_reads.append(value)
        return value

    budget = SearchProviderRequestBudget(timeout_seconds=5, clock=crossing_clock)
    started = False

    async def operation() -> str:
        nonlocal started
        started = True
        return "ok"

    assert run(budget.run_external_call(operation)) == "ok"
    assert started is True
    assert budget.external_calls == 1
    assert clock_reads == [100.0, 104.0, 104.5]


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("operation timeout"),
        RuntimeError("secret"),
        asyncio.CancelledError(),
    ],
)
def test_external_call_remains_charged_after_started_failure(
    failure: BaseException,
) -> None:
    budget = SearchProviderRequestBudget()

    async def operation() -> None:
        raise failure

    with pytest.raises(type(failure)):
        run(budget.run_external_call(operation))

    assert budget.external_calls == 1


def test_budget_summary_is_bounded_and_secret_safe() -> None:
    clock = Clock()
    budget = SearchProviderRequestBudget(timeout_seconds=10, clock=clock)
    clock.value += 2.5

    assert budget.summary(SearchProviderBudgetReason.DEADLINE_EXCEEDED) == {
        "reason": "deadline_exceeded",
        "external_calls": 0,
        "external_call_limit": 32,
        "elapsed_seconds": 2.5,
        "deadline_seconds": 10.0,
    }
    safe_summary = repr(budget.summary())
    assert all(
        forbidden not in safe_summary
        for forbidden in ("secret", "error", "candidate", "provider", "identity")
    )

    extreme_clock = Clock(-1e308)
    extreme_budget = SearchProviderRequestBudget(
        timeout_seconds=10, clock=extreme_clock
    )
    extreme_clock.value = 1e308
    assert extreme_budget.summary()["elapsed_seconds"] == 10.0


@pytest.mark.parametrize(
    ("error", "reason", "message"),
    [
        (
            SearchProviderBudgetExceeded(
                SearchProviderBudgetReason.EXTERNAL_CALL_LIMIT_EXCEEDED
            ),
            SearchProviderBudgetReason.EXTERNAL_CALL_LIMIT_EXCEEDED,
            "Search provider request budget exceeded",
        ),
        (
            SearchProviderAttemptError(SearchProviderAttemptCategory.INVALID_RESPONSE),
            SearchProviderAttemptCategory.INVALID_RESPONSE,
            "Search provider attempt failed",
        ),
        (
            SearchProviderRequestFailover(
                SearchProviderRequestFailoverReason.REQUEST_REJECTED
            ),
            SearchProviderRequestFailoverReason.REQUEST_REJECTED,
            "Search provider request could not use this candidate",
        ),
        (
            SearchProviderChainUnavailable(
                SearchProviderChainUnavailableReason.ALL_ATTEMPTS_FAILED
            ),
            SearchProviderChainUnavailableReason.ALL_ATTEMPTS_FAILED,
            "Search unavailable; Please consider Browser Use",
        ),
    ],
)
def test_typed_errors_expose_only_bounded_reasons_and_generic_messages(
    error: (
        SearchProviderBudgetExceeded
        | SearchProviderAttemptError
        | SearchProviderRequestFailover
        | SearchProviderChainUnavailable
    ),
    reason: (
        SearchProviderBudgetReason
        | SearchProviderAttemptCategory
        | SearchProviderRequestFailoverReason
        | SearchProviderChainUnavailableReason
    ),
    message: str,
) -> None:
    assert error.reason is reason
    assert str(error) == message
    assert "secret" not in str(error)
    if isinstance(error, SearchProviderAttemptError):
        assert error.category is reason
        assert error.quota_exhausted is False
    with pytest.raises(AttributeError):
        setattr(error, "reason", reason)


def candidate(
    row_id: str, identity: str, *, api_key: str = "tvly-private-key"
) -> TavilySearchProviderCandidate:
    return TavilySearchProviderCandidate(
        row_id=row_id,
        api_key=api_key,
        identity=identity,
    )


def test_chain_defaults_to_one_hour_cooldown() -> None:
    assert DEFAULT_SEARCH_PROVIDER_COOLDOWN_SECONDS == 3600.0


def test_chain_starts_at_current_row_wraps_once_and_records_success() -> None:
    candidates = (
        candidate("first", "identity-first"),
        candidate("current", "identity-current"),
        candidate("last", "identity-last"),
    )
    calls: list[str] = []
    recorded: list[str] = []

    async def runner(item: TavilySearchProviderCandidate) -> str:
        calls.append(item.row_id)
        if item.row_id != "last":
            raise SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)
        return "ok"

    coordinator = SearchProviderChainCoordinator(
        current_provider=lambda: "current",
        record_current=lambda item: recorded.append(item.row_id),
    )

    assert run(coordinator.run(candidates, runner)) == "ok"
    assert calls == ["current", "last"]
    assert recorded == ["last"]


def test_concurrent_failures_share_one_failover_and_waiters_use_replacement() -> None:
    async def scenario() -> None:
        first = candidate("first", "identity-first")
        second = candidate("second", "identity-second")
        coordinator = SearchProviderChainCoordinator()
        release_first = asyncio.Event()
        release_second = asyncio.Event()
        both_first_started = asyncio.Event()
        leader_reached_second = asyncio.Event()
        first_calls = 0
        second_calls = 0

        async def runner(item: TavilySearchProviderCandidate) -> str:
            nonlocal first_calls, second_calls
            if item is first:
                first_calls += 1
                if first_calls == 2:
                    both_first_started.set()
                await release_first.wait()
                raise SearchProviderAttemptError(
                    SearchProviderAttemptCategory.CONNECTION_ERROR
                )
            second_calls += 1
            leader_reached_second.set()
            await release_second.wait()
            return "ok"

        requests = [
            asyncio.create_task(coordinator.run((first, second), runner))
            for _ in range(2)
        ]
        await both_first_started.wait()
        release_first.set()
        await leader_reached_second.wait()
        await asyncio.sleep(0)
        assert second_calls == 1

        release_second.set()
        assert await asyncio.gather(*requests) == ["ok", "ok"]
        assert first_calls == 2
        assert second_calls == 2
        assert coordinator.current_candidate((first, second)) is second

    run(scenario())


def test_request_arriving_during_failover_waits_for_replacement() -> None:
    async def scenario() -> None:
        first = candidate("first", "identity-first")
        second = candidate("second", "identity-second")
        coordinator = SearchProviderChainCoordinator()
        leader_reached_second = asyncio.Event()
        release_second = asyncio.Event()
        calls: list[tuple[str, str]] = []

        async def leader_runner(item: TavilySearchProviderCandidate) -> str:
            calls.append(("leader", item.row_id))
            if item is first:
                raise SearchProviderAttemptError(
                    SearchProviderAttemptCategory.CONNECTION_ERROR
                )
            leader_reached_second.set()
            await release_second.wait()
            return "leader-ok"

        async def later_runner(item: TavilySearchProviderCandidate) -> str:
            calls.append(("later", item.row_id))
            return "later-ok"

        leader = asyncio.create_task(coordinator.run((first, second), leader_runner))
        await leader_reached_second.wait()
        later = asyncio.create_task(coordinator.run((first, second), later_runner))
        await asyncio.sleep(0)
        assert ("later", "first") not in calls
        assert ("later", "second") not in calls

        release_second.set()
        assert await leader == "leader-ok"
        assert await later == "later-ok"
        assert calls == [
            ("leader", "first"),
            ("leader", "second"),
            ("later", "second"),
        ]

    run(scenario())


def test_cancelled_failover_waiter_does_not_cancel_leader() -> None:
    async def scenario() -> None:
        first = candidate("first", "identity-first")
        second = candidate("second", "identity-second")
        coordinator = SearchProviderChainCoordinator()
        leader_reached_second = asyncio.Event()
        release_second = asyncio.Event()
        waiter_calls = 0

        async def leader_runner(item: TavilySearchProviderCandidate) -> str:
            if item is first:
                raise SearchProviderAttemptError(
                    SearchProviderAttemptCategory.CONNECTION_ERROR
                )
            leader_reached_second.set()
            await release_second.wait()
            return "leader-ok"

        async def waiter_runner(_item: TavilySearchProviderCandidate) -> str:
            nonlocal waiter_calls
            waiter_calls += 1
            return "waiter-ok"

        leader = asyncio.create_task(coordinator.run((first, second), leader_runner))
        await leader_reached_second.wait()
        waiter = asyncio.create_task(coordinator.run((first, second), waiter_runner))
        await asyncio.sleep(0)
        waiter.cancel("stop-waiting")
        with pytest.raises(asyncio.CancelledError) as caught:
            await waiter
        assert caught.value.args == ("stop-waiting",)
        assert waiter_calls == 0

        release_second.set()
        assert await leader == "leader-ok"
        assert coordinator.current_candidate((first, second)) is second

    run(scenario())


def test_cancelled_tavily_settlement_hands_failover_to_one_waiter() -> None:
    async def scenario() -> None:
        first = candidate("first", "identity-first")
        second = candidate("second", "identity-second")
        settlement_started = asyncio.Event()

        class BlockingUsageState:
            calls = 0

            async def get(self, _api_key: str, *, refresh: bool = False) -> TavilyUsage:
                assert refresh is True
                self.calls += 1
                if self.calls > 1:
                    return TavilyUsage(status="unavailable")
                settlement_started.set()
                await asyncio.Event().wait()
                raise AssertionError("unreachable")

        usage_state: Any = BlockingUsageState()
        coordinator = SearchProviderChainCoordinator(tavily_usage_state=usage_state)
        waiter_calls: list[str] = []

        async def leader_runner(item: TavilySearchProviderCandidate) -> str:
            assert item is first
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.CONNECTION_ERROR
            )

        async def waiter_runner(item: TavilySearchProviderCandidate) -> str:
            waiter_calls.append(item.row_id)
            return "waiter-ok"

        leader = asyncio.create_task(coordinator.run((first, second), leader_runner))
        await settlement_started.wait()
        waiter = asyncio.create_task(coordinator.run((first, second), waiter_runner))
        await asyncio.sleep(0)

        leader.cancel("client-left")
        with pytest.raises(asyncio.CancelledError) as caught:
            await leader
        assert caught.value.args == ("client-left",)

        assert await waiter == "waiter-ok"
        assert waiter_calls == ["second"]
        assert usage_state.calls == 2
        assert coordinator.current_candidate((first, second)) is second

    run(scenario())


def test_concurrent_waiter_reuses_all_unavailable_outcome() -> None:
    async def scenario() -> None:
        first = candidate("first", "identity-first")
        second = candidate("second", "identity-second")
        coordinator = SearchProviderChainCoordinator()
        release_first = asyncio.Event()
        both_first_started = asyncio.Event()
        first_calls = 0
        second_calls = 0

        async def runner(item: TavilySearchProviderCandidate) -> None:
            nonlocal first_calls, second_calls
            if item is first:
                first_calls += 1
                if first_calls == 2:
                    both_first_started.set()
                await release_first.wait()
            else:
                second_calls += 1
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.UPSTREAM_FAILURE
            )

        requests = [
            asyncio.create_task(coordinator.run((first, second), runner))
            for _ in range(2)
        ]
        await both_first_started.wait()
        release_first.set()
        results = await asyncio.gather(*requests, return_exceptions=True)

        assert all(
            isinstance(result, SearchProviderChainUnavailable) for result in results
        )
        assert all(
            result.reason is SearchProviderChainUnavailableReason.ALL_ATTEMPTS_FAILED
            for result in results
            if isinstance(result, SearchProviderChainUnavailable)
        )
        assert first_calls == 2
        assert second_calls == 1

    run(scenario())


def test_healthy_searches_remain_concurrent() -> None:
    async def scenario() -> None:
        item = candidate("current", "identity-current")
        coordinator = SearchProviderChainCoordinator()
        release = asyncio.Event()
        both_started = asyncio.Event()
        started = 0

        async def runner(_item: TavilySearchProviderCandidate) -> str:
            nonlocal started
            started += 1
            if started == 2:
                both_started.set()
            await release.wait()
            return "ok"

        requests = [
            asyncio.create_task(coordinator.run((item,), runner)) for _ in range(2)
        ]
        await asyncio.wait_for(both_started.wait(), timeout=1)
        release.set()
        assert await asyncio.gather(*requests) == ["ok", "ok"]

    run(scenario())


def test_stale_inflight_success_cannot_restore_pre_failover_current() -> None:
    async def scenario() -> None:
        first = candidate("first", "identity-first")
        second = candidate("second", "identity-second")
        coordinator = SearchProviderChainCoordinator()
        stale_started = asyncio.Event()
        release_stale = asyncio.Event()

        async def stale_runner(item: TavilySearchProviderCandidate) -> str:
            assert item is first
            stale_started.set()
            await release_stale.wait()
            return "stale-ok"

        async def switching_runner(item: TavilySearchProviderCandidate) -> str:
            if item is first:
                raise SearchProviderAttemptError(
                    SearchProviderAttemptCategory.CONNECTION_ERROR
                )
            return "replacement-ok"

        stale = asyncio.create_task(coordinator.run((first, second), stale_runner))
        await stale_started.wait()
        assert (
            await coordinator.run((first, second), switching_runner) == "replacement-ok"
        )
        assert coordinator.current_candidate((first, second)) is second

        release_stale.set()
        assert await stale == "stale-ok"
        assert coordinator.current_candidate((first, second)) is second

    run(scenario())


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("invalid local request"),
        SearchProviderRequestFailover(
            SearchProviderRequestFailoverReason.LOCAL_UNAVAILABLE
        ),
        asyncio.CancelledError("cancelled"),
    ],
)
def test_non_execution_failures_do_not_fail_over(
    failure: BaseException,
) -> None:
    first = candidate("first", "identity-first")
    second = candidate("second", "identity-second")
    calls: list[str] = []

    async def runner(item: TavilySearchProviderCandidate) -> None:
        calls.append(item.row_id)
        raise failure

    coordinator = SearchProviderChainCoordinator()
    with pytest.raises(type(failure)) as caught:
        run(coordinator.run((first, second), runner))

    assert caught.value is failure
    assert calls == ["first"]
    assert not coordinator.is_cooling(first)
    assert not coordinator.is_cooling(second)


def test_manual_selection_clears_only_selected_candidate_cooldown() -> None:
    first = candidate("first", "identity-first")
    second = candidate("second", "identity-second")
    coordinator = SearchProviderChainCoordinator()
    failure = SearchProviderAttemptError(SearchProviderAttemptCategory.UPSTREAM_FAILURE)
    coordinator.mark_failed(first, failure)
    coordinator.mark_failed(second, failure)

    coordinator.select_current(first, clear_cooldown=True)

    assert coordinator.current_candidate((first, second)) is first
    assert coordinator.is_cooling(first) is False
    assert coordinator.is_cooling(second) is True


def test_all_failed_chain_has_stable_browser_use_error() -> None:
    first = candidate("first", "identity-first")
    second = candidate("second", "identity-second")

    async def runner(_item: TavilySearchProviderCandidate) -> None:
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.UPSTREAM_FAILURE)

    with pytest.raises(SearchProviderChainUnavailable) as caught:
        run(SearchProviderChainCoordinator().run((first, second), runner))

    assert "Please consider Browser Use" in str(caught.value)
    assert "first" not in str(caught.value)
    assert "second" not in str(caught.value)


def test_candidate_key_has_exact_equality_hash_and_secret_safe_repr() -> None:
    first = search_provider_chain_state_module._CandidateKey("row", "private-identity")
    same = search_provider_chain_state_module._CandidateKey("row", "private-identity")
    changed_identity = search_provider_chain_state_module._CandidateKey(
        "row", "changed"
    )
    changed_row = search_provider_chain_state_module._CandidateKey(
        "changed-row", "private-identity"
    )

    assert first == same
    assert hash(first) == hash(same)
    assert first != changed_identity
    assert first != changed_row
    assert {first: "stored"}[same] == "stored"
    assert repr(first) == "_CandidateKey(row_id='row')"
    assert "private-identity" not in repr(first)


def test_chain_runs_in_order_once_and_short_circuits_on_success() -> None:
    candidates = (candidate("first", "a"), candidate("second", "b"))
    calls: list[str] = []

    async def runner(item: TavilySearchProviderCandidate) -> str:
        calls.append(item.row_id)
        if item.row_id == "first":
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.CONNECTION_ERROR
            )
        return "ok"

    coordinator = SearchProviderChainCoordinator()
    assert run(coordinator.run(candidates, runner)) == "ok"
    assert calls == ["first", "second"]
    assert coordinator.is_cooling(candidates[0]) is True


def test_chain_does_not_retry_duplicate_candidate_identity_in_one_request() -> None:
    item = candidate("only", "same")
    calls = 0

    async def runner(_item: TavilySearchProviderCandidate) -> None:
        nonlocal calls
        calls += 1
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)

    with pytest.raises(SearchProviderChainUnavailable) as caught:
        run(SearchProviderChainCoordinator().run((item, item), runner))

    assert (
        caught.value.reason is SearchProviderChainUnavailableReason.ALL_ATTEMPTS_FAILED
    )
    assert calls == 1


@pytest.mark.parametrize(
    ("candidates", "reason"),
    [
        ((), SearchProviderChainUnavailableReason.EMPTY_CHAIN),
        (
            (candidate("single", "identity"),),
            SearchProviderChainUnavailableReason.ALL_ATTEMPTS_FAILED,
        ),
    ],
)
def test_chain_has_bounded_terminal_reasons_for_empty_and_failed_chain(
    candidates: tuple[TavilySearchProviderCandidate, ...],
    reason: SearchProviderChainUnavailableReason,
) -> None:
    async def runner(_item: TavilySearchProviderCandidate) -> None:
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)

    with pytest.raises(SearchProviderChainUnavailable) as caught:
        run(SearchProviderChainCoordinator().run(candidates, runner))

    assert caught.value.reason is reason


def test_all_attempts_failed_locals_aware_traceback_excludes_candidate_secrets() -> (
    None
):
    first_identity = "synthetic-private-identity-a"
    second_identity = "synthetic-private-identity-b"
    first_key = "synthetic-api-key-a"
    second_key = "synthetic-api-key-b"
    raw_error = "synthetic-raw-provider-error"
    first = candidate("first", first_identity, api_key=first_key)
    second = candidate("second", second_identity, api_key=second_key)

    async def runner(item: TavilySearchProviderCandidate) -> None:
        if item is first:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.HTTP_ERROR
            ) from RuntimeError(raw_error)
        raise SearchProviderAttemptError(
            SearchProviderAttemptCategory.CONNECTION_ERROR
        ) from RuntimeError(raw_error)

    with pytest.raises(SearchProviderChainUnavailable) as caught:
        run(SearchProviderChainCoordinator().run((first, second), runner))

    assert (
        caught.value.reason is SearchProviderChainUnavailableReason.ALL_ATTEMPTS_FAILED
    )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    formatted = format_traceback_with_locals(caught.value)
    for secret in (
        first_identity,
        second_identity,
        first_key,
        second_key,
        raw_error,
    ):
        assert secret not in formatted


def test_attempt_error_cools_candidate_and_fails_over() -> None:
    clock = Clock()
    first = candidate("first", "a")
    second = candidate("second", "b")
    calls: list[str] = []

    async def runner(item: TavilySearchProviderCandidate) -> str:
        calls.append(item.row_id)
        if item is first:
            raise SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)
        return "ok"

    coordinator = SearchProviderChainCoordinator(clock=clock)
    assert run(coordinator.run((first, second), runner)) == "ok"
    assert calls == ["first", "second"]
    assert coordinator.is_cooling(first) is True
    assert (
        coordinator.cooldown_reason(first) is SearchProviderAttemptCategory.HTTP_ERROR
    )
    assert coordinator.is_cooling(second) is False


def test_all_cooling_is_distinct_and_cooldown_expires_lazily() -> None:
    clock = Clock()
    identity = "synthetic-all-cooling-identity"
    api_key = "synthetic-all-cooling-api-key"
    raw_error = "synthetic-all-cooling-raw-error"
    item = candidate("only", identity, api_key=api_key)
    coordinator = SearchProviderChainCoordinator(clock=clock)
    failure = SearchProviderAttemptError(SearchProviderAttemptCategory.CONNECTION_ERROR)
    failure.__cause__ = RuntimeError(raw_error)
    coordinator.mark_failed(item, failure)
    calls = 0

    async def runner(_item: TavilySearchProviderCandidate) -> str:
        nonlocal calls
        calls += 1
        return "recovered"

    with pytest.raises(SearchProviderChainUnavailable) as caught:
        run(coordinator.run((item,), runner))
    assert (
        caught.value.reason
        is SearchProviderChainUnavailableReason.ALL_CANDIDATES_COOLING
    )
    assert calls == 0
    formatted = format_traceback_with_locals(caught.value)
    assert identity not in formatted
    assert api_key not in formatted
    assert raw_error not in formatted

    clock.value += DEFAULT_SEARCH_PROVIDER_COOLDOWN_SECONDS
    assert coordinator.is_cooling(item) is False
    assert coordinator.cooldown_reason(item) is None
    assert run(coordinator.run((item,), runner)) == "recovered"
    assert calls == 1


def test_cooldown_survives_reorder_but_identity_change_is_fresh() -> None:
    first = candidate("first", "a")
    second = candidate("second", "b")
    changed = candidate("first", "new-a")
    calls: list[str] = []

    async def fail_first(item: TavilySearchProviderCandidate) -> str:
        calls.append(item.identity)
        if item is first:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.UPSTREAM_FAILURE
            )
        return item.identity

    coordinator = SearchProviderChainCoordinator()
    assert run(coordinator.run((first, second), fail_first)) == "b"
    calls.clear()
    assert run(coordinator.run((second, first), fail_first)) == "b"
    assert calls == ["b"]
    calls.clear()
    coordinator.select_current(changed)
    assert run(coordinator.run((changed, second), fail_first)) == "new-a"
    assert calls == ["new-a"]


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("upstream-secret-detail"),
        asyncio.CancelledError("cancel-now"),
        SearchProviderBudgetExceeded(SearchProviderBudgetReason.DEADLINE_EXCEEDED),
        MemoryError("memory-pressure"),
        SystemExit("process-exit"),
        KeyboardInterrupt("operator-interrupt"),
    ],
)
def test_untyped_budget_cancel_and_fatal_errors_propagate_without_cooldown(
    failure: BaseException,
) -> None:
    identity = "synthetic-propagated-path-identity"
    api_key = "synthetic-propagated-path-api-key"
    item = candidate("row", identity, api_key=api_key)
    coordinator = SearchProviderChainCoordinator()

    async def runner(_item: TavilySearchProviderCandidate) -> None:
        raise failure

    with pytest.raises(type(failure)) as caught:
        run(coordinator.run((item,), runner))
    assert caught.value is failure
    assert caught.value.args == failure.args
    assert coordinator.is_cooling(item) is False
    formatted = format_traceback_with_locals(caught.value)
    assert identity not in formatted
    assert api_key not in formatted


def test_quota_attempt_uses_bounded_quota_cooldown_reason() -> None:
    item = candidate("row", "identity")
    coordinator = SearchProviderChainCoordinator()

    async def runner(_item: TavilySearchProviderCandidate) -> None:
        raise SearchProviderAttemptError(
            SearchProviderAttemptCategory.HTTP_ERROR,
            quota_exhausted=True,
        )

    with pytest.raises(SearchProviderChainUnavailable):
        run(coordinator.run((item,), runner))

    assert (
        coordinator.cooldown_reason(item)
        is SearchProviderAttemptCategory.QUOTA_EXHAUSTED
    )


def test_observer_receives_only_bounded_safe_events() -> None:
    private_key = "tvly-super-secret"
    private_identity = "private-fingerprint"
    raw_error = "raw-upstream-error"
    first = candidate("first", private_identity, api_key=private_key)
    second = candidate("second", "safe-identity", api_key="another-secret")
    events: list[dict[str, str | int]] = []

    async def runner(item: TavilySearchProviderCandidate) -> str:
        if item is first:
            error = SearchProviderAttemptError(SearchProviderAttemptCategory.HTTP_ERROR)
            error.__cause__ = RuntimeError(raw_error)
            raise error
        raise SearchProviderAttemptError(SearchProviderAttemptCategory.UPSTREAM_FAILURE)

    coordinator = SearchProviderChainCoordinator(observer=events.append)
    with pytest.raises(SearchProviderChainUnavailable) as caught:
        run(coordinator.run((first, second), runner))
    assert (
        caught.value.reason is SearchProviderChainUnavailableReason.ALL_ATTEMPTS_FAILED
    )

    assert events == [
        {
            "row_id": "first",
            "provider": "tavily",
            "attempt_index": 0,
            "outcome_category": "http_error",
            "cooldown_reason": "http_error",
        },
        {
            "row_id": "second",
            "provider": "tavily",
            "attempt_index": 1,
            "outcome_category": "upstream_failure",
            "cooldown_reason": "upstream_failure",
        },
        {"final_reason": "all_attempts_failed"},
    ]
    serialized = repr(events)
    assert private_key not in serialized
    assert private_identity not in serialized
    assert raw_error not in serialized


@pytest.mark.parametrize(
    "observer_failure_type",
    [RuntimeError, asyncio.CancelledError],
)
@pytest.mark.parametrize(
    ("scenario", "expected_calls", "expected_events", "terminal_reason"),
    [
        ("success", ["first"], ["success"], None),
        (
            "cooldown_failover",
            ["first", "second"],
            ["http_error", "success"],
            None,
        ),
        (
            "empty",
            [],
            ["empty_chain"],
            SearchProviderChainUnavailableReason.EMPTY_CHAIN,
        ),
        (
            "all_cooling",
            [],
            ["cooling", "all_candidates_cooling"],
            SearchProviderChainUnavailableReason.ALL_CANDIDATES_COOLING,
        ),
        (
            "all_failed",
            ["first", "second"],
            ["http_error", "connection_error", "all_attempts_failed"],
            SearchProviderChainUnavailableReason.ALL_ATTEMPTS_FAILED,
        ),
    ],
)
def test_observer_failures_are_advisory_for_every_chain_outcome(
    observer_failure_type: type[BaseException],
    scenario: str,
    expected_calls: list[str],
    expected_events: list[str],
    terminal_reason: SearchProviderChainUnavailableReason | None,
) -> None:
    upstream_secret = "synthetic-upstream-secret"
    observer_secret = "synthetic-observer-secret"
    first = candidate("first", "a")
    second = candidate("second", "b")
    calls: list[str] = []
    events: list[str] = []

    def observer(event: dict[str, str | int]) -> None:
        events.append(str(event.get("outcome_category", event.get("final_reason"))))
        raise observer_failure_type(observer_secret)

    coordinator = SearchProviderChainCoordinator(observer=observer)
    if scenario == "all_cooling":
        coordinator.mark_failed(
            first,
            SearchProviderAttemptError(SearchProviderAttemptCategory.CONNECTION_ERROR),
        )

    candidates = () if scenario == "empty" else (first,)
    if scenario in {"cooldown_failover", "all_failed"}:
        candidates = (first, second)

    async def runner(item: TavilySearchProviderCandidate) -> str:
        calls.append(item.row_id)
        if item is first and scenario in {"cooldown_failover", "all_failed"}:
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.HTTP_ERROR
            ) from RuntimeError(upstream_secret)
        if scenario == "all_failed":
            raise SearchProviderAttemptError(
                SearchProviderAttemptCategory.CONNECTION_ERROR
            ) from RuntimeError(upstream_secret)
        return "ok"

    if terminal_reason is None:
        assert run(coordinator.run(candidates, runner)) == "ok"
    else:
        with pytest.raises(SearchProviderChainUnavailable) as caught:
            run(coordinator.run(candidates, runner))
        assert caught.value.reason is terminal_reason
        formatted = "".join(
            traceback.format_exception(
                type(caught.value), caught.value, caught.value.__traceback__
            )
        )
        assert upstream_secret not in formatted
        assert observer_secret not in formatted

    assert calls == expected_calls
    assert events == expected_events
    if scenario in {"cooldown_failover", "all_failed"}:
        assert coordinator.is_cooling(first) is True
