import asyncio
import gc
import math
import time
import weakref
from collections.abc import Awaitable
from typing import Any

import pytest

from codex_rosetta.gateway import search_provider_chain as search_provider_chain_module
from codex_rosetta.gateway.search_provider_chain import (
    MAX_SEARCH_PROVIDER_EXTERNAL_CALLS,
    SEARCH_PROVIDER_REQUEST_TIMEOUT_SECONDS,
    SearchProviderAttemptCategory,
    SearchProviderAttemptError,
    SearchProviderBudgetExceeded,
    SearchProviderBudgetReason,
    SearchProviderChainUnavailable,
    SearchProviderChainUnavailableReason,
    SearchProviderRequestBudget,
    SearchProviderRequestFailover,
    SearchProviderRequestFailoverReason,
)


class Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.value


def run(coro: Awaitable[Any]) -> Any:
    return asyncio.run(coro)


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
            "Search provider chain unavailable",
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
