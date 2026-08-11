"""Small thread-safe cooldown state for the search provider chain."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar

from .search_provider_candidates import SearchProviderCandidate

DEFAULT_SEARCH_PROVIDER_STATE_CAPACITY = 256

_ReasonT = TypeVar("_ReasonT", bound=StrEnum)


@dataclass(frozen=True, slots=True)
class _CandidateKey:
    """Exact candidate identity key with a credential-safe representation."""

    row_id: str
    identity: str = field(repr=False)


@dataclass(slots=True)
class _CandidateState(Generic[_ReasonT]):
    cooldown_until: float
    cooldown_started_at: float
    cooldown_reason: _ReasonT
    cooldown_order: int


class SearchProviderStateCapacityUnavailable(RuntimeError):
    """Compatibility error for callers that expose bounded state capacity."""

    def __init__(self) -> None:
        super().__init__("Search provider state capacity unavailable")


class _SearchProviderChainState(Generic[_ReasonT]):
    """Own a bounded process-local cooldown map behind one lock."""

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
        self._next_cooldown_order = 0

    @staticmethod
    def key(candidate: SearchProviderCandidate) -> _CandidateKey:
        """Return the exact row and process-local identity key."""
        return _CandidateKey(candidate.row_id, candidate.identity)

    def _read_clock_locked(self) -> float:
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("clock must return a finite value")
        if now < self._last_clock:
            raise ValueError("clock must be monotonic")
        self._last_clock = now
        return now

    def _prune_expired_locked(self, now: float) -> None:
        expired = [
            key for key, entry in self._entries.items() if entry.cooldown_until <= now
        ]
        for key in expired:
            del self._entries[key]

    def _evict_oldest_locked(self) -> None:
        oldest = min(
            self._entries,
            key=lambda key: self._entries[key].cooldown_order,
        )
        del self._entries[oldest]

    def cooldown_reason(self, candidate: SearchProviderCandidate) -> _ReasonT | None:
        """Return the active cooldown reason, pruning expired rows lazily."""
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
        """Start or replace one row identity's ordinary cooldown."""
        key = self.key(candidate)
        with self._lock:
            now = self._read_clock_locked()
            until = now + self._cooldown_seconds
            if not math.isfinite(until):
                raise ValueError("cooldown deadline must be finite")
            if until <= now:
                raise ValueError("cooldown deadline must be later than current time")
            self._prune_expired_locked(now)
            if key not in self._entries and len(self._entries) >= self._capacity:
                self._evict_oldest_locked()
            self._next_cooldown_order += 1
            self._entries[key] = _CandidateState(
                cooldown_until=until,
                cooldown_started_at=now,
                cooldown_reason=reason,
                cooldown_order=self._next_cooldown_order,
            )
        return reason

    def clear_cooldown_from_health_evidence(
        self,
        candidate: SearchProviderCandidate,
        *,
        reason: _ReasonT,
        evidence_started_at: float | None,
        quota_reason: _ReasonT,
    ) -> bool:
        """Clear a matching quota cooldown using fresh monotonic evidence."""
        if (
            evidence_started_at is None
            or isinstance(evidence_started_at, bool)
            or type(evidence_started_at)
            not in (
                int,
                float,
            )
        ):
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
            if (
                entry is None
                or entry.cooldown_reason is not quota_reason
                or reason is not quota_reason
                or evidence_value <= entry.cooldown_started_at
                or evidence_value > now
            ):
                return False
            del self._entries[key]
            return True
