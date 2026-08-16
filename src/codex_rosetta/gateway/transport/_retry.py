"""Private status-neutral retry sequencing."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

_ResultT = TypeVar("_ResultT")

_FAILOVER_RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0, 16.0)


@dataclass(frozen=True)
class _RetryPolicy:
    """Repeat an async operation while a caller-defined predicate matches."""

    delays: tuple[float, ...]

    async def run(
        self,
        initial_result: _ResultT,
        operation: Callable[[], Awaitable[_ResultT]],
        retry_if: Callable[[_ResultT], bool],
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> _ResultT:
        result = initial_result
        for delay in self.delays:
            if not retry_if(result):
                break
            await sleep(delay)
            result = await operation()
        return result


_FAILOVER_RETRY_POLICY = _RetryPolicy(_FAILOVER_RETRY_DELAYS)
