"""Ordered execution, cooldowns, budgets, and typed web-search chain errors."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from enum import StrEnum
from typing import Any, Generic, TypeVar, cast

from .search_provider_candidates import SearchProviderCandidate
from .search_provider_chain_state import (
    DEFAULT_SEARCH_PROVIDER_STATE_CAPACITY,
    SearchProviderStateCapacityUnavailable as SearchProviderStateCapacityUnavailable,
    _SearchProviderChainState,
)

SEARCH_PROVIDER_REQUEST_TIMEOUT_SECONDS = 300.0
MAX_SEARCH_PROVIDER_EXTERNAL_CALLS = 32
DEFAULT_SEARCH_PROVIDER_COOLDOWN_SECONDS = 3600.0

_ResultT = TypeVar("_ResultT")
_ReasonT = TypeVar("_ReasonT", bound=StrEnum)
_CandidateT = TypeVar("_CandidateT", bound=SearchProviderCandidate)
_AsyncOperation = Callable[[], Awaitable[_ResultT]]
_ObserverEvent = dict[str, str | int]
_Observer = Callable[[_ObserverEvent], None]
_DETACHED_OPERATION_FUTURES: set[asyncio.Future[Any]] = set()
_CurrentProviderValue = SearchProviderCandidate | str | tuple[str, str] | None
_CurrentProviderSource = Callable[[], _CurrentProviderValue] | _CurrentProviderValue
_CurrentProviderRecorder = Callable[[SearchProviderCandidate], object]


async def _invoke_operation(operation: _AsyncOperation[_ResultT]) -> _ResultT:
    return await operation()


def _observe_future(future: asyncio.Future[_ResultT]) -> None:
    with suppress(asyncio.CancelledError):
        future.exception()


def _observe_detached_future(future: asyncio.Future[Any]) -> None:
    try:
        _observe_future(future)
    finally:
        _DETACHED_OPERATION_FUTURES.discard(future)


def _detach_future(future: asyncio.Future[_ResultT]) -> None:
    _DETACHED_OPERATION_FUTURES.add(future)
    future.add_done_callback(_observe_detached_future)


class SearchProviderBudgetReason(StrEnum):
    """Bounded reasons why a request-local search budget was exhausted."""

    DEADLINE_EXCEEDED = "deadline_exceeded"
    EXTERNAL_CALL_LIMIT_EXCEEDED = "external_call_limit_exceeded"


class SearchProviderAttemptCategory(StrEnum):
    """Bounded candidate-health failure categories."""

    CONNECTION_ERROR = "connection_error"
    HTTP_ERROR = "http_error"
    INVALID_RESPONSE = "invalid_response"
    UPSTREAM_FAILURE = "upstream_failure"
    QUOTA_EXHAUSTED = "quota_exhausted"


class SearchProviderRequestFailoverReason(StrEnum):
    """Bounded request-local reasons for trying the next candidate."""

    REQUEST_REJECTED = "request_rejected"
    LOCAL_UNAVAILABLE = "local_unavailable"


class SearchProviderChainUnavailableReason(StrEnum):
    """Bounded terminal outcomes for an unavailable provider chain."""

    EMPTY_CHAIN = "empty_chain"
    ALL_CANDIDATES_COOLING = "all_candidates_cooling"
    ALL_ATTEMPTS_FAILED = "all_attempts_failed"


class _ReasonedError(RuntimeError, Generic[_ReasonT]):
    def __init__(self, reason: _ReasonT, message: str) -> None:
        self._reason = reason
        super().__init__(message)

    @property
    def reason(self) -> _ReasonT:
        """Return the bounded failure reason without raw error details."""
        return self._reason


class SearchProviderBudgetExceeded(_ReasonedError[SearchProviderBudgetReason]):
    """Raised when a request-local search budget is exhausted."""

    def __init__(self, reason: SearchProviderBudgetReason) -> None:
        super().__init__(reason, "Search provider request budget exceeded")


class SearchProviderAttemptError(_ReasonedError[SearchProviderAttemptCategory]):
    """A typed provider failure that cools the candidate and permits failover."""

    def __init__(
        self,
        category: SearchProviderAttemptCategory,
        *,
        quota_exhausted: bool = False,
    ) -> None:
        self._quota_exhausted = bool(quota_exhausted)
        super().__init__(category, "Search provider attempt failed")

    @property
    def category(self) -> SearchProviderAttemptCategory:
        """Return the bounded candidate-health failure category."""
        return self.reason

    @property
    def quota_exhausted(self) -> bool:
        """Return whether the candidate reported bounded quota exhaustion."""
        return self._quota_exhausted


class SearchProviderRequestFailover(
    _ReasonedError[SearchProviderRequestFailoverReason]
):
    """A typed request-local failure that permits failover."""

    def __init__(self, reason: SearchProviderRequestFailoverReason) -> None:
        super().__init__(reason, "Search provider request could not use this candidate")


class SearchProviderChainUnavailable(
    _ReasonedError[SearchProviderChainUnavailableReason]
):
    """Raised when no candidate in the ordered search chain can succeed."""

    def __init__(self, reason: SearchProviderChainUnavailableReason) -> None:
        super().__init__(reason, "Search unavailable; Please consider Browser Use")


class SearchProviderChainCoordinator:
    """Run one ordered search request with small process-local row state.

    ``current_provider`` may be a row id, candidate, or zero-argument getter.
    ``record_current`` is an optional state seam called only after a candidate
    succeeds.  The coordinator intentionally keeps no reservation, waiter,
    cohort, or generation state: one request owns one immutable circular pass.
    """

    def __init__(
        self,
        *,
        cooldown_seconds: float = DEFAULT_SEARCH_PROVIDER_COOLDOWN_SECONDS,
        state_capacity: int = DEFAULT_SEARCH_PROVIDER_STATE_CAPACITY,
        clock: Callable[[], float] = time.monotonic,
        observer: _Observer | None = None,
        current_provider: _CurrentProviderSource = None,
        record_current: _CurrentProviderRecorder | None = None,
        on_success: _CurrentProviderRecorder | None = None,
    ) -> None:
        if record_current is not None and on_success is not None:
            raise ValueError("record_current and on_success are mutually exclusive")
        self._observer = observer
        self._state = _SearchProviderChainState[SearchProviderAttemptCategory](
            cooldown_seconds=cooldown_seconds,
            capacity=state_capacity,
            clock=clock,
        )
        self._current_provider = current_provider
        self._record_current = record_current or on_success

    def is_cooling(self, candidate: SearchProviderCandidate) -> bool:
        """Return whether the candidate's current identity is cooling."""
        return self._state.cooldown_reason(candidate) is not None

    def cooldown_reason(
        self, candidate: SearchProviderCandidate
    ) -> SearchProviderAttemptCategory | None:
        """Return the bounded active cooldown reason, if any."""
        return self._state.cooldown_reason(candidate)

    def mark_failed(
        self,
        candidate: SearchProviderCandidate,
        failure: SearchProviderAttemptError,
    ) -> SearchProviderAttemptCategory:
        """Start a cooldown for one stable row and process-local identity."""
        reason = (
            SearchProviderAttemptCategory.QUOTA_EXHAUSTED
            if failure.quota_exhausted
            else failure.category
        )
        return self._state.mark_failed(candidate, reason)

    def clear_cooldown_from_health_evidence(
        self,
        candidate: SearchProviderCandidate,
        *,
        reason: SearchProviderAttemptCategory,
        evidence_started_at: float | None,
    ) -> bool:
        """Clear a matching quota cooldown using newer monotonic evidence."""
        return self._state.clear_cooldown_from_health_evidence(
            candidate,
            reason=reason,
            evidence_started_at=evidence_started_at,
            quota_reason=SearchProviderAttemptCategory.QUOTA_EXHAUSTED,
        )

    def _observe(self, event: _ObserverEvent) -> None:
        """Notify the advisory observer without surrendering chain ownership."""
        if self._observer is None:
            return
        try:
            self._observer(event)
        except asyncio.CancelledError:
            return
        except MemoryError:
            raise
        except Exception:
            return

    def _observe_candidate(
        self,
        candidate: SearchProviderCandidate,
        attempt_index: int,
        outcome: StrEnum | str,
        *,
        cooldown_reason: SearchProviderAttemptCategory | None = None,
    ) -> None:
        event: _ObserverEvent = {
            "row_id": candidate.row_id,
            "provider": candidate.provider,
            "attempt_index": attempt_index,
            "outcome_category": str(outcome),
        }
        if cooldown_reason is not None:
            event["cooldown_reason"] = cooldown_reason.value
        self._observe(event)

    def _observe_candidate_safely(
        self,
        candidate: SearchProviderCandidate,
        attempt_index: int,
        outcome: StrEnum | str,
        *,
        cooldown_reason: SearchProviderAttemptCategory | None = None,
    ) -> None:
        """Keep fatal observer errors independent of provider failure context."""
        try:
            self._observe_candidate(
                candidate,
                attempt_index,
                outcome,
                cooldown_reason=cooldown_reason,
            )
        except BaseException as error:
            raise error from None

    def _resolve_current_index(self, candidates: tuple[_CandidateT, ...]) -> int:
        source = self._current_provider
        current = (
            cast(Callable[[], _CurrentProviderValue], source)()
            if callable(source)
            else source
        )
        if current is None:
            return 0
        if isinstance(current, str):
            return next(
                (
                    index
                    for index, item in enumerate(candidates)
                    if item.row_id == current
                ),
                0,
            )
        if isinstance(current, tuple) and len(current) == 2:
            row_id, identity = current
            return next(
                (
                    index
                    for index, item in enumerate(candidates)
                    if item.row_id == row_id and item.identity == identity
                ),
                0,
            )
        return next(
            (
                index
                for index, item in enumerate(candidates)
                if item is current
                or (
                    getattr(current, "row_id", None) == item.row_id
                    and getattr(current, "identity", None) == item.identity
                )
            ),
            0,
        )

    def _record_success(self, candidate: _CandidateT) -> None:
        if self._record_current is not None:
            self._record_current(candidate)

    async def run(
        self,
        candidates: Sequence[_CandidateT],
        runner: Callable[[_CandidateT], Awaitable[_ResultT]],
    ) -> _ResultT:
        """Try each non-cooling candidate once and return the first success."""
        candidate_snapshot = tuple(candidates)
        if not candidate_snapshot:
            reason = SearchProviderChainUnavailableReason.EMPTY_CHAIN
            self._observe({"final_reason": reason.value})
            raise SearchProviderChainUnavailable(reason)
        start = self._resolve_current_index(candidate_snapshot)
        ordered = candidate_snapshot[start:] + candidate_snapshot[:start]
        attempted = False
        seen_rows: set[str] = set()
        for attempt_index, candidate in enumerate(ordered):
            if candidate.row_id in seen_rows:
                continue
            seen_rows.add(candidate.row_id)
            cooling_reason = self._state.cooldown_reason(candidate)
            if cooling_reason is not None:
                self._observe_candidate_safely(
                    candidate,
                    attempt_index,
                    "cooling",
                    cooldown_reason=cooling_reason,
                )
                continue
            attempted = True
            try:
                result = await runner(candidate)
            except SearchProviderAttemptError as error:
                try:
                    reason = self.mark_failed(candidate, error)
                except BaseException as settlement_error:
                    raise settlement_error from None
                self._observe_candidate_safely(
                    candidate,
                    attempt_index,
                    error.category,
                    cooldown_reason=reason,
                )
                continue
            except SearchProviderRequestFailover:
                self._observe_candidate_safely(
                    candidate,
                    attempt_index,
                    "request_rejected",
                )
                raise
            else:
                self._record_success(candidate)
                self._observe_candidate_safely(candidate, attempt_index, "success")
                return result

        reason = (
            SearchProviderChainUnavailableReason.ALL_ATTEMPTS_FAILED
            if attempted
            else SearchProviderChainUnavailableReason.ALL_CANDIDATES_COOLING
        )
        self._observe({"final_reason": reason.value})
        raise SearchProviderChainUnavailable(reason)


