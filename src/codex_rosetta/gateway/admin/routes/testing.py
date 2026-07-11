"""Async model test task route handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from codex_rosetta._vendor.httpclient import AsyncClient
from codex_rosetta._vendor.httpserver import JSONResponse, Response

from ...config import GatewayConfig
from ...transport import UpstreamResponseTooLargeError
from ...transport.http.transport import request_bounded_response
from ..runtime import (
    DEFAULT_TEST_TASK_MAX_PAYLOAD_BYTES,
    DEFAULT_TEST_TASK_TIMEOUT_SECONDS,
    AdminTestTaskStore,
)
from ._shared import _parse_json_object

_TASK_TIMEOUT = DEFAULT_TEST_TASK_TIMEOUT_SECONDS
_TASK_RESPONSE_MAX_BYTES = DEFAULT_TEST_TASK_MAX_PAYLOAD_BYTES


async def _run_test_task(
    task_id: str,
    store: AdminTestTaskStore,
    base_url: str,
    endpoint: str,
    payload: dict[str, Any],
    internal_token: str,
) -> None:
    """Execute an upstream test request via a self-call to the gateway.

    Results are stored in the app-owned task store.  This runs as an
    ``asyncio.Task`` so the admin API handler can return immediately.

    Important: we create a **dedicated** ``AsyncClient`` per task instead
    of reusing the shared pool from ``proxy.get_client()``.  The shared
    client serialises non-streaming requests with an ``asyncio.Lock``,
    which would deadlock when the self-call triggers the proxy handler
    that itself needs the same lock to call the upstream provider.
    """
    try:
        # Use a per-task client to avoid lock contention / deadlock
        # with the shared proxy client.
        client = AsyncClient(timeout=float(_TASK_TIMEOUT))
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {internal_token}",
            }

            url = f"{base_url}{endpoint}"

            # Enforce per-task timeout so hung upstream calls don't
            # linger for the full _MAX_TASK_AGE cleanup window.
            resp = await asyncio.wait_for(
                request_bounded_response(
                    client,
                    "POST",
                    url,
                    json=payload,
                    headers=headers,
                    max_success_bytes=_TASK_RESPONSE_MAX_BYTES,
                    max_error_bytes=_TASK_RESPONSE_MAX_BYTES,
                ),
                timeout=_TASK_TIMEOUT,
            )

            store.finish(
                task_id,
                status="done",
                status_code=resp.status_code,
                body_bytes=resp.content,
            )
        finally:
            await client.aclose()
    except asyncio.CancelledError:
        store.finish(task_id, status="cancelled")
        raise
    except asyncio.TimeoutError:
        store.finish(
            task_id,
            status="error",
            status_code=504,
            error=f"Test timed out after {_TASK_TIMEOUT:g}s",
        )
    except UpstreamResponseTooLargeError:
        store.finish(
            task_id,
            status="error",
            status_code=502,
            error=(
                "Admin model-test upstream response exceeds "
                f"{_TASK_RESPONSE_MAX_BYTES} bytes"
            ),
        )
    except Exception as exc:
        store.finish(
            task_id,
            status="error",
            status_code=502,
            error=str(exc),
        )


def _get_gateway_config(request: Any) -> GatewayConfig | None:
    """Return the live GatewayConfig owned by this app instance."""
    return getattr(request.app, "gateway_config", None)


async def start_test(request: Any) -> Response:
    """Start an async model test.  Returns a task_id immediately.

    POST /admin/api/test
    Body: {endpoint: "/v1/...", payload: {...}}
    """
    body = _parse_json_object(request)
    if isinstance(body, Response):
        return body

    endpoint = body.get("endpoint")
    payload = body.get("payload")
    if not endpoint or not isinstance(payload, dict):
        return JSONResponse({"error": "Missing endpoint or payload"}, status_code=400)

    internal_token = getattr(request.app, "internal_token", "")
    if not internal_token:
        return JSONResponse({"error": "No internal token available"}, status_code=500)

    store: AdminTestTaskStore = request.app.admin_runtime_state.test_tasks
    task_id, capacity_error = store.reserve()
    if task_id is None:
        return JSONResponse({"error": capacity_error}, status_code=429)

    # Determine the base URL the gateway is listening on so the test
    # task can POST back to ourselves.
    host = getattr(request.app, "_bind_host", "127.0.0.1")
    port = getattr(request.app, "_bind_port", 28765)
    # Always use 127.0.0.1 for self-calls — even if bound to 0.0.0.0
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    base_url = f"http://{host}:{port}"

    asyncio_task = asyncio.create_task(
        _run_test_task(task_id, store, base_url, endpoint, payload, internal_token)
    )
    store.attach_task(task_id, asyncio_task)

    return JSONResponse({"task_id": task_id})


async def get_test_result(request: Any, task_id: str = "") -> Response:
    """Poll for a test task result.

    GET /admin/api/test/<task_id>
    """
    store: AdminTestTaskStore = request.app.admin_runtime_state.test_tasks
    result = store.get_public(task_id)
    if result is None:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return JSONResponse(result)


async def cancel_test(request: Any, task_id: str = "") -> Response:
    """Cancel a running test task.

    DELETE /admin/api/test/<task_id>
    """
    store: AdminTestTaskStore = request.app.admin_runtime_state.test_tasks
    if not store.cancel(task_id):
        return JSONResponse({"error": "Task not found"}, status_code=404)

    return JSONResponse({"ok": True})
