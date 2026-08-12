"""Ordered execution, cooldowns, budgets, and typed web-search chain errors."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from .search_provider_candidates import (
    SearchProviderCandidate,
    TavilySearchProviderCandidate,
)
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

if TYPE_CHECKING:
    from codex_rosetta.observability.persistence import PersistenceManager

    from .search_usage import TavilyUsage, TavilyUsageState


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


_PendingProviderFailure = tuple[
    SearchProviderCandidate, SearchProviderAttemptError, int
]


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
    succeeds. Provider failures are coordinated within one process so one
    request advances the chain while affected concurrent requests wait.
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
        persistence: PersistenceManager | None = None,
        tavily_usage_state: TavilyUsageState | None = None,
        wall_clock: Callable[[], float] = time.time,
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
        self._persistence = persistence
        self._tavily_usage_state = tavily_usage_state
        self._wall_clock = wall_clock
        self._process_current: tuple[str, str] | None = None
        self._process_quota: dict[tuple[str, str], float] = {}
        self._failover_condition = asyncio.Condition()
        self._failover_generation = 0
        self._failover_active = False
        self._failover_orphaned = False
        self._failover_pending_failure: _PendingProviderFailure | None = None
        self._failover_unavailable: SearchProviderChainUnavailableReason | None = None

    def _load_current(self) -> _CurrentProviderValue:
        if self._current_provider is not None:
            source = self._current_provider
            return (
                cast(Callable[[], _CurrentProviderValue], source)()
                if callable(source)
                else source
            )
        if self._persistence is not None:
            return self._persistence.load_current_search_provider()
        return self._process_current

    def select_current(
        self,
        candidate: SearchProviderCandidate,
        *,
        clear_cooldown: bool = False,
    ) -> None:
        """Record a manually or automatically selected current provider row."""
        if clear_cooldown:
            self._state.clear(candidate)
        if self._record_current is not None:
            self._record_current(candidate)
            return
        if self._persistence is not None:
            self._persistence.set_current_search_provider(
                candidate.row_id, self._persistence_binding(candidate)
            )
        else:
            self._process_current = (candidate.row_id, candidate.identity)

    @staticmethod
    def _persistence_binding(candidate: SearchProviderCandidate) -> str:
        return getattr(candidate, "_persistence_binding", "") or candidate.identity

    def _quota_check_at(self, candidate: SearchProviderCandidate) -> float | None:
        if self._persistence is not None:
            return self._persistence.load_search_provider_quota_check(
                candidate.row_id, self._persistence_binding(candidate)
            )
        return self._process_quota.get((candidate.row_id, candidate.identity))

    def is_quota_exhausted(self, candidate: SearchProviderCandidate) -> bool:
        """Return whether a zero-credit exclusion exists for this identity."""
        return self._quota_check_at(candidate) is not None

    def apply_tavily_usage(
        self, candidate: TavilySearchProviderCandidate, usage: TavilyUsage
    ) -> bool | None:
        """Apply one safe Tavily usage sample to persistent routing state."""
        available = usage.available_credits if usage.status == "ok" else None
        key = (
            candidate.row_id,
            self._persistence_binding(candidate)
            if self._persistence is not None
            else candidate.identity,
        )
        if available == 0:
            self._defer_quota_check(candidate)
            return True
        if available is not None and available > 0:
            if self._persistence is not None:
                self._persistence.clear_search_provider_quota(*key)
            else:
                self._process_quota.pop(key, None)
            return False
        return None

    def _defer_quota_check(self, candidate: SearchProviderCandidate) -> None:
        key = (
            candidate.row_id,
            self._persistence_binding(candidate)
            if self._persistence is not None
            else candidate.identity,
        )
        next_check_at = self._wall_clock() + DEFAULT_SEARCH_PROVIDER_COOLDOWN_SECONDS
        if self._persistence is not None:
            self._persistence.set_search_provider_quota_exhausted(*key, next_check_at)
        else:
            self._process_quota[key] = next_check_at

    async def _refresh_tavily_quota(
        self, candidate: TavilySearchProviderCandidate
    ) -> bool | None:
        if self._tavily_usage_state is None:
            return None
        try:
            usage = await self._tavily_usage_state.get(candidate.api_key, refresh=True)
        except asyncio.CancelledError:
            raise
        except MemoryError:
            raise
        except Exception:
            return None
        return self.apply_tavily_usage(candidate, usage)

    async def _quota_allows_attempt(self, candidate: _CandidateT) -> bool:
        next_check_at = self._quota_check_at(candidate)
        if next_check_at is None:
            return True
        if self._wall_clock() < next_check_at:
            return False
        if not isinstance(candidate, TavilySearchProviderCandidate):
            return False
        exhausted = await self._refresh_tavily_quota(candidate)
        if exhausted is False:
            return True
        if exhausted is None:
            self._defer_quota_check(candidate)
        return False

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

    def _resolve_current_index(self, candidates: tuple[_CandidateT, ...]) -> int:
        current = self._load_current()
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
                    if item.row_id == row_id
                    and (
                        self._persistence_binding(item)
                        if self._persistence is not None
                        and self._current_provider is None
                        else item.identity
                    )
                    == identity
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

    def current_candidate(
        self, candidates: Sequence[_CandidateT]
    ) -> _CandidateT | None:
        """Return the configured current candidate without changing chain state."""
        candidate_snapshot = tuple(candidates)
        if not candidate_snapshot:
            return None
        return candidate_snapshot[self._resolve_current_index(candidate_snapshot)]

    async def _await_active_failover(
        self,
    ) -> tuple[
        int,
        SearchProviderChainUnavailableReason | None,
        bool,
        bool,
        _PendingProviderFailure | None,
    ]:
        waited = False
        async with self._failover_condition:
            while self._failover_active:
                waited = True
                if self._failover_orphaned:
                    self._failover_orphaned = False
                    pending_failure = self._failover_pending_failure
                    self._failover_pending_failure = None
                    return (
                        self._failover_generation,
                        None,
                        waited,
                        True,
                        pending_failure,
                    )
                await self._failover_condition.wait()
            return (
                self._failover_generation,
                self._failover_unavailable,
                waited,
                False,
                None,
            )

    async def _claim_failover(
        self, observed_generation: int
    ) -> tuple[
        bool,
        int,
        SearchProviderChainUnavailableReason | None,
        _PendingProviderFailure | None,
    ]:
        async with self._failover_condition:
            while self._failover_active:
                if self._failover_orphaned:
                    self._failover_orphaned = False
                    pending_failure = self._failover_pending_failure
                    self._failover_pending_failure = None
                    return True, self._failover_generation, None, pending_failure
                await self._failover_condition.wait()
            if self._failover_generation != observed_generation:
                return (
                    False,
                    self._failover_generation,
                    self._failover_unavailable,
                    None,
                )
            self._failover_generation += 1
            self._failover_active = True
            self._failover_orphaned = False
            self._failover_pending_failure = None
            self._failover_unavailable = None
            return True, self._failover_generation, None, None

    async def _publish_failover(
        self, unavailable: SearchProviderChainUnavailableReason | None
    ) -> None:
        async with self._failover_condition:
            self._failover_unavailable = unavailable
            self._failover_active = False
            self._failover_orphaned = False
            self._failover_pending_failure = None
            self._failover_condition.notify_all()

    async def _handoff_failover(
        self, pending_failure: _PendingProviderFailure | None
    ) -> None:
        async with self._failover_condition:
            self._failover_orphaned = True
            self._failover_pending_failure = pending_failure
            self._failover_condition.notify_all()

    def _record_success(
        self,
        candidate: _CandidateT,
        *,
        observed_generation: int,
        failover_leader: bool,
    ) -> None:
        if failover_leader or observed_generation == self._failover_generation:
            self.select_current(candidate)

    async def _candidate_is_eligible(
        self, candidate: _CandidateT, attempt_index: int
    ) -> bool:
        if not await self._quota_allows_attempt(candidate):
            self._observe_candidate(
                candidate,
                attempt_index,
                "quota_exhausted",
                cooldown_reason=SearchProviderAttemptCategory.QUOTA_EXHAUSTED,
            )
            return False
        cooling_reason = self._state.cooldown_reason(candidate)
        if cooling_reason is None:
            return True
        self._observe_candidate(
            candidate,
            attempt_index,
            "cooling",
            cooldown_reason=cooling_reason,
        )
        return False

    async def _settle_failure(
        self,
        candidate: SearchProviderCandidate,
        error: SearchProviderAttemptError,
        attempt_index: int,
    ) -> None:
        try:
            quota_exhausted = (
                await self._refresh_tavily_quota(candidate)
                if isinstance(candidate, TavilySearchProviderCandidate)
                else None
            )
            reason = (
                SearchProviderAttemptCategory.QUOTA_EXHAUSTED
                if quota_exhausted is True
                else self.mark_failed(candidate, error)
            )
        except BaseException as settlement_error:
            raise settlement_error from None
        self._observe_candidate(
            candidate,
            attempt_index,
            error.category,
            cooldown_reason=reason,
        )

    async def _settle_pending_failure(
        self,
        pending_failure: _PendingProviderFailure | None,
        seen_rows: set[str],
    ) -> None:
        if pending_failure is None:
            return
        candidate, error, attempt_index = pending_failure
        seen_rows.add(candidate.row_id)
        await self._settle_failure(candidate, error, attempt_index)

    def _unavailable_reason(
        self, *, attempted: bool
    ) -> SearchProviderChainUnavailableReason:
        return (
            SearchProviderChainUnavailableReason.ALL_ATTEMPTS_FAILED
            if attempted
            else SearchProviderChainUnavailableReason.ALL_CANDIDATES_COOLING
        )

    def _raise_unavailable(self, reason: SearchProviderChainUnavailableReason) -> None:
        self._observe({"final_reason": reason.value})
        raise SearchProviderChainUnavailable(reason)

    async def _attempt_candidate(
        self,
        candidate: _CandidateT,
        attempt_index: int,
        runner: Callable[[_CandidateT], Awaitable[_ResultT]],
    ) -> tuple[_ResultT | None, SearchProviderAttemptError | None]:
        try:
            return await runner(candidate), None
        except SearchProviderAttemptError as error:
            return None, error
        except SearchProviderRequestFailover:
            self._observe_candidate(candidate, attempt_index, "request_rejected")
            raise

    async def run(
        self,
        candidates: Sequence[_CandidateT],
        runner: Callable[[_CandidateT], Awaitable[_ResultT]],
    ) -> _ResultT:
        """Try each non-cooling candidate once and return the first success."""
        candidate_snapshot = tuple(candidates)
        if not candidate_snapshot:
            self._raise_unavailable(SearchProviderChainUnavailableReason.EMPTY_CHAIN)
        (
            generation,
            unavailable,
            waited,
            failover_leader,
            pending_failure,
        ) = await self._await_active_failover()
        if waited and unavailable is not None:
            self._raise_unavailable(unavailable)
        attempted = pending_failure is not None
        seen_rows: set[str] = set()
        try:
            await self._settle_pending_failure(pending_failure, seen_rows)
            pending_failure = None
            while True:
                start = self._resolve_current_index(candidate_snapshot)
                ordered = candidate_snapshot[start:] + candidate_snapshot[:start]
                restart_after_wait = False
                for attempt_index, candidate in enumerate(ordered):
                    if candidate.row_id in seen_rows:
                        continue
                    seen_rows.add(candidate.row_id)
                    if not await self._candidate_is_eligible(candidate, attempt_index):
                        continue
                    attempted = True
                    result, failure = await self._attempt_candidate(
                        candidate, attempt_index, runner
                    )
                    if failure is None:
                        self._record_success(
                            candidate,
                            observed_generation=generation,
                            failover_leader=failover_leader,
                        )
                        self._observe_candidate(candidate, attempt_index, "success")
                        if failover_leader:
                            await self._publish_failover(None)
                            failover_leader = False
                        return cast(_ResultT, result)
                    if failover_leader:
                        pending_failure = (candidate, failure, attempt_index)
                        await self._settle_failure(candidate, failure, attempt_index)
                        pending_failure = None
                        continue
                    (
                        failover_leader,
                        generation,
                        unavailable,
                        inherited_failure,
                    ) = await self._claim_failover(generation)
                    if unavailable is not None:
                        self._raise_unavailable(unavailable)
                    if failover_leader:
                        pending_failure = inherited_failure or (
                            candidate,
                            failure,
                            attempt_index,
                        )
                        inherited_candidate, inherited_error, inherited_index = (
                            pending_failure
                        )
                        seen_rows.add(inherited_candidate.row_id)
                        await self._settle_failure(
                            inherited_candidate,
                            inherited_error,
                            inherited_index,
                        )
                        pending_failure = None
                    else:
                        restart_after_wait = True
                        break

                if restart_after_wait:
                    continue
                reason = self._unavailable_reason(attempted=attempted)
                if failover_leader:
                    await self._publish_failover(reason)
                    failover_leader = False
                self._raise_unavailable(reason)
        finally:
            if failover_leader:
                await self._handoff_failover(pending_failure)


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