class SearchProviderRequestBudget:
    """One request's frozen deadline and external-call allowance."""

    def __init__(
        self,
        *,
        timeout_seconds: float = SEARCH_PROVIDER_REQUEST_TIMEOUT_SECONDS,
        max_external_calls: int = MAX_SEARCH_PROVIDER_EXTERNAL_CALLS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        timeout_seconds = float(timeout_seconds)
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        valid_limit = isinstance(max_external_calls, int) and not isinstance(
            max_external_calls, bool
        )
        if not valid_limit or max_external_calls <= 0:
            raise ValueError("max_external_calls must be a positive integer")
        self._clock = clock
        self._timeout_seconds = timeout_seconds
        self._max_external_calls = max_external_calls
        self._started_at = float(clock())
        if not math.isfinite(self._started_at):
            raise ValueError("clock must return a finite value")
        self._last_clock = self._started_at
        self._deadline = self._started_at + self._timeout_seconds
        if not math.isfinite(self._deadline):
            raise ValueError("deadline must be finite")
        self._external_calls = 0

    @property
    def deadline(self) -> float:
        """Return the absolute monotonic deadline frozen at construction."""
        return self._deadline

    @property
    def external_calls(self) -> int:
        """Return the number of admitted external calls."""
        return self._external_calls

    def summary(
        self, reason: SearchProviderBudgetReason | None = None
    ) -> dict[str, str | int | float | None]:
        """Return bounded, identity-free request budget diagnostics."""
        try:
            now = self._read_clock()
        except SearchProviderBudgetExceeded:
            now = self._last_clock
        elapsed = now - self._started_at
        if not math.isfinite(elapsed):
            elapsed = self._timeout_seconds
        return {
            "reason": reason.value if reason is not None else None,
            "external_calls": self._external_calls,
            "external_call_limit": self._max_external_calls,
            "elapsed_seconds": max(0.0, elapsed),
            "deadline_seconds": self._timeout_seconds,
        }

    def _read_clock(self) -> float:
        now = float(self._clock())
        if not math.isfinite(now) or now < self._last_clock:
            raise SearchProviderBudgetExceeded(
                SearchProviderBudgetReason.DEADLINE_EXCEEDED
            )
        self._last_clock = now
        return now

    def _remaining(self) -> float:
        remaining = self._deadline - self._read_clock()
        if remaining <= 0:
            raise SearchProviderBudgetExceeded(
                SearchProviderBudgetReason.DEADLINE_EXCEEDED
            )
        return remaining

    async def _run_with_timeout(
        self, operation: _AsyncOperation[_ResultT], remaining: float
    ) -> _ResultT:
        operation_future = asyncio.ensure_future(_invoke_operation(operation))
        try:
            done, _ = await asyncio.wait({operation_future}, timeout=remaining)
        except asyncio.CancelledError:
            operation_future.cancel()
            _detach_future(operation_future)
            raise
        if operation_future in done:
            try:
                self._remaining()
            except BaseException:
                _observe_future(operation_future)
                raise
            return operation_future.result()
        operation_future.cancel()
        _detach_future(operation_future)
        raise SearchProviderBudgetExceeded(SearchProviderBudgetReason.DEADLINE_EXCEEDED)

    async def run(self, operation: _AsyncOperation[_ResultT]) -> _ResultT:
        """Run an operation within the shared deadline without charging a call."""
        return await self._run_with_timeout(operation, self._remaining())

    async def run_external_call(self, operation: _AsyncOperation[_ResultT]) -> _ResultT:
        """Atomically charge one external call, then reuse the shared deadline."""
        remaining = self._remaining()
        if self._external_calls >= self._max_external_calls:
            raise SearchProviderBudgetExceeded(
                SearchProviderBudgetReason.EXTERNAL_CALL_LIMIT_EXCEEDED
            )
        self._external_calls += 1
        return await self._run_with_timeout(operation, remaining)
