"""App-owned bounded daemon workers for blocking Google image conversion."""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from codex_rosetta.converters.google_genai.image_fetch import ImageFetchCancellation

_T = TypeVar("_T")

DEFAULT_IMAGE_FETCH_WORKERS = 4
_SENTINEL = object()


class ImageWorkerError(RuntimeError):
    """Base class for stable Gateway image-worker failures."""


class ImageWorkerCapacityError(ImageWorkerError):
    """Raised when all app-owned image workers remain occupied."""


class ImageWorkerTimeoutError(ImageWorkerError):
    """Raised when a blocking conversion exceeds its wall-clock budget."""


@dataclass(frozen=True)
class _WorkItem(Generic[_T]):
    function: Callable[[], _T]
    future: Future[_T]
    cancellation: ImageFetchCancellation


class ImageFetchWorkerPool:
    """Run blocking conversions on a fixed, bounded set of daemon threads."""

    def __init__(self, *, max_workers: int = DEFAULT_IMAGE_FETCH_WORKERS) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        self._max_workers = max_workers
        self._queue: queue.Queue[_WorkItem[object] | object] = queue.Queue(
            maxsize=max_workers
        )
        self._permits = asyncio.Semaphore(max_workers)
        self._lock = threading.Lock()
        self._tokens: set[ImageFetchCancellation] = set()
        self._waiting_submitters = 0
        self._closed = False
        self._threads = tuple(
            threading.Thread(
                target=self._worker,
                name=f"codex-rosetta-image-{index}",
                daemon=True,
            )
            for index in range(max_workers)
        )
        for thread in self._threads:
            thread.start()

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _SENTINEL:
                    return
                work = cast(_WorkItem[object], item)
                if not work.future.set_running_or_notify_cancel():
                    continue
                try:
                    result = work.function()
                except BaseException as exc:
                    work.future.set_exception(exc)
                else:
                    work.future.set_result(result)
            finally:
                self._queue.task_done()

    async def run(
        self,
        function: Callable[[], _T],
        *,
        cancellation: ImageFetchCancellation,
        timeout_seconds: float,
    ) -> _T:
        """Run one conversion without releasing capacity before worker exit."""
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        with self._lock:
            if self._closed:
                raise ImageWorkerCapacityError("Image conversion workers are closed")
            self._waiting_submitters += 1

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        acquired = False
        try:
            try:
                await asyncio.wait_for(
                    self._permits.acquire(),
                    timeout=timeout_seconds,
                )
                acquired = True
            except asyncio.TimeoutError:
                raise ImageWorkerCapacityError(
                    "Image conversion capacity is temporarily unavailable"
                ) from None
        finally:
            with self._lock:
                self._waiting_submitters -= 1

        with self._lock:
            if self._closed:
                if acquired:
                    self._permits.release()
                raise ImageWorkerCapacityError("Image conversion workers are closed")
            self._tokens.add(cancellation)

        raw_future: Future[_T] = Future()

        def _worker_done(_future: Future[_T]) -> None:
            with self._lock:
                self._tokens.discard(cancellation)
            try:
                loop.call_soon_threadsafe(self._permits.release)
            except RuntimeError:
                pass

        raw_future.add_done_callback(_worker_done)
        try:
            self._queue.put_nowait(
                cast(
                    _WorkItem[object],
                    _WorkItem(function, raw_future, cancellation),
                )
            )
        except BaseException:
            with self._lock:
                self._tokens.discard(cancellation)
            raw_future.cancel()
            raise

        wrapped = asyncio.wrap_future(raw_future)
        wrapped.add_done_callback(
            lambda future: None if future.cancelled() else future.exception()
        )
        remaining = deadline - loop.time()
        if remaining <= 0:
            cancellation.cancel()
            raise ImageWorkerTimeoutError("Image conversion timed out")
        try:
            return await asyncio.wait_for(
                asyncio.shield(wrapped),
                timeout=remaining,
            )
        except asyncio.TimeoutError:
            cancellation.cancel()
            raise ImageWorkerTimeoutError("Image conversion timed out") from None
        except asyncio.CancelledError:
            cancellation.cancel()
            raise

    async def close(self) -> None:
        """Cancel work, drain queued items, and stop without joining active workers."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            tokens = tuple(self._tokens)
            waiting_submitters = self._waiting_submitters

        for token in tokens:
            token.cancel()
        for _ in range(waiting_submitters):
            self._permits.release()

        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                if item is not _SENTINEL:
                    work = cast(_WorkItem[object], item)
                    work.cancellation.cancel()
                    work.future.cancel()
            finally:
                self._queue.task_done()

        for _ in self._threads:
            self._queue.put_nowait(_SENTINEL)
