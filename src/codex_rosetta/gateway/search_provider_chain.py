"""Request-local budgets and typed errors for web-search provider chains."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Generic, TypeVar

SEARCH_PROVIDER_REQUEST_TIMEOUT_SECONDS = 300.0
MAX_SEARCH_PROVIDER_EXTERNAL_CALLS = 32

_ResultT = TypeVar("_ResultT")
_ReasonT = TypeVar("_ReasonT", bound=StrEnum)
_AsyncOperation = Callable[[], Awaitable[_ResultT]]


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


class SearchProviderRequestBudget:
    """One request's frozen deadline and external-call allowance."""

    def __init__(
        self,
        *,
        timeout_seconds: float = SEARCH_PROVIDER_REQUEST_TIMEOUT_SECONDS,
        max_external_calls: int = MAX_SEARCH_PROVIDER_EXTERNAL_CALLS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_external_calls <= 0:
            raise ValueError("max_external_calls must be positive")
        self._clock = clock
        self._timeout_seconds = float(timeout_seconds)
        self._max_external_calls = max_external_calls
        self._started_at = clock()
        self._deadline = self._started_at + self._timeout_seconds
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
        return {
            "reason": reason.value if reason is not None else None,
            "external_calls": self._external_calls,
            "external_call_limit": self._max_external_calls,
            "elapsed_seconds": max(0.0, self._clock() - self._started_at),
            "deadline_seconds": self._timeout_seconds,
        }

    def _remaining(self) -> float:
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise SearchProviderBudgetExceeded(
                SearchProviderBudgetReason.DEADLINE_EXCEEDED
            )
        return remaining

    async def _run_with_timeout(
        self, operation: _AsyncOperation[_ResultT], remaining: float
    ) -> _ResultT:
        timeout = asyncio.timeout(remaining)
        try:
            async with timeout:
                return await operation()
        except TimeoutError:
            if timeout.expired():
                raise SearchProviderBudgetExceeded(
                    SearchProviderBudgetReason.DEADLINE_EXCEEDED
                ) from None
            raise

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
