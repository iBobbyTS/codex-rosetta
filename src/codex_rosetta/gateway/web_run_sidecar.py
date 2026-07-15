"""Authenticated client contract for the optional ``web-run`` browser sidecar."""

from __future__ import annotations

from typing import Any, Protocol

from codex_rosetta._vendor.httpclient import AsyncClient

from .transport.http.transport import request_bounded_response

_MAX_SIDECAR_RESPONSE_BYTES = 1_000_000


class WebRunSidecarError(RuntimeError):
    """Base error returned by the browser sidecar client."""


class WebRunSidecarInvalidRequest(WebRunSidecarError):
    """The browser operation or reference is invalid."""


class WebRunSidecarNotImplemented(WebRunSidecarError):
    """The browser operation is recognized but unavailable."""


class WebRunBrowserClient(Protocol):
    """Minimal browser/PDF executor consumed by the Codex search bridge."""

    async def execute(
        self,
        *,
        session_id: str,
        operation: str,
        arguments: dict[str, Any],
    ) -> str:
        """Execute one scoped operation and return model-visible text."""


class WebRunSidecarHTTPClient:
    """Bounded bearer-authenticated HTTP client for the optional sidecar."""

    def __init__(self, base_url: str, token: str, *, timeout: float = 45.0) -> None:
        self._url = f"{base_url.rstrip('/')}/v1/execute"
        self._token = token
        self._timeout = timeout

    async def execute(
        self,
        *,
        session_id: str,
        operation: str,
        arguments: dict[str, Any],
    ) -> str:
        payload = {
            "session_id": session_id,
            "operation": operation,
            "arguments": arguments,
        }
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        async with AsyncClient(timeout=self._timeout) as client:
            try:
                response = await request_bounded_response(
                    client,
                    "POST",
                    self._url,
                    json=payload,
                    headers=headers,
                    max_success_bytes=_MAX_SIDECAR_RESPONSE_BYTES,
                    max_error_bytes=_MAX_SIDECAR_RESPONSE_BYTES,
                )
            except Exception as exc:
                raise WebRunSidecarError(
                    f"web-run sidecar request failed: {exc}"
                ) from exc

        try:
            body = response.json()
        except Exception as exc:
            raise WebRunSidecarError("web-run sidecar returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise WebRunSidecarError("web-run sidecar returned a non-object response")
        if response.status_code >= 400:
            message = _sidecar_error_message(body, response.status_code)
            if response.status_code in {400, 404, 422}:
                raise WebRunSidecarInvalidRequest(message)
            if response.status_code == 501:
                raise WebRunSidecarNotImplemented(message)
            raise WebRunSidecarError(message)
        output = body.get("output")
        if not isinstance(output, str):
            raise WebRunSidecarError(
                "web-run sidecar response is missing string 'output'"
            )
        return output


def _sidecar_error_message(body: dict[str, Any], status_code: int) -> str:
    detail = body.get("detail")
    if isinstance(detail, dict):
        detail = detail.get("message")
    if not isinstance(detail, str) or not detail.strip():
        detail = body.get("error")
    if not isinstance(detail, str) or not detail.strip():
        detail = f"web-run sidecar returned HTTP {status_code}"
    return detail.strip()


__all__ = [
    "WebRunBrowserClient",
    "WebRunSidecarError",
    "WebRunSidecarHTTPClient",
    "WebRunSidecarInvalidRequest",
    "WebRunSidecarNotImplemented",
]
