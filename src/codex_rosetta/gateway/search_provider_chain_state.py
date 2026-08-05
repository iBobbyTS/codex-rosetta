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


@dataclass(slots=True)
class _CandidateState(Generic[_ReasonT]):
    cooldown_until: float | None = None
    cooldown_reason: _ReasonT | None = None
    cooldown_order: int = 0
    inflight: int = 0


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
        self._capacity_event = asyncio.Event()
        self._entries: dict[_CandidateKey, _CandidateState[_ReasonT]] = {}
        self._reservations: dict[int, _CandidateKey] = {}
        self._next_reservation = 0
        self._next_cooldown_order = 0

    @staticmethod
    def key(candidate: SearchProviderCandidate) -> _CandidateKey:
        """Return the secret-safe exact identity key for a candidate."""
        return _CandidateKey(candidate.row_id, candidate.identity)

    def keys_for(
        self, candidates: Iterable[SearchProviderCandidate]
    ) -> frozenset[_CandidateKey]:
        """Return the exact identities protected by one executing chain."""
        return frozenset(self.key(candidate) for candidate in candidates)

    def _read_clock_locked(self) -> float:
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("clock must return a finite value")
        if now < self._last_clock:
            raise ValueError("clock must be monotonic")
        self._last_clock = now
        return now

    def _rotate_capacity_event_locked(self) -> None:
        event = self._capacity_event
        self._capacity_event = asyncio.Event()
        event.set()

    def _prune_expired_locked(self, now: float) -> None:
        removed = False
        for key, entry in tuple(self._entries.items()):
            until = entry.cooldown_until
            if until is None or until > now:
                continue
            entry.cooldown_until = None
            entry.cooldown_reason = None
            entry.cooldown_order = 0
            if entry.inflight == 0:
                del self._entries[key]
                removed = True
        if removed:
            self._rotate_capacity_event_locked()

    def _evict_oldest_cooldown_locked(
        self, protected_keys: frozenset[_CandidateKey]
    ) -> bool:
        eligible = (
            (entry.cooldown_order, key)
            for key, entry in self._entries.items()
            if key not in protected_keys
            and entry.inflight == 0
            and entry.cooldown_until is not None
        )
        oldest = min(eligible, default=None, key=lambda item: item[0])
        if oldest is None:
            return False
        del self._entries[oldest[1]]
        self._rotate_capacity_event_locked()
        return True

    async def reserve(
        self,
        candidate: SearchProviderCandidate,
        protected_keys: frozenset[_CandidateKey],
    ) -> tuple[_Reservation | None, _ReasonT | None]:
        """Reserve one candidate attempt, waiting on rotated capacity notifications."""
        key = self.key(candidate)
        while True:
            with self._lock:
                now = self._read_clock_locked()
                self._prune_expired_locked(now)
                entry = self._entries.get(key)
                if entry is not None and entry.cooldown_until is not None:
                    return None, entry.cooldown_reason
                if (
                    entry is not None
                    and entry.inflight < MAX_ACTIVE_ATTEMPTS_PER_CANDIDATE
                ):
                    return self._reserve_locked(key, entry), None
                if entry is None:
                    if len(self._entries) < self._capacity:
                        entry = _CandidateState()
                        self._entries[key] = entry
                        return self._reserve_locked(key, entry), None
                    if self._evict_oldest_cooldown_locked(protected_keys):
                        entry = _CandidateState()
                        self._entries[key] = entry
                        return self._reserve_locked(key, entry), None
                capacity_event = self._capacity_event
            await capacity_event.wait()

    def _reserve_locked(
        self, key: _CandidateKey, entry: _CandidateState[_ReasonT]
    ) -> _Reservation:
        self._next_reservation += 1
        reservation = _Reservation(self._next_reservation, key)
        self._reservations[reservation.token] = key
        entry.inflight += 1
        return reservation

    def release(self, reservation: _Reservation) -> None:
        """Release an admission token once and notify every capacity waiter."""
        with self._lock:
            key = self._reservations.pop(reservation.token, None)
            if key is None or key != reservation.key:
                return
            entry = self._entries[key]
            entry.inflight -= 1
            if entry.inflight == 0 and entry.cooldown_until is None:
                del self._entries[key]
            self._rotate_capacity_event_locked()

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
        reservation: _Reservation | None = None,
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
                if len(
                    self._entries
                ) >= self._capacity and not self._evict_oldest_cooldown_locked(
                    frozenset({key})
                ):
                    raise RuntimeError("Search provider state capacity unavailable")
                entry = _CandidateState()
                self._entries[key] = entry
            if (
                reservation is not None
                and self._reservations.get(reservation.token) != key
            ):
                return reason
            self._next_cooldown_order += 1
            entry.cooldown_until = until
            entry.cooldown_reason = reason
            entry.cooldown_order = self._next_cooldown_order
            return reason
