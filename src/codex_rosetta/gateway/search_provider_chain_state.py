"""Private concurrency and cooldown state for the search provider chain."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar

from .search_provider_candidates import SearchProviderCandidate

MAX_ACTIVE_ATTEMPTS_PER_CANDIDATE = 4
DEFAULT_SEARCH_PROVIDER_STATE_CAPACITY = 256

_ReasonT = TypeVar("_ReasonT", bound=StrEnum)


@dataclass(frozen=True, slots=True)
class _CandidateKey:
    """Exact candidate identity key with a traceback-safe representation."""

    row_id: str
    identity: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Reservation:
    """Opaque, idempotently releasable admission token."""

    token: int
    key: _CandidateKey
    generation: int


@dataclass(frozen=True, slots=True)
class _ChainProtection:
    """Opaque, idempotently releasable active-chain protection token."""

    token: int


@dataclass(frozen=True, slots=True)
class _CapacityWaiter:
    """One waiter whose future belongs exclusively to its event loop."""

    token: int
    loop: asyncio.AbstractEventLoop = field(repr=False)
    future: asyncio.Future[None] = field(repr=False)


@dataclass(frozen=True, slots=True)
class _ReserveInstruction(Generic[_ReasonT]):
    """One lock-owned admission, cooldown, or capacity-wait instruction."""

    reservation: _Reservation | None = None
    cooling_reason: _ReasonT | None = None
    waiter: _CapacityWaiter | None = None
    timeout: float | None = None


@dataclass(slots=True)
class _AttemptCohort(Generic[_ReasonT]):
    active: int = 0
    succeeded: bool = False
    pending_failure_reason: _ReasonT | None = None


@dataclass(slots=True)
class _CandidateState(Generic[_ReasonT]):
    cooldown_until: float | None = None
    cooldown_started_at: float | None = None
    cooldown_reason: _ReasonT | None = None
    cooldown_generation: int | None = None
    cooldown_order: int = 0
    inflight: int = 0
    open_generation: int | None = None
    latest_success_generation: int | None = None
    cohorts: dict[int, _AttemptCohort[_ReasonT]] = field(default_factory=dict)
    suppressed_pending_generations: set[int] = field(default_factory=set)


class SearchProviderStateCapacityUnavailable(RuntimeError):
    """Raised when synchronous cooldown storage has no safe capacity."""

    def __init__(self) -> None:
        super().__init__("Search provider state capacity unavailable")


def _wake_waiter(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)


class _SearchProviderChainState(Generic[_ReasonT]):
    """Own bounded cooldown and admission state behind one lock."""

    def __init__(
        self,
        *,
        cooldown_seconds: float,
        capacity: int = DEFAULT_SEARCH_PROVIDER_STATE_CAPACITY,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        cooldown_seconds = float(cooldown_seconds)
        if not math.isfinite(cooldown_seconds) or cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        valid_capacity = isinstance(capacity, int) and not isinstance(capacity, bool)
        if not valid_capacity or capacity <= 0:
            raise ValueError("state_capacity must be a positive integer")

        started_at = float(clock())
        if not math.isfinite(started_at):
            raise ValueError("clock must return a finite value")

        self._clock = clock
        self._cooldown_seconds = cooldown_seconds
        self._capacity = capacity
        self._last_clock = started_at
        self._lock = threading.Lock()
        self._entries: dict[_CandidateKey, _CandidateState[_ReasonT]] = {}
        self._reservations: dict[int, _Reservation] = {}
        self._protections: dict[int, frozenset[_CandidateKey]] = {}
        self._protection_counts: dict[_CandidateKey, int] = {}
        self._waiters: dict[int, _CapacityWaiter] = {}
        self._next_reservation = 0
        self._next_generation = 0
        self._next_protection = 0
        self._next_waiter = 0
        self._next_cooldown_order = 0

    @staticmethod
    def key(candidate: SearchProviderCandidate) -> _CandidateKey:
        """Return the secret-safe exact identity key for a candidate."""
        return _CandidateKey(candidate.row_id, candidate.identity)

    def _read_clock_locked(self) -> float:
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("clock must return a finite value")
        if now < self._last_clock:
            raise ValueError("clock must be monotonic")
        self._last_clock = now
        return now

    def _notify_waiters_locked(self) -> None:
        waiters = tuple(self._waiters.values())
        self._waiters.clear()
        for waiter in waiters:
            try:
                waiter.loop.call_soon_threadsafe(_wake_waiter, waiter.future)
            except RuntimeError:
                # A waiter's loop may close concurrently with a state change.
                continue

    def protect(
        self, candidates: Iterable[SearchProviderCandidate]
    ) -> _ChainProtection:
        """Reference-count every exact identity for one active chain."""
        keys = frozenset(self.key(candidate) for candidate in candidates)
        with self._lock:
            self._next_protection += 1
            protection = _ChainProtection(self._next_protection)
            self._protections[protection.token] = keys
            for key in keys:
                self._protection_counts[key] = self._protection_counts.get(key, 0) + 1
            return protection

    def release_protection(self, protection: _ChainProtection) -> None:
        """Release one active chain's protection and notify capacity waiters."""
        with self._lock:
            keys = self._protections.pop(protection.token, None)
            if keys is None:
                return
            for key in keys:
                remaining = self._protection_counts[key] - 1
                if remaining == 0:
                    del self._protection_counts[key]
                else:
                    self._protection_counts[key] = remaining
            self._notify_waiters_locked()

    def _prune_expired_locked(self, now: float) -> None:
        removed = False
        for key, entry in tuple(self._entries.items()):
            until = entry.cooldown_until
            if until is None or until > now:
                continue
            entry.cooldown_until = None
            entry.cooldown_started_at = None
            entry.cooldown_reason = None
            entry.cooldown_generation = None
            entry.cooldown_order = 0
            if entry.inflight == 0:
                del self._entries[key]
                removed = True
        if removed:
            self._notify_waiters_locked()

    def _evict_oldest_cooldown_locked(self) -> bool:
        eligible = (
            (entry.cooldown_order, key)
            for key, entry in self._entries.items()
            if self._protection_counts.get(key, 0) == 0
            and entry.inflight == 0
            and entry.cooldown_until is not None
        )
        oldest = min(eligible, default=None, key=lambda item: item[0])
        if oldest is None:
            return False
        del self._entries[oldest[1]]
        self._notify_waiters_locked()
        return True

    def _nearest_releasable_cooldown_locked(self) -> float | None:
        return min(
            (
                entry.cooldown_until
                for entry in self._entries.values()
                if entry.inflight == 0 and entry.cooldown_until is not None
            ),
            default=None,
        )

    def _register_waiter_locked(
        self, loop: asyncio.AbstractEventLoop
    ) -> _CapacityWaiter:
        self._next_waiter += 1
        waiter = _CapacityWaiter(
            token=self._next_waiter,
            loop=loop,
            future=loop.create_future(),
        )
        self._waiters[waiter.token] = waiter
        return waiter

    def _discard_waiter(self, waiter: _CapacityWaiter) -> None:
        with self._lock:
            if self._waiters.get(waiter.token) is waiter:
                del self._waiters[waiter.token]

    def _reserve_instruction_locked(
        self,
        key: _CandidateKey,
        loop: asyncio.AbstractEventLoop,
    ) -> _ReserveInstruction[_ReasonT]:
        now = self._read_clock_locked()
        self._prune_expired_locked(now)
        entry = self._entries.get(key)
        if entry is not None and entry.cooldown_until is not None:
            assert entry.cooldown_reason is not None
            return _ReserveInstruction(cooling_reason=entry.cooldown_reason)
        if entry is not None and entry.inflight < MAX_ACTIVE_ATTEMPTS_PER_CANDIDATE:
            return _ReserveInstruction(reservation=self._reserve_locked(key, entry))
        if entry is None and (
            len(self._entries) < self._capacity or self._evict_oldest_cooldown_locked()
        ):
            entry = _CandidateState()
            self._entries[key] = entry
            return _ReserveInstruction(reservation=self._reserve_locked(key, entry))
        waiter = self._register_waiter_locked(loop)
        cooldown_deadline = self._nearest_releasable_cooldown_locked()
        timeout = None if cooldown_deadline is None else cooldown_deadline - now
        return _ReserveInstruction(waiter=waiter, timeout=timeout)

    async def reserve(
        self,
        candidate: SearchProviderCandidate,
    ) -> tuple[_Reservation | None, _ReasonT | None]:
        """Reserve one attempt, waiting for state changes or cooldown expiry."""
        key = self.key(candidate)
        loop = asyncio.get_running_loop()
        while True:
            with self._lock:
                instruction = self._reserve_instruction_locked(key, loop)
            if instruction.reservation is not None:
                return instruction.reservation, None
            if instruction.cooling_reason is not None:
                return None, instruction.cooling_reason
            waiter = instruction.waiter
            assert waiter is not None
            try:
                if instruction.timeout is None:
                    await waiter.future
                else:
                    try:
                        await asyncio.wait_for(
                            waiter.future, timeout=instruction.timeout
                        )
                    except TimeoutError:
                        pass
            finally:
                self._discard_waiter(waiter)

    def _reserve_locked(
        self, key: _CandidateKey, entry: _CandidateState[_ReasonT]
    ) -> _Reservation:
        generation = entry.open_generation
        if generation is None:
            self._next_generation += 1
            generation = self._next_generation
            entry.open_generation = generation
            entry.cohorts[generation] = _AttemptCohort()
        self._next_reservation += 1
        reservation = _Reservation(self._next_reservation, key, generation)
        self._reservations[reservation.token] = reservation
        entry.cohorts[generation].active += 1
        entry.inflight += 1
        return reservation

    def _close_cohort_locked(
        self, entry: _CandidateState[_ReasonT], generation: int
    ) -> None:
        if entry.open_generation == generation:
            entry.open_generation = None

    def _publish_cohort_failure_locked(
        self,
        entry: _CandidateState[_ReasonT],
        generation: int,
        cohort: _AttemptCohort[_ReasonT],
        now: float,
    ) -> _ReasonT | None:
        reason = cohort.pending_failure_reason
        latest_success = entry.latest_success_generation
        if cohort.succeeded or reason is None:
            return None
        if generation in entry.suppressed_pending_generations:
            return None
        if latest_success is not None and latest_success >= generation:
            return None
        if entry.cooldown_until is not None and (
            entry.cooldown_generation is None or entry.cooldown_generation > generation
        ):
            return None
        self._next_cooldown_order += 1
        entry.cooldown_until = now + self._cooldown_seconds
        entry.cooldown_started_at = now
        entry.cooldown_reason = reason
        entry.cooldown_generation = generation
        entry.cooldown_order = self._next_cooldown_order
        return reason

    @staticmethod
    def _prune_success_order_locked(entry: _CandidateState[_ReasonT]) -> None:
        latest = entry.latest_success_generation
        if latest is None:
            return
        if any(generation < latest for generation in entry.cohorts):
            return
        entry.latest_success_generation = None

    def _validate_settlement_deadline_locked(
        self,
        reservation: _Reservation,
        *,
        now: float,
        success: bool,
        failure_reason: _ReasonT | None,
    ) -> None:
        if self._reservations.get(reservation.token) != reservation or success:
            return
        entry = self._entries[reservation.key]
        cohort = entry.cohorts[reservation.generation]
        pending_reason = failure_reason or cohort.pending_failure_reason
        latest_success = entry.latest_success_generation
        suppressed = reservation.generation in entry.suppressed_pending_generations
        active_cooldown = (
            entry.cooldown_until is not None and entry.cooldown_until > now
        )
        cooldown_blocks = active_cooldown and (
            entry.cooldown_generation is None
            or entry.cooldown_generation > reservation.generation
        )
        eligible = (
            cohort.active == 1
            and not cohort.succeeded
            and pending_reason is not None
            and (failure_reason is not None or not suppressed)
            and (latest_success is None or latest_success < reservation.generation)
            and not cooldown_blocks
        )
        if not eligible:
            return
        until = now + self._cooldown_seconds
        if not math.isfinite(until):
            raise ValueError("cooldown deadline must be finite")
        if until <= now:
            raise ValueError("cooldown deadline must be later than current time")

    def _settle_locked(
        self,
        reservation: _Reservation,
        *,
        now: float,
        success: bool = False,
        failure_reason: _ReasonT | None = None,
    ) -> _ReasonT | None:
        stored = self._reservations.get(reservation.token)
        if stored != reservation:
            return None
        entry = self._entries[reservation.key]
        cohort = entry.cohorts[reservation.generation]
        self._reservations.pop(reservation.token)
        if success or failure_reason is not None:
            self._close_cohort_locked(entry, reservation.generation)
        if success:
            cohort.succeeded = True
            latest = entry.latest_success_generation
            if latest is None or reservation.generation > latest:
                entry.latest_success_generation = reservation.generation
            cooldown_generation = entry.cooldown_generation
            if (
                entry.cooldown_until is not None
                and cooldown_generation is not None
                and cooldown_generation <= reservation.generation
            ):
                entry.cooldown_until = None
                entry.cooldown_started_at = None
                entry.cooldown_reason = None
                entry.cooldown_generation = None
                entry.cooldown_order = 0
        elif failure_reason is not None:
            entry.suppressed_pending_generations.discard(reservation.generation)
            cohort.pending_failure_reason = failure_reason
        cohort.active -= 1
        entry.inflight -= 1
        published_reason = None
        if cohort.active == 0:
            published_reason = self._publish_cohort_failure_locked(
                entry, reservation.generation, cohort, now
            )
            del entry.cohorts[reservation.generation]
            entry.suppressed_pending_generations.discard(reservation.generation)
            self._close_cohort_locked(entry, reservation.generation)
        self._prune_success_order_locked(entry)
        if entry.inflight == 0 and entry.cooldown_until is None:
            del self._entries[reservation.key]
        self._notify_waiters_locked()
        return published_reason

    def _discard_without_publication_locked(self, reservation: _Reservation) -> None:
        if self._reservations.pop(reservation.token, None) != reservation:
            return
        entry = self._entries[reservation.key]
        cohort = entry.cohorts[reservation.generation]
        cohort.active -= 1
        entry.inflight -= 1
        if cohort.active == 0:
            del entry.cohorts[reservation.generation]
            entry.suppressed_pending_generations.discard(reservation.generation)
            self._close_cohort_locked(entry, reservation.generation)
        self._prune_success_order_locked(entry)
        if entry.inflight == 0 and entry.cooldown_until is None:
            del self._entries[reservation.key]
        self._notify_waiters_locked()

    def _settle(
        self,
        reservation: _Reservation,
        *,
        success: bool = False,
        failure_reason: _ReasonT | None = None,
    ) -> _ReasonT | None:
        with self._lock:
            if self._reservations.get(reservation.token) != reservation:
                return None
            try:
                now = self._read_clock_locked()
                self._validate_settlement_deadline_locked(
                    reservation,
                    now=now,
                    success=success,
                    failure_reason=failure_reason,
                )
            except BaseException:
                self._discard_without_publication_locked(reservation)
                raise
            self._prune_expired_locked(now)
            return self._settle_locked(
                reservation,
                now=now,
                success=success,
                failure_reason=failure_reason,
            )

    def release(self, reservation: _Reservation) -> _ReasonT | None:
        """Neutrally release once and return any delayed cooldown publication."""
        return self._settle(reservation)

    def record_success(self, reservation: _Reservation) -> _ReasonT | None:
        """Atomically record health success and settle its reservation once."""
        return self._settle(reservation, success=True)

    def record_failure(
        self, reservation: _Reservation, reason: _ReasonT
    ) -> _ReasonT | None:
        """Atomically record health failure and settle its reservation once."""
        return self._settle(reservation, failure_reason=reason)

    def cooldown_reason(self, candidate: SearchProviderCandidate) -> _ReasonT | None:
        """Return the bounded active cooldown reason, if any."""
        key = self.key(candidate)
        with self._lock:
            now = self._read_clock_locked()
            self._prune_expired_locked(now)
            entry = self._entries.get(key)
            return entry.cooldown_reason if entry is not None else None

    def mark_failed(
        self,
        candidate: SearchProviderCandidate,
        reason: _ReasonT,
    ) -> _ReasonT:
        """Start a cooldown without exposing candidate or provider failure details."""
        key = self.key(candidate)
        with self._lock:
            now = self._read_clock_locked()
            until = now + self._cooldown_seconds
            if not math.isfinite(until):
                raise ValueError("cooldown deadline must be finite")
            if until <= now:
                raise ValueError("cooldown deadline must be later than current time")
            self._prune_expired_locked(now)
            entry = self._entries.get(key)
            if entry is None:
                if (
                    len(self._entries) >= self._capacity
                    and not self._evict_oldest_cooldown_locked()
                ):
                    raise SearchProviderStateCapacityUnavailable from None
                entry = _CandidateState()
                self._entries[key] = entry
            self._next_cooldown_order += 1
            entry.cooldown_until = until
            entry.cooldown_started_at = now
            entry.cooldown_reason = reason
            entry.cooldown_generation = None
            entry.cooldown_order = self._next_cooldown_order
            self._notify_waiters_locked()
            return reason

    def clear_cooldown_from_health_evidence(
        self,
        candidate: SearchProviderCandidate,
        *,
        reason: _ReasonT,
        evidence_started_at: float | None,
        quota_reason: _ReasonT,
    ) -> bool:
        """Clear only a matching quota cooldown with fresh monotonic evidence."""
        if isinstance(evidence_started_at, bool) or not isinstance(
            evidence_started_at, (int, float)
        ):
            return False
        if type(evidence_started_at) not in (int, float):
            return False
        try:
            evidence_value = float(evidence_started_at)
        except OverflowError:
            return False
        if not math.isfinite(evidence_value):
            return False
        key = self.key(candidate)
        with self._lock:
            now = self._read_clock_locked()
            self._prune_expired_locked(now)
            entry = self._entries.get(key)
            if entry is None or entry.cooldown_reason is not quota_reason:
                return False
            if reason is not quota_reason:
                return False
            started_at = entry.cooldown_started_at
            if (
                started_at is None
                or evidence_value <= started_at
                or evidence_value > now
            ):
                return False
            entry.suppressed_pending_generations.update(
                generation
                for generation, cohort in entry.cohorts.items()
                if cohort.pending_failure_reason is not None
            )
            entry.cooldown_until = None
            entry.cooldown_started_at = None
            entry.cooldown_reason = None
            entry.cooldown_generation = None
            entry.cooldown_order = 0
            if entry.inflight == 0:
                del self._entries[key]
            self._notify_waiters_locked()
            return True
