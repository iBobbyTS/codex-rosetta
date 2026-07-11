"""Unit tests for per-app Admin runtime ownership and bounded task state."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import pytest

from codex_rosetta.gateway.admin import runtime as runtime_module
from codex_rosetta.gateway.admin.runtime import (
    DEFAULT_TEST_TASK_MAX_COMPLETED_BYTES,
    DEFAULT_TEST_TASK_MAX_COUNT,
    DEFAULT_TEST_TASK_MAX_PAYLOAD_BYTES,
    AdminLoginLimiter,
    AdminRuntimeState,
    AdminTestTaskStore,
)


class _FakeTask:
    def __init__(self, *, done: bool = False) -> None:
        self._done = done
        self.cancelled = False

    def done(self) -> bool:
        return self._done

    def cancel(self) -> None:
        self.cancelled = True


def _reserve(store: AdminTestTaskStore) -> str:
    task_id, error = store.reserve()
    assert error is None
    assert task_id is not None
    return task_id


def test_login_limiter_updates_are_thread_safe() -> None:
    limiter = AdminLoginLimiter(max_attempts=200, capacity=1)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(lambda _: limiter.record_failure("198.51.100.10"), range(200))
        )

    blocked, retry_after = limiter.check("198.51.100.10")
    assert blocked is True
    assert retry_after > 0
    assert limiter._failures["198.51.100.10"]["count"] == 200


def test_expiry_cancels_and_clears_only_own_apps_active_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: now[0])
    store_a = AdminTestTaskStore(ttl_seconds=10)
    store_b = AdminTestTaskStore(ttl_seconds=10)
    task_a = _reserve(store_a)
    task_b = _reserve(store_b)
    work_a = _FakeTask()
    work_b = _FakeTask()
    store_a.attach_task(task_a, cast(Any, work_a))
    store_b.attach_task(task_b, cast(Any, work_b))

    now[0] += 11
    store_a.cleanup_expired()

    assert store_a.task_count == 0
    assert work_a.cancelled is True
    assert store_b.task_count == 1
    assert work_b.cancelled is False


def test_count_capacity_evicts_oldest_completed_and_preserves_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: now[0])
    store = AdminTestTaskStore(max_active=2, max_count=2)
    older = _reserve(store)
    assert store.finish(older, status="done", body_bytes=b'{"order":1}')
    older_bytes = store.completed_bytes
    now[0] += 1
    newer = _reserve(store)
    assert store.finish(newer, status="done", body_bytes=b'{"order":2}')
    newer_bytes = store.completed_bytes - older_bytes

    replacement = _reserve(store)

    assert replacement not in {older, newer}
    assert store.get_public(older) is None
    newer_result = store.get_public(newer)
    assert newer_result is not None
    assert newer_result["body"] == {"order": 2}
    assert store.completed_bytes == newer_bytes
    assert store.task_count == 2


def test_all_128_active_records_reject_the_next_reservation_without_eviction() -> None:
    store = AdminTestTaskStore(
        max_active=DEFAULT_TEST_TASK_MAX_COUNT,
        max_count=DEFAULT_TEST_TASK_MAX_COUNT,
    )

    task_ids = [_reserve(store) for _ in range(DEFAULT_TEST_TASK_MAX_COUNT)]
    rejected, error = store.reserve()

    assert len(set(task_ids)) == DEFAULT_TEST_TASK_MAX_COUNT
    assert rejected is None
    assert error == "Too many model tests are already running"
    assert store.active_count == DEFAULT_TEST_TASK_MAX_COUNT
    assert store.task_count == DEFAULT_TEST_TASK_MAX_COUNT
    assert store.completed_bytes == 0


def test_single_task_payload_budget_replaces_oversize_body_with_compact_error() -> None:
    store = AdminTestTaskStore(max_payload_bytes=512, max_completed_bytes=4096)
    task_id = _reserve(store)

    assert store.finish(task_id, status="done", body_bytes=b"x" * 513)

    result = store.get_public(task_id)
    assert result is not None
    assert result["status"] == "error"
    assert result["status_code"] == 507
    assert result["error"] == (
        "Admin model-test result exceeds retained-task capacity (512 bytes)"
    )
    assert "body" not in result
    assert 0 < store.completed_bytes <= 512


def test_default_32_mib_budget_evicts_oldest_completed_but_never_active() -> None:
    store = AdminTestTaskStore(max_active=9, max_count=16)
    active_id = _reserve(store)
    body = b'{"data":"' + b"x" * (DEFAULT_TEST_TASK_MAX_PAYLOAD_BYTES - 1024) + b'"}'
    completed: list[str] = []
    for _ in range(9):
        task_id = _reserve(store)
        assert store.finish(task_id, status="done", body_bytes=body)
        completed.append(task_id)

    assert store.completed_bytes <= DEFAULT_TEST_TASK_MAX_COMPLETED_BYTES
    active_result = store.get_public(active_id)
    assert active_result is not None
    assert active_result["status"] == "pending"
    assert store.get_public(completed[0]) is None
    assert store.get_public(completed[-1]) is not None
    assert store.active_count == 1
    assert store.task_count == 9


def test_get_decodes_temporarily_while_store_keeps_compact_bytes() -> None:
    store = AdminTestTaskStore()
    task_id = _reserve(store)
    assert store.finish(task_id, status="done", body_bytes=b'{"nested":[1,2,3]}')

    public = store.get_public(task_id)

    assert public is not None
    assert public["body"] == {"nested": [1, 2, 3]}
    assert store._tasks[task_id].body_bytes == b'{"nested":[1,2,3]}'
    assert isinstance(store._tasks[task_id].body_bytes, bytes)


def test_normal_error_cancel_ttl_and_eviction_keep_byte_accounting_consistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: now[0])
    store = AdminTestTaskStore(ttl_seconds=10, max_active=3, max_count=3)
    normal = _reserve(store)
    assert store.finish(normal, status="done", body_bytes=b'{"ok":true}')
    after_normal = store.completed_bytes
    error = _reserve(store)
    assert store.finish(error, status="error", status_code=502, error="upstream failed")
    after_error = store.completed_bytes
    cancelled = _reserve(store)
    work = _FakeTask()
    store.attach_task(cancelled, cast(Any, work))
    assert store.cancel(cancelled)

    assert after_normal > 0
    assert after_error > after_normal
    assert store.completed_bytes > after_error
    assert work.cancelled is True
    cancelled_result = store.get_public(cancelled)
    assert cancelled_result is not None
    assert cancelled_result["status"] == "cancelled"

    now[0] += 11
    store.cleanup_expired()
    assert store.task_count == 0
    assert store.completed_bytes == 0


def test_tiny_aggregate_budget_drops_diagnostic_without_negative_accounting() -> None:
    store = AdminTestTaskStore(max_payload_bytes=512, max_completed_bytes=1)
    task_id = _reserve(store)

    assert store.finish(task_id, status="done", body_bytes=b"oversize") is False
    assert store.task_count == 0
    assert store.completed_bytes == 0


def test_shutdown_cancels_and_awaits_only_own_apps_tasks_and_clears_results() -> None:
    async def _scenario() -> None:
        runtime_a = AdminRuntimeState()
        runtime_b = AdminRuntimeState()
        active_a = _reserve(runtime_a.test_tasks)
        active_b = _reserve(runtime_b.test_tasks)
        completed_a = _reserve(runtime_a.test_tasks)
        runtime_a.test_tasks.finish(
            completed_a, status="done", body_bytes=b'{"ok":true}'
        )
        started_a = asyncio.Event()
        started_b = asyncio.Event()

        async def _wait(started: asyncio.Event) -> None:
            started.set()
            await asyncio.Event().wait()

        work_a = asyncio.create_task(_wait(started_a))
        work_b = asyncio.create_task(_wait(started_b))
        runtime_a.test_tasks.attach_task(active_a, work_a)
        runtime_b.test_tasks.attach_task(active_b, work_b)
        await asyncio.gather(started_a.wait(), started_b.wait())

        await runtime_a.aclose()

        assert work_a.cancelled()
        assert not work_b.done()
        assert runtime_a.test_tasks.task_count == 0
        assert runtime_a.test_tasks.completed_bytes == 0
        assert runtime_b.test_tasks.task_count == 1
        await runtime_b.aclose()
        assert work_b.cancelled()

    asyncio.run(_scenario())
