"""Private process-local coordination for ordered failover adopters."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable, Hashable, Sequence
from typing import Generic, TypeVar

_CandidateT = TypeVar("_CandidateT", bound=Hashable)
_OutcomeT = TypeVar("_OutcomeT")
_PendingT = TypeVar("_PendingT")


class FailoverGate(Generic[_OutcomeT, _PendingT]):
    """Coordinate one leader, waiters, and cancellation handoff in-process."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._generation = 0
        self._active = False
        self._orphaned = False
        self._pending: _PendingT | None = None
        self._outcome: _OutcomeT | None = None

    @property
    def generation(self) -> int:
        return self._generation

    async def await_active(
        self,
    ) -> tuple[int, _OutcomeT | None, bool, bool, _PendingT | None]:
        waited = False
        async with self._condition:
            while self._active:
                waited = True
                if self._orphaned:
                    self._orphaned = False
                    pending = self._pending
                    self._pending = None
                    return self._generation, None, waited, True, pending
                await self._condition.wait()
            return self._generation, self._outcome, waited, False, None

    async def claim(
        self, observed_generation: int
    ) -> tuple[bool, int, _OutcomeT | None, _PendingT | None]:
        async with self._condition:
            while self._active:
                if self._orphaned:
                    self._orphaned = False
                    pending = self._pending
                    self._pending = None
                    return True, self._generation, None, pending
                await self._condition.wait()
            if self._generation != observed_generation:
                return False, self._generation, self._outcome, None
            self._generation += 1
            self._active = True
            self._orphaned = False
            self._pending = None
            self._outcome = None
            return True, self._generation, None, None

    async def publish(self, outcome: _OutcomeT | None) -> None:
        async with self._condition:
            self._outcome = outcome
            self._active = False
            self._orphaned = False
            self._pending = None
            self._condition.notify_all()

    async def handoff(self, pending: _PendingT | None) -> None:
        async with self._condition:
            self._orphaned = True
            self._pending = pending
            self._condition.notify_all()


class OrderedFailoverCoordinator(Generic[_CandidateT]):
    """Own ordered current selection, cooldowns, and a failover gate."""

    def __init__(
        self,
        candidates: Sequence[_CandidateT],
        current: _CandidateT,
        *,
        cooldown_seconds: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        snapshot = tuple(candidates)
        if not snapshot or len(set(snapshot)) != len(snapshot):
            raise ValueError("ordered candidates must be non-empty and unique")
        if current not in snapshot:
            raise ValueError("current candidate must belong to ordered candidates")
        cooldown_seconds = float(cooldown_seconds)
        if not math.isfinite(cooldown_seconds) or cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        self._candidates = snapshot
        self._current = current
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._cooldown_until: dict[_CandidateT, float] = {}
        self._gate = FailoverGate[None, None]()

    @property
    def current(self) -> _CandidateT:
        return self._current

    @property
    def candidates(self) -> tuple[_CandidateT, ...]:
        return self._candidates

    async def wait(self) -> None:
        await self._gate.await_active()

    async def claim(self, observed: _CandidateT) -> bool:
        generation = self._gate.generation
        leader, _generation, _outcome, _pending = await self._gate.claim(generation)
        if leader and self._current != observed:
            await self._gate.publish(None)
            return False
        return leader

    def mark_failed(self, candidate: _CandidateT) -> None:
        self._cooldown_until[candidate] = self._clock() + self._cooldown_seconds

    def _prune(self) -> None:
        now = self._clock()
        self._cooldown_until = {
            candidate: deadline
            for candidate, deadline in self._cooldown_until.items()
            if deadline > now
        }

    def available(self) -> tuple[_CandidateT, ...]:
        self._prune()
        start = self._candidates.index(self._current)
        ordered = self._candidates[start:] + self._candidates[:start]
        return tuple(item for item in ordered if item not in self._cooldown_until)

    def next_available_after(self, candidate: _CandidateT) -> _CandidateT | None:
        self._prune()
        start = self._candidates.index(candidate)
        ordered = self._candidates[start + 1 :] + self._candidates[: start + 1]
        return next(
            (item for item in ordered if item not in self._cooldown_until), None
        )

    def set_current(self, candidate: _CandidateT) -> None:
        if candidate not in self._candidates:
            raise ValueError("current candidate must belong to ordered candidates")
        self._current = candidate

    async def publish(self) -> None:
        await self._gate.publish(None)
