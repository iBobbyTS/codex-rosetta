"""Route tests for app-owned, bounded Admin model-test tasks."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from codex_rosetta.gateway.admin.routes import testing
from codex_rosetta.gateway.admin.runtime import (
    DEFAULT_TEST_TASK_MAX_PAYLOAD_BYTES,
    AdminRuntimeState,
    AdminTestTaskStore,
)
from codex_rosetta.gateway.transport import UpstreamResponseTooLargeError
from codex_rosetta.gateway.transport.http.transport import BoundedHttpResponse


def _app(*, store: AdminTestTaskStore | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        internal_token="internal",
        _bind_host="127.0.0.1",
        _bind_port=28765,
        admin_runtime_state=AdminRuntimeState(test_tasks=store),
    )


def _request(app: SimpleNamespace) -> SimpleNamespace:
    request = SimpleNamespace(app=app)
    request.json = lambda: {
        "endpoint": "/v1/responses",
        "payload": {"model": "test-model"},
    }
    return request


def _body(response: Any) -> dict[str, object]:
    return json.loads(response.body.decode("utf-8"))


def _reserve(store: AdminTestTaskStore) -> str:
    task_id, error = store.reserve()
    assert error is None
    assert task_id is not None
    return task_id


def test_start_test_rejects_when_app_concurrency_limit_is_reached() -> None:
    store = AdminTestTaskStore(max_active=2)
    _reserve(store)
    _reserve(store)

    response = asyncio.run(testing.start_test(_request(_app(store=store))))

    assert response.status_code == 429
    assert _body(response) == {"error": "Too many model tests are already running"}


def test_poll_sweeps_only_the_current_apps_expired_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(
        "codex_rosetta.gateway.admin.runtime.time.monotonic",
        lambda: now[0],
    )
    store_a = AdminTestTaskStore(ttl_seconds=10)
    store_b = AdminTestTaskStore(ttl_seconds=10)
    task_a = _reserve(store_a)
    task_b = _reserve(store_b)
    store_a.finish(task_a, status="done", body_bytes=b'{"app":"a"}')
    store_b.finish(task_b, status="done", body_bytes=b'{"app":"b"}')
    now[0] += 11

    response = asyncio.run(
        testing.get_test_result(_request(_app(store=store_a)), task_a)
    )

    assert response.status_code == 404
    assert store_a.task_count == 0
    assert store_b.task_count == 1


def test_cross_app_poll_and_cancel_return_not_found() -> None:
    store_a = AdminTestTaskStore()
    store_b = AdminTestTaskStore()
    task_a = _reserve(store_a)
    store_a.finish(task_a, status="done", body_bytes=b'{"secret":"app-a"}')
    request_b = _request(_app(store=store_b))

    poll = asyncio.run(testing.get_test_result(request_b, task_a))
    cancel = asyncio.run(testing.cancel_test(request_b, task_a))

    assert poll.status_code == 404
    assert cancel.status_code == 404
    assert _body(poll) == {"error": "Task not found"}
    assert _body(cancel) == {"error": "Task not found"}
    own_result = store_a.get_public(task_a)
    assert own_result is not None
    assert own_result["body"] == {"secret": "app-a"}


def test_model_test_self_call_uses_explicit_four_mib_limits_and_retains_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    async def _fake_bounded(client: Any, method: str, url: str, **kwargs: Any):
        calls.append((method, url, kwargs))
        return BoundedHttpResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            content=b'{"ok":true}',
        )

    monkeypatch.setattr(testing, "AsyncClient", _FakeClient)
    monkeypatch.setattr(testing, "request_bounded_response", _fake_bounded)
    store = AdminTestTaskStore()
    task_id = _reserve(store)

    asyncio.run(
        testing._run_test_task(
            task_id,
            store,
            "http://127.0.0.1:28765",
            "/v1/responses",
            {"model": "test"},
            "internal-token",
        )
    )

    assert calls == [
        (
            "POST",
            "http://127.0.0.1:28765/v1/responses",
            {
                "json": {"model": "test"},
                "headers": {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer internal-token",
                },
                "max_success_bytes": DEFAULT_TEST_TASK_MAX_PAYLOAD_BYTES,
                "max_error_bytes": DEFAULT_TEST_TASK_MAX_PAYLOAD_BYTES,
            },
        )
    ]
    assert store.get_public(task_id) == {
        "status": "done",
        "started": pytest.approx(store._tasks[task_id].started),
        "finished": pytest.approx(store._tasks[task_id].finished),
        "status_code": 200,
        "body": {"ok": True},
    }
    assert store._tasks[task_id].body_bytes == b'{"ok":true}'


def test_oversized_model_test_becomes_stable_502_without_partial_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def aclose(self) -> None:
            pass

    async def _too_large(*args: Any, **kwargs: Any) -> BoundedHttpResponse:
        raise UpstreamResponseTooLargeError("must not leak a partial body")

    monkeypatch.setattr(testing, "AsyncClient", _FakeClient)
    monkeypatch.setattr(testing, "request_bounded_response", _too_large)
    store = AdminTestTaskStore()
    task_id = _reserve(store)

    asyncio.run(
        testing._run_test_task(
            task_id,
            store,
            "http://127.0.0.1:28765",
            "/v1/responses",
            {"model": "test"},
            "internal-token",
        )
    )

    result = store.get_public(task_id)
    assert result == {
        "status": "error",
        "started": pytest.approx(store._tasks[task_id].started),
        "finished": pytest.approx(store._tasks[task_id].finished),
        "status_code": 502,
        "error": (
            "Admin model-test upstream response exceeds "
            f"{DEFAULT_TEST_TASK_MAX_PAYLOAD_BYTES} bytes"
        ),
    }
    assert store._tasks[task_id].body_bytes is None
