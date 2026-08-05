"""Ordered execution, cooldowns, budgets, and typed web-search chain errors."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Generic, TypeVar

from .search_provider_candidates import SearchProviderCandidate

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
        super().__init__(reason, "Search provider chain unavailable")


@dataclass(frozen=True, slots=True)
class _CandidateKey:
    """Exact candidate identity key with a traceback-safe representation."""

    row_id: str
    identity: str = field(repr=False)


class SearchProviderChainCoordinator:
    """Run candidates in order and retain process-local candidate cooldowns."""

    def __init__(
        self,
        *,
        cooldown_seconds: float = DEFAULT_SEARCH_PROVIDER_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        observer: _Observer | None = None,
    ) -> None:
        cooldown_seconds = float(cooldown_seconds)
        if not math.isfinite(cooldown_seconds) or cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        self._clock = clock
        self._cooldown_seconds = cooldown_seconds
        self._observer = observer
        self._last_clock = self._read_clock()
        self._cooldowns: dict[
            _CandidateKey, tuple[float, SearchProviderAttemptCategory]
        ] = {}

    def _read_clock(self) -> float:
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("clock must return a finite value")
        last_clock = getattr(self, "_last_clock", now)
        if now < last_clock:
            raise ValueError("clock must be monotonic")
        self._last_clock = now
        return now

    @staticmethod
    def _key(candidate: SearchProviderCandidate) -> _CandidateKey:
        return _CandidateKey(candidate.row_id, candidate.identity)

    def _prune(self, now: float) -> None:
        expired = [key for key, (until, _) in self._cooldowns.items() if until <= now]
        for key in expired:
            del self._cooldowns[key]

    def _cooldown_reason_at(
        self, candidate: SearchProviderCandidate, now: float
    ) -> SearchProviderAttemptCategory | None:
        self._prune(now)
        state = self._cooldowns.get(self._key(candidate))
        return state[1] if state is not None else None

    def is_cooling(self, candidate: SearchProviderCandidate) -> bool:
        """Return whether the candidate's current identity is cooling."""
        return self._cooldown_reason_at(candidate, self._read_clock()) is not None

    def cooldown_reason(
        self, candidate: SearchProviderCandidate
    ) -> SearchProviderAttemptCategory | None:
        """Return the bounded active cooldown reason, if any."""
        return self._cooldown_reason_at(candidate, self._read_clock())

    def mark_failed(
        self,
        candidate: SearchProviderCandidate,
        failure: SearchProviderAttemptError,
    ) -> SearchProviderAttemptCategory:
        """Start a cooldown for one stable row and process-local identity."""
        now = self._read_clock()
        reason = (
            SearchProviderAttemptCategory.QUOTA_EXHAUSTED
            if failure.quota_exhausted
            else failure.category
        )
        until = now + self._cooldown_seconds
        if not math.isfinite(until):
            raise ValueError("cooldown deadline must be finite")
        self._prune(now)
        self._cooldowns[self._key(candidate)] = (until, reason)
        return reason

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

    async def run(
        self,
        candidates: Sequence[_CandidateT],
        runner: Callable[[_CandidateT], Awaitable[_ResultT]],
    ) -> _ResultT:
        """Try each non-cooling candidate once and return the first success."""
        if not candidates:
            reason = SearchProviderChainUnavailableReason.EMPTY_CHAIN
            self._observe({"final_reason": reason.value})
            raise SearchProviderChainUnavailable(reason)

        attempted = False
        seen: set[_CandidateKey] = set()
        for attempt_index, candidate in enumerate(candidates):
            key = self._key(candidate)
            if key in seen:
                continue
            seen.add(key)
            cooling_reason = self._cooldown_reason_at(candidate, self._read_clock())
            if cooling_reason is not None:
                self._observe_candidate(
                    candidate,
                    attempt_index,
                    "cooling",
                    cooldown_reason=cooling_reason,
                )
                continue
            attempted = True
            attempt_category: SearchProviderAttemptCategory | None = None
            quota_exhausted = False
            request_failover_reason: SearchProviderRequestFailoverReason | None = None
            try:
                result = await runner(candidate)
            except SearchProviderAttemptError as error:
                attempt_category = error.category
                quota_exhausted = error.quota_exhausted
            except SearchProviderRequestFailover as error:
                request_failover_reason = error.reason
            else:
                self._observe_candidate(candidate, attempt_index, "success")
                return result

            if attempt_category is not None:
                failure = SearchProviderAttemptError(
                    attempt_category,
                    quota_exhausted=quota_exhausted,
                )
                cooling_reason = self.mark_failed(candidate, failure)
                self._observe_candidate(
                    candidate,
                    attempt_index,
                    attempt_category,
                    cooldown_reason=cooling_reason,
                )
            else:
                assert request_failover_reason is not None
                self._observe_candidate(
                    candidate,
                    attempt_index,
                    request_failover_reason,
                )

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
