"""Gateway scheduling tests for Google URL-image conversion."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
import textwrap
from types import SimpleNamespace
from typing import Any, cast

import pytest

from codex_rosetta.gateway.proxy import _convert_request
from codex_rosetta.converters.google_genai.image_fetch import (
    ImageFetchCancellation,
    ImageFetchPolicy,
)
from codex_rosetta.gateway.image_workers import (
    ImageFetchWorkerPool,
    ImageWorkerCapacityError,
    ImageWorkerTimeoutError,
)
from codex_rosetta.pipeline import ConversionPipeline
from codex_rosetta.routing import ResolvedRoute


class _Pipeline:
    def __init__(self) -> None:
        self.thread_id: int | None = None

    def convert_request(self, body: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        self.thread_id = threading.get_ident()
        return body


def test_google_request_conversion_runs_off_the_event_loop():
    pipeline = _Pipeline()
    main_thread = threading.get_ident()

    result = asyncio.run(
        _convert_request(
            cast(ConversionPipeline, pipeline),
            cast(ResolvedRoute, SimpleNamespace(target_provider="google")),
            {"model": "gemini-test"},
            lambda _body: None,
        )
    )

    assert result == {"model": "gemini-test"}
    assert pipeline.thread_id is not None
    assert pipeline.thread_id != main_thread


def test_non_google_request_conversion_stays_on_the_event_loop_thread():
    pipeline = _Pipeline()
    main_thread = threading.get_ident()

    asyncio.run(
        _convert_request(
            cast(ConversionPipeline, pipeline),
            cast(ResolvedRoute, SimpleNamespace(target_provider="anthropic")),
            {"model": "claude-test"},
            lambda _body: None,
        )
    )

    assert pipeline.thread_id == main_thread


def test_worker_timeout_keeps_permit_until_raw_worker_exits():
    gate = threading.Event()
    started = threading.Event()

    class _BlockingPipeline(_Pipeline):
        def convert_request(
            self, body: dict[str, Any], **_kwargs: Any
        ) -> dict[str, Any]:
            started.set()
            gate.wait(timeout=1)
            return body

    async def _scenario() -> None:
        owner = ImageFetchWorkerPool(max_workers=1)
        first_token = ImageFetchCancellation()
        policy = ImageFetchPolicy(
            timeout_seconds=0.03,
            cancellation=first_token,
        )
        try:
            with pytest.raises(ImageWorkerTimeoutError, match="timed out"):
                await _convert_request(
                    cast(ConversionPipeline, _BlockingPipeline()),
                    cast(ResolvedRoute, SimpleNamespace(target_provider="google")),
                    {"model": "gemini-test"},
                    lambda _body: None,
                    image_fetch_workers=owner,
                    image_fetch_policy=policy,
                )
            assert started.is_set()
            assert first_token.cancelled is True

            with pytest.raises(ImageWorkerCapacityError, match="capacity"):
                await _convert_request(
                    cast(ConversionPipeline, _Pipeline()),
                    cast(ResolvedRoute, SimpleNamespace(target_provider="google")),
                    {"model": "gemini-test"},
                    lambda _body: None,
                    image_fetch_workers=owner,
                    image_fetch_policy=ImageFetchPolicy(timeout_seconds=0.03),
                )

            gate.set()
            result = await _convert_request(
                cast(ConversionPipeline, _Pipeline()),
                cast(ResolvedRoute, SimpleNamespace(target_provider="google")),
                {"model": "gemini-test"},
                lambda _body: None,
                image_fetch_workers=owner,
                image_fetch_policy=ImageFetchPolicy(timeout_seconds=0.5),
            )
            assert result["model"] == "gemini-test"
        finally:
            gate.set()
            await owner.close()

    asyncio.run(_scenario())


def test_worker_pools_are_isolated_and_event_loop_stays_responsive():
    gate = threading.Event()

    class _BlockingPipeline(_Pipeline):
        def convert_request(
            self, body: dict[str, Any], **_kwargs: Any
        ) -> dict[str, Any]:
            gate.wait(timeout=1)
            return body

    async def _scenario() -> None:
        owner_a = ImageFetchWorkerPool(max_workers=1)
        owner_b = ImageFetchWorkerPool(max_workers=1)
        try:
            blocked = asyncio.create_task(
                _convert_request(
                    cast(ConversionPipeline, _BlockingPipeline()),
                    cast(ResolvedRoute, SimpleNamespace(target_provider="google")),
                    {"model": "blocked"},
                    lambda _body: None,
                    image_fetch_workers=owner_a,
                    image_fetch_policy=ImageFetchPolicy(timeout_seconds=0.5),
                )
            )
            await asyncio.sleep(0.01)
            result = await _convert_request(
                cast(ConversionPipeline, _Pipeline()),
                cast(ResolvedRoute, SimpleNamespace(target_provider="google")),
                {"model": "independent"},
                lambda _body: None,
                image_fetch_workers=owner_b,
                image_fetch_policy=ImageFetchPolicy(timeout_seconds=0.2),
            )
            assert result["model"] == "independent"
            assert blocked.done() is False
            gate.set()
            await blocked
        finally:
            gate.set()
            await owner_a.close()
            await owner_b.close()

    asyncio.run(_scenario())


def test_worker_pool_uses_fixed_bounded_daemon_threads():
    async def _scenario() -> None:
        owner = ImageFetchWorkerPool(max_workers=2)
        try:
            assert owner._queue.maxsize == 2
            assert len(owner._threads) == 2
            assert all(thread.daemon for thread in owner._threads)
        finally:
            await owner.close()
            await owner.close()

    asyncio.run(_scenario())


def test_close_wakes_capacity_waiters_and_rejects_new_work():
    gate = threading.Event()
    started = threading.Event()

    def _block() -> str:
        started.set()
        gate.wait(timeout=1)
        return "done"

    async def _scenario() -> None:
        owner = ImageFetchWorkerPool(max_workers=1)
        first_token = ImageFetchCancellation()
        first = asyncio.create_task(
            owner.run(_block, cancellation=first_token, timeout_seconds=1)
        )
        while not started.is_set():
            await asyncio.sleep(0)
        second = asyncio.create_task(
            owner.run(
                lambda: "never-runs",
                cancellation=ImageFetchCancellation(),
                timeout_seconds=1,
            )
        )
        await asyncio.sleep(0.01)

        await owner.close()
        with pytest.raises(ImageWorkerCapacityError, match="closed"):
            await second
        with pytest.raises(ImageWorkerCapacityError, match="closed"):
            await owner.run(
                lambda: "never-runs",
                cancellation=ImageFetchCancellation(),
                timeout_seconds=1,
            )
        assert first_token.cancelled is True
        gate.set()
        assert await first == "done"

    asyncio.run(_scenario())


def test_stuck_daemon_worker_does_not_block_interpreter_exit():
    code = textwrap.dedent(
        """
        import asyncio
        import time

        from codex_rosetta.converters.google_genai.image_fetch import ImageFetchCancellation
        from codex_rosetta.gateway.image_workers import (
            ImageFetchWorkerPool,
            ImageWorkerTimeoutError,
        )

        async def main():
            owner = ImageFetchWorkerPool(max_workers=1)
            try:
                await owner.run(
                    lambda: time.sleep(30),
                    cancellation=ImageFetchCancellation(),
                    timeout_seconds=0.05,
                )
            except ImageWorkerTimeoutError:
                pass
            await owner.close()

        asyncio.run(main())
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert completed.returncode == 0, completed.stderr
