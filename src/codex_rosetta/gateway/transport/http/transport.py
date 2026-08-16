"""HTTP/SSE transport implementation.

Implements the :class:`~transport._base.UpstreamTransport` protocol for
HTTP REST + SSE streaming, backed by the vendored ``httpclient`` and ``sse``
modules.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from compression import zstd

from codex_rosetta._vendor.httpclient import (
    DEFAULT_MAX_REDIRECTS,
    HttpClientError,
    HttpResponseLimitError,
    StreamingResponse as HttpStreamingResponse,
)
from codex_rosetta._vendor.sse import AsyncEventSource, SSELimitError
from codex_rosetta.auto_detect import ProviderType
from codex_rosetta.gateway.headers import overlay_headers_case_insensitive

from .._base import (
    UpstreamConnectionError,
    UpstreamContentEncodingError,
    UpstreamProtocolError,
    UpstreamNetworkError,
    UpstreamResponse,
    UpstreamResponseTooLargeError,
    UpstreamSafetyError,
    UpstreamStream,
    UpstreamStreamLimitError,
)
from .._retry import _RetryPolicy
from ..provider_info import ProviderInfo
from .client_pool import DEFAULT_HTTP_TIMEOUT_SECONDS, HttpClientPool

logger = logging.getLogger("codex-rosetta-gateway")

MAX_UPSTREAM_SUCCESS_BODY_BYTES = 50_000_000
MAX_UPSTREAM_ERROR_BODY_BYTES = 1_000_000
MAX_UPSTREAM_SSE_LINE_BYTES = 1024 * 1024
MAX_UPSTREAM_SSE_EVENT_BYTES = 8 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
DEFAULT_UPSTREAM_STREAM_OPEN_TIMEOUT_SECONDS = 10 * 60.0
DEFAULT_UPSTREAM_STREAM_IDLE_TIMEOUT_SECONDS = 5 * 60.0
DEFAULT_UPSTREAM_CLOSE_TIMEOUT_SECONDS = 5.0
_CDN_502_MARKERS = (
    "网站请求超时".encode(),
    "回源请求被中断".encode(),
    b">502<",
)
_RESPONSES_TARGETS = frozenset({"openai_responses", "open_responses"})
_HTTP_502_RETRY = _RetryPolicy((1.0, 2.0, 4.0, 8.0, 16.0))


class _ClosedSyntheticResponse:
    """Minimal closed response backing a pre-output synthetic stream error."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    async def aclose(self) -> None:
        return None


def _consume_background_task_result(task: asyncio.Task[Any]) -> None:
    """Drain a detached cleanup task without surfacing its terminal exception."""
    try:
        task.result()
    except BaseException:
        pass


async def _await_with_deadline(
    awaitable: Any,
    *,
    timeout: float,
    timeout_message: str,
) -> Any:
    """Wait for one operation without waiting indefinitely for cancellation cleanup."""
    task = asyncio.create_task(awaitable)
    try:
        done, _pending = await asyncio.wait({task}, timeout=timeout)
    except BaseException:
        task.cancel()
        task.add_done_callback(_consume_background_task_result)
        raise
    if task in done:
        return task.result()

    task.cancel()
    task.add_done_callback(_consume_background_task_result)
    raise UpstreamNetworkError(timeout_message)


@dataclass(frozen=True)
class BoundedHttpResponse:
    """Closed auxiliary HTTP response whose body passed Gateway limits."""

    status_code: int
    headers: dict[str, str]
    content: bytes

    @property
    def text(self) -> str:
        """Decode the bounded body for diagnostics."""
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        """Decode the bounded body as JSON."""
        return json.loads(self.content)


def _reject_non_finite_json_constant(value: str) -> Any:
    """Reject the non-standard numeric constants accepted by ``json.loads``."""
    raise ValueError(f"Non-standard JSON constant: {value}")


def _parse_finite_json_float(value: str) -> float:
    """Parse one standard JSON float without permitting overflow to infinity."""
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("JSON number is not finite")
    return parsed


def _parse_strict_utf8_json(raw_content: bytes) -> Any:
    """Parse standard JSON after strict UTF-8 decoding."""
    return json.loads(
        raw_content.decode("utf-8"),
        parse_constant=_reject_non_finite_json_constant,
        parse_float=_parse_finite_json_float,
    )


def _stream_limit_error(kind: str, limit: int, actual: int) -> UpstreamStreamLimitError:
    """Build the stable Gateway error for an upstream stream overflow."""
    return UpstreamStreamLimitError(
        f"Upstream SSE {kind} exceeds {limit} bytes (observed {actual} bytes)"
    )


def _header_safety_error(exc: HttpResponseLimitError) -> UpstreamSafetyError:
    """Map a vendored response header/trailer overflow to a stable safety error."""
    return UpstreamSafetyError(f"Upstream response {exc.kind} exceeds its safety limit")


class _SSEWireLimitTracker:
    """Track SSE line and event sizes without changing raw passthrough bytes."""

    def __init__(self, *, max_line_bytes: int, max_event_bytes: int) -> None:
        self._max_line_bytes = max_line_bytes
        self._max_event_bytes = max_event_bytes
        self._line = bytearray()
        self._event_bytes = 0
        self._has_data = False
        self._first_line = True

    def feed(self, chunk: bytes) -> None:
        """Consume one raw body chunk and raise on a line or event overflow."""
        self._line.extend(chunk)
        while True:
            newline = self._line.find(b"\n")
            if newline < 0:
                break
            wire_size = newline + 1
            self._check_line(wire_size)
            line = bytes(self._line[:newline])
            del self._line[:wire_size]
            self._consume_line(line.rstrip(b"\r"))
        self._check_line(len(self._line))

    def finish(self) -> None:
        """Validate a final unterminated line at end-of-stream."""
        if not self._line:
            return
        self._check_line(len(self._line))
        self._consume_line(bytes(self._line).rstrip(b"\r"))
        self._line.clear()

    def _check_line(self, actual: int) -> None:
        if actual > self._max_line_bytes:
            raise _stream_limit_error("line", self._max_line_bytes, actual)

    def _consume_line(self, line: bytes) -> None:
        if self._first_line:
            self._first_line = False
            if line.startswith(b"\xef\xbb\xbf"):
                line = line[3:]
        if not line:
            self._event_bytes = 0
            self._has_data = False
            return
        if line == b"data":
            value = b""
        elif line.startswith(b"data:"):
            value = line[5:]
            if value.startswith(b" "):
                value = value[1:]
        else:
            return
        event_bytes = self._event_bytes + len(value)
        if self._has_data:
            event_bytes += 1
        if event_bytes > self._max_event_bytes:
            raise _stream_limit_error("event", self._max_event_bytes, event_bytes)
        self._event_bytes = event_bytes
        self._has_data = True


def _force_identity_encoding(headers: dict[str, str]) -> None:
    for key in tuple(headers):
        if key.lower() == "accept-encoding":
            del headers[key]
    headers["Accept-Encoding"] = "identity"


def _remove_headers_case_insensitive(
    headers: dict[str, str], names: set[str] | frozenset[str]
) -> None:
    for key in tuple(headers):
        if key.lower() in names:
            del headers[key]


def _request_payload(
    provider_info: ProviderInfo,
    target_provider: ProviderType,
    req_body: dict[str, Any],
    headers: dict[str, str],
    *,
    wire_body: bytes | None = None,
    wire_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the final request bytes for one upstream protocol call."""

    if target_provider not in _RESPONSES_TARGETS:
        return {"json": req_body}

    encoding = provider_info.request_encoding
    if encoding is None:
        raise ValueError("Responses Provider request_encoding is required")

    if encoding == "passthrough" and wire_body is not None:
        if wire_headers:
            overlay_headers_case_insensitive(headers, wire_headers)
        _force_identity_encoding(headers)
        overlay_headers_case_insensitive(headers, provider_info.auth_headers())
        return {"data": wire_body}

    _remove_headers_case_insensitive(
        headers,
        frozenset({"content-encoding", "content-length", "x-oai-attestation"}),
    )
    if encoding == "zstd":
        serialized = json.dumps(
            req_body,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        headers["Content-Encoding"] = "zstd"
        return {"data": zstd.compress(serialized)}
    return {"json": req_body}


async def _enforce_identity_encoding(resp: HttpStreamingResponse) -> None:
    encoding = str(resp.headers.get("content-encoding", "")).strip().lower()
    if not encoding or encoding == "identity":
        return
    await resp.aclose()
    raise UpstreamContentEncodingError(
        "Upstream response used unsupported Content-Encoding; identity required"
    )


async def _enforce_content_length(
    resp: HttpStreamingResponse,
    max_bytes: int,
) -> None:
    raw_length = resp.headers.get("content-length")
    if raw_length is None:
        return
    try:
        content_length = int(raw_length)
    except TypeError, ValueError:
        await resp.aclose()
        raise UpstreamConnectionError(
            "Upstream response has an invalid Content-Length"
        ) from None
    if content_length < 0 or content_length > max_bytes:
        await resp.aclose()
        raise UpstreamResponseTooLargeError(
            f"Upstream response body exceeds {max_bytes} bytes"
        )


async def _read_bounded_body(
    resp: HttpStreamingResponse,
    max_bytes: int,
) -> bytes:
    """Incrementally read one identity-encoded body and always close it."""
    await _enforce_identity_encoding(resp)
    await _enforce_content_length(resp, max_bytes)
    chunks: list[bytes] = []
    total = 0
    try:
        read_size = min(_READ_CHUNK_BYTES, max_bytes + 1)
        async for chunk in resp.aiter_bytes(chunk_size=read_size):
            total += len(chunk)
            if total > max_bytes:
                raise UpstreamResponseTooLargeError(
                    f"Upstream response body exceeds {max_bytes} bytes"
                )
            chunks.append(chunk)
    except UpstreamConnectionError:
        raise
    except HttpResponseLimitError as exc:
        raise _header_safety_error(exc) from exc
    except HttpClientError as exc:
        raise UpstreamConnectionError(str(exc)) from exc
    finally:
        await resp.aclose()
    return b"".join(chunks)


def _is_base_url_rotation_trigger(status_code: int, content: bytes) -> bool:
    """Match the frozen real-502 or observed CDN-page trigger whitelist."""
    return status_code == 502 or all(marker in content for marker in _CDN_502_MARKERS)


def _all_domains_502(count: int) -> bytes:
    return json.dumps(
        {
            "error": {
                "message": f"All {count} domains responded with HTTP 502",
                "type": "upstream_error",
            }
        },
        separators=(",", ":"),
    ).encode()


def _all_credentials_503(count: int) -> bytes:
    return json.dumps(
        {
            "error": {
                "message": f"All {count} credentials responded with HTTP 503",
                "type": "upstream_error",
            }
        },
        separators=(",", ":"),
    ).encode()


async def _claim_url_rotation_immediately(
    provider_info: ProviderInfo, observation: tuple[str, int]
) -> bool:
    """Keep URL leadership only when the claim did not wait on another leader."""
    claimed, waited = await provider_info.claim_url_rotation_observation(observation)
    if claimed and waited:
        await provider_info.publish_url_rotation()
    return claimed and not waited


async def request_bounded_response(
    client: Any,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_success_bytes: int | None = None,
    max_error_bytes: int | None = None,
    allow_redirects: bool = False,
    **kwargs: Any,
) -> BoundedHttpResponse:
    """Send one auxiliary request through the primary response safety envelope."""
    if max_success_bytes is None:
        max_success_bytes = MAX_UPSTREAM_SUCCESS_BODY_BYTES
    if max_error_bytes is None:
        max_error_bytes = MAX_UPSTREAM_ERROR_BODY_BYTES
    for name, value in (
        ("max_success_bytes", max_success_bytes),
        ("max_error_bytes", max_error_bytes),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    request_headers = dict(headers or {})
    _force_identity_encoding(request_headers)
    kwargs["follow_redirects"] = allow_redirects
    if allow_redirects:
        kwargs["max_redirects"] = DEFAULT_MAX_REDIRECTS
    try:
        resp = await client.request(
            method,
            url,
            headers=request_headers,
            stream=True,
            **kwargs,
        )
    except HttpResponseLimitError as exc:
        raise _header_safety_error(exc) from exc
    except (HttpClientError, ValueError) as exc:
        raise UpstreamConnectionError(str(exc)) from exc
    if not isinstance(resp, HttpStreamingResponse):
        raise UpstreamConnectionError("Auxiliary HTTP request did not return a stream")
    max_bytes = max_success_bytes if 200 <= resp.status_code < 300 else max_error_bytes
    raw_content = await _read_bounded_body(resp, max_bytes)
    return BoundedHttpResponse(
        status_code=resp.status_code,
        headers={str(key): str(value) for key, value in resp.headers.items()},
        content=raw_content,
    )


# ---------------------------------------------------------------------------
# Upstream request assembly
# ---------------------------------------------------------------------------


def _prepare_upstream(
    target_provider: ProviderType,
    provider_info: ProviderInfo,
    provider_request: dict[str, Any],
    model: str,
    *,
    stream: bool,
    credential_headers: dict[str, str],
    extra_headers: dict[str, str] | None = None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Return ``(url, headers, body)`` ready for the upstream HTTP call."""
    url = provider_info.upstream_url(model, stream=stream)
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        overlay_headers_case_insensitive(headers, extra_headers)
    _force_identity_encoding(headers)
    overlay_headers_case_insensitive(headers, credential_headers)

    body = dict(provider_request)

    # Inject stream flag into the body for providers that use it
    if stream:
        if target_provider in ("openai_chat",):
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        elif target_provider in ("openai_responses", "open_responses", "anthropic"):
            body["stream"] = True
        # Google streaming is signaled via URL, not body

    return url, headers, body


# ---------------------------------------------------------------------------
# Streaming response wrapper
# ---------------------------------------------------------------------------


class HttpUpstreamStream(UpstreamStream):
    """Streaming response backed by HTTP/SSE.

    Wraps a :class:`~httpclient.StreamingResponse` and uses the vendored
    :class:`~sse.AsyncEventSource` to parse SSE events into JSON chunks.
    """

    def __init__(
        self,
        resp: HttpStreamingResponse,
        *,
        error_text: str | None = None,
        prefetched_raw: bytes | None = None,
        response_closed: bool = False,
        idle_timeout: float = DEFAULT_UPSTREAM_STREAM_IDLE_TIMEOUT_SECONDS,
        close_timeout: float = DEFAULT_UPSTREAM_CLOSE_TIMEOUT_SECONDS,
    ) -> None:
        self.status_code = resp.status_code
        self._resp = resp
        self._error_text = error_text
        self._prefetched_raw = prefetched_raw
        self._closed = response_closed
        self._idle_timeout = idle_timeout
        self._close_timeout = close_timeout

    async def _next_with_idle_timeout(self, iterator: Any) -> Any:
        """Read one upstream item and fail fast when the route becomes a black hole."""
        try:
            return await _await_with_deadline(
                anext(iterator),
                timeout=self._idle_timeout,
                timeout_message=(
                    "Upstream stream produced no data for "
                    f"{self._idle_timeout:g} seconds"
                ),
            )
        except UpstreamNetworkError:
            await self.close()
            raise
        except HttpResponseLimitError:
            raise
        except HttpClientError as exc:
            await self.close()
            raise UpstreamNetworkError(str(exc)) from exc

    async def _iter_lines_with_idle_timeout(self) -> AsyncIterator[str]:
        lines = self._resp.aiter_lines(max_line_bytes=MAX_UPSTREAM_SSE_LINE_BYTES)
        while True:
            try:
                yield await self._next_with_idle_timeout(lines)
            except StopAsyncIteration:
                return

    async def read_error(self) -> str:
        """Read one bounded error body as a string and close the response."""
        if self._error_text is not None:
            return self._error_text
        self._closed = True
        raw = await _read_bounded_body(self._resp, MAX_UPSTREAM_ERROR_BODY_BYTES)
        return raw.decode("utf-8", errors="replace")

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override]
        """Yield parsed JSON chunks from the upstream SSE stream.

        Uses the vendored W3C-compliant SSE parser.  Detects OpenAI's
        ``[DONE]`` marker and stops iteration.
        """
        if self._prefetched_raw is not None:
            raise UpstreamProtocolError("Upstream SSE data is not valid JSON")
        try:
            async for event in AsyncEventSource(
                self._iter_lines_with_idle_timeout(),
                max_event_bytes=MAX_UPSTREAM_SSE_EVENT_BYTES,
            ):
                if event.data == "[DONE]":
                    break
                if not event.data:
                    continue
                try:
                    yield json.loads(event.data)
                except json.JSONDecodeError:
                    await self.close()
                    raise UpstreamProtocolError(
                        "Upstream SSE data is not valid JSON"
                    ) from None
        except HttpResponseLimitError as exc:
            await self.close()
            if exc.kind.startswith("header"):
                raise _header_safety_error(exc) from exc
            raise _stream_limit_error(exc.kind, exc.limit, exc.actual) from exc
        except SSELimitError as exc:
            await self.close()
            raise _stream_limit_error(exc.kind, exc.limit, exc.actual) from exc
        except asyncio.CancelledError, GeneratorExit:
            await self.close()
            raise

    def aiter_raw_bytes(self) -> AsyncIterator[bytes]:
        """Yield raw upstream response bytes without parsing SSE events."""

        async def bounded_raw_stream() -> AsyncIterator[bytes]:
            if self._prefetched_raw is not None:
                yield self._prefetched_raw
                return
            tracker = _SSEWireLimitTracker(
                max_line_bytes=MAX_UPSTREAM_SSE_LINE_BYTES,
                max_event_bytes=MAX_UPSTREAM_SSE_EVENT_BYTES,
            )
            try:
                raw_chunks = self._resp.aiter_bytes(chunk_size=_READ_CHUNK_BYTES)
                while True:
                    try:
                        chunk = await self._next_with_idle_timeout(raw_chunks)
                    except StopAsyncIteration:
                        break
                    tracker.feed(chunk)
                    yield chunk
                tracker.finish()
            except asyncio.CancelledError, GeneratorExit:
                await self.close()
                raise
            except UpstreamStreamLimitError:
                await self.close()
                raise
            except HttpResponseLimitError as exc:
                await self.close()
                raise _header_safety_error(exc) from exc

        return bounded_raw_stream()

    async def close(self) -> None:
        """Close the underlying HTTP streaming response."""
        if self._closed:
            return
        self._closed = True
        try:
            await _await_with_deadline(
                self._resp.aclose(),
                timeout=self._close_timeout,
                timeout_message=(
                    "Timed out closing upstream stream after "
                    f"{self._close_timeout:g} seconds"
                ),
            )
        except UpstreamConnectionError as exc:
            logger.warning("%s", exc)


# ---------------------------------------------------------------------------
# HttpTransport
# ---------------------------------------------------------------------------


class HttpTransport:
    """Upstream transport implementation for HTTP REST + SSE streaming.

    Implements the :class:`~transport._base.UpstreamTransport` protocol.
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        stream_open_timeout: float = DEFAULT_UPSTREAM_STREAM_OPEN_TIMEOUT_SECONDS,
        stream_idle_timeout: float = DEFAULT_UPSTREAM_STREAM_IDLE_TIMEOUT_SECONDS,
        close_timeout: float = DEFAULT_UPSTREAM_CLOSE_TIMEOUT_SECONDS,
        retry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._pool = HttpClientPool(timeout=timeout)
        self._stream_open_timeout = stream_open_timeout
        self._stream_idle_timeout = stream_idle_timeout
        self._close_timeout = close_timeout
        self._retry_sleep = retry_sleep

    async def _advance_credential(
        self,
        provider_info: ProviderInfo,
        observed: str,
    ) -> UpstreamResponse | None:
        """Advance one provider credential after a literal upstream 503."""
        if not await provider_info.claim_credential_rotation(observed):
            return None
        try:
            provider_info.mark_credential_failed(observed)
            next_credential = provider_info.next_available_credential(observed)
            if next_credential is None:
                return UpstreamResponse(
                    status_code=503,
                    body=None,
                    raw_content=_all_credentials_503(len(provider_info.credential_ids)),
                )
            await provider_info.select_credential(next_credential)
            return None
        finally:
            await provider_info.publish_credential_rotation()

    async def _send_request_observed(
        self,
        provider_info: ProviderInfo,
        target_provider: ProviderType,
        body: dict[str, Any],
        model: str,
        *,
        extra_headers: dict[str, str] | None,
    ) -> tuple[UpstreamResponse, tuple[str, int], str]:
        observation = provider_info.observe_url_rotation()
        credential_id, credential_headers = provider_info._credential_snapshot()
        response = await self._send_request_once(
            provider_info,
            target_provider,
            body,
            model,
            extra_headers=extra_headers,
            credential_headers=credential_headers,
        )
        return response, observation, credential_id

    async def _send_streaming_observed(
        self,
        provider_info: ProviderInfo,
        target_provider: ProviderType,
        body: dict[str, Any],
        model: str,
        *,
        extra_headers: dict[str, str] | None,
        wire_body: bytes | None,
        wire_headers: dict[str, str] | None,
        preserve_failover_error_body: bool,
    ) -> tuple[HttpUpstreamStream, bool, tuple[str, int], str]:
        observation = provider_info.observe_url_rotation()
        credential_id, credential_headers = provider_info._credential_snapshot()
        result, trigger = await self._send_streaming_once(
            provider_info,
            target_provider,
            body,
            model,
            extra_headers=extra_headers,
            wire_body=wire_body,
            wire_headers=wire_headers,
            preserve_failover_error_body=preserve_failover_error_body,
            credential_headers=credential_headers,
        )
        return result, trigger, observation, credential_id

    async def send_request(
        self,
        provider_info: ProviderInfo,
        target_provider: ProviderType,
        body: dict[str, Any],
        model: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> UpstreamResponse:
        """Send a non-streaming request and return the full response."""
        single_attempt = await provider_info.wait_for_url_rotation()
        await provider_info.wait_for_credential_rotation()
        while True:
            if not provider_info.has_available_base_url():
                return UpstreamResponse(
                    status_code=502,
                    body=None,
                    raw_content=_all_domains_502(len(provider_info.base_urls)),
                )
            if not provider_info.has_available_credential():
                return UpstreamResponse(
                    status_code=503,
                    body=None,
                    raw_content=_all_credentials_503(len(provider_info.credential_ids)),
                )
            (
                response,
                url_observation,
                observed_credential,
            ) = await self._send_request_observed(
                provider_info,
                target_provider,
                body,
                model,
                extra_headers=extra_headers,
            )
            observed = url_observation[0]
            if single_attempt and response.status_code == 502:
                return response
            if response.status_code == 503:
                exhausted = await self._advance_credential(
                    provider_info, observed_credential
                )
                if exhausted is not None:
                    return exhausted
                continue
            if not _is_base_url_rotation_trigger(
                response.status_code, response.raw_content
            ):
                return response
            if not await _claim_url_rotation_immediately(
                provider_info, url_observation
            ):
                single_attempt = True
                continue
            try:
                while True:
                    (
                        response,
                        url_observation,
                        observed_credential,
                    ) = await _HTTP_502_RETRY.run(
                        (response, url_observation, observed_credential),
                        lambda: self._send_request_observed(
                            provider_info,
                            target_provider,
                            body,
                            model,
                            extra_headers=extra_headers,
                        ),
                        lambda item: not single_attempt and item[0].status_code == 502,
                        sleep=self._retry_sleep,
                    )
                    observed = url_observation[0]
                    if single_attempt and response.status_code == 502:
                        return response
                    if response.status_code == 503:
                        exhausted = await self._advance_credential(
                            provider_info, observed_credential
                        )
                        if exhausted is not None:
                            return exhausted
                        (
                            response,
                            url_observation,
                            observed_credential,
                        ) = await self._send_request_observed(
                            provider_info,
                            target_provider,
                            body,
                            model,
                            extra_headers=extra_headers,
                        )
                        observed = url_observation[0]
                        continue
                    if not _is_base_url_rotation_trigger(
                        response.status_code, response.raw_content
                    ):
                        return response
                    provider_info.mark_base_url_failed(observed)
                    next_url = provider_info.next_available_base_url(observed)
                    if next_url is None:
                        return UpstreamResponse(
                            status_code=502,
                            body=None,
                            raw_content=_all_domains_502(len(provider_info.base_urls)),
                        )
                    await provider_info.select_base_url(next_url)
                    (
                        response,
                        url_observation,
                        observed_credential,
                    ) = await self._send_request_observed(
                        provider_info,
                        target_provider,
                        body,
                        model,
                        extra_headers=extra_headers,
                    )
                    observed = url_observation[0]
            finally:
                await provider_info.publish_url_rotation()

    async def _send_request_once(
        self,
        provider_info: ProviderInfo,
        target_provider: ProviderType,
        body: dict[str, Any],
        model: str,
        *,
        extra_headers: dict[str, str] | None,
        credential_headers: dict[str, str],
    ) -> UpstreamResponse:
        url, headers, req_body = _prepare_upstream(
            target_provider,
            provider_info,
            body,
            model,
            stream=False,
            credential_headers=credential_headers,
            extra_headers=extra_headers,
        )
        client = self._pool.get(
            provider_info.proxy_url,
            allow_redirects=provider_info.allow_redirects,
        )
        try:
            resp = await client.post(
                url,
                headers=headers,
                stream=True,
                **_request_payload(provider_info, target_provider, req_body, headers),
            )
        except HttpResponseLimitError as exc:
            raise _header_safety_error(exc) from exc
        except (HttpClientError, ValueError) as exc:
            raise UpstreamConnectionError(str(exc)) from exc
        assert isinstance(resp, HttpStreamingResponse)
        if resp.status_code == 502:
            await resp.aclose()
            return UpstreamResponse(status_code=502, body=None, raw_content=b"")
        if resp.status_code == 503:
            await resp.aclose()
            return UpstreamResponse(status_code=503, body=None, raw_content=b"")
        max_bytes = (
            MAX_UPSTREAM_ERROR_BODY_BYTES
            if resp.status_code >= 400
            else MAX_UPSTREAM_SUCCESS_BODY_BYTES
        )
        raw_content = await _read_bounded_body(resp, max_bytes)
        return UpstreamResponse(
            status_code=resp.status_code,
            body=(
                json.loads(raw_content)
                if resp.status_code < 400
                and not _is_base_url_rotation_trigger(resp.status_code, raw_content)
                else None
            ),
            raw_content=raw_content,
        )

    async def send_streaming(
        self,
        provider_info: ProviderInfo,
        target_provider: ProviderType,
        body: dict[str, Any],
        model: str,
        *,
        extra_headers: dict[str, str] | None = None,
        wire_body: bytes | None = None,
        wire_headers: dict[str, str] | None = None,
        allow_failover: bool = True,
    ) -> HttpUpstreamStream:
        """Send a streaming request and return an async chunk iterator."""
        single_attempt = await provider_info.wait_for_url_rotation()
        await provider_info.wait_for_credential_rotation()
        while True:
            if not provider_info.has_available_base_url():
                message = _all_domains_502(len(provider_info.base_urls))
                return HttpUpstreamStream(
                    cast(Any, _ClosedSyntheticResponse(502)),
                    error_text=message.decode(),
                    response_closed=True,
                    idle_timeout=self._stream_idle_timeout,
                    close_timeout=self._close_timeout,
                )
            if not provider_info.has_available_credential():
                message = _all_credentials_503(len(provider_info.credential_ids))
                return HttpUpstreamStream(
                    cast(Any, _ClosedSyntheticResponse(503)),
                    error_text=message.decode(),
                    response_closed=True,
                    idle_timeout=self._stream_idle_timeout,
                    close_timeout=self._close_timeout,
                )
            (
                result,
                trigger,
                url_observation,
                observed_credential,
            ) = await self._send_streaming_observed(
                provider_info,
                target_provider,
                body,
                model,
                extra_headers=extra_headers,
                wire_body=wire_body,
                wire_headers=wire_headers,
                preserve_failover_error_body=not allow_failover,
            )
            observed = url_observation[0]
            if not allow_failover or (single_attempt and result.status_code == 502):
                return result
            if result.status_code == 503:
                exhausted = await self._advance_credential(
                    provider_info, observed_credential
                )
                if exhausted is not None:
                    return HttpUpstreamStream(
                        cast(Any, _ClosedSyntheticResponse(503)),
                        error_text=exhausted.raw_content.decode(),
                        response_closed=True,
                        idle_timeout=self._stream_idle_timeout,
                        close_timeout=self._close_timeout,
                    )
                continue
            if not trigger:
                return result
            if not await _claim_url_rotation_immediately(
                provider_info, url_observation
            ):
                single_attempt = True
                continue
            try:
                while True:
                    (
                        result,
                        trigger,
                        url_observation,
                        observed_credential,
                    ) = await _HTTP_502_RETRY.run(
                        (result, trigger, url_observation, observed_credential),
                        lambda: self._send_streaming_observed(
                            provider_info,
                            target_provider,
                            body,
                            model,
                            extra_headers=extra_headers,
                            wire_body=wire_body,
                            wire_headers=wire_headers,
                            preserve_failover_error_body=False,
                        ),
                        lambda item: not single_attempt and item[0].status_code == 502,
                        sleep=self._retry_sleep,
                    )
                    observed = url_observation[0]
                    if single_attempt and result.status_code == 502:
                        return result
                    if result.status_code == 503:
                        exhausted = await self._advance_credential(
                            provider_info, observed_credential
                        )
                        if exhausted is not None:
                            return HttpUpstreamStream(
                                cast(Any, _ClosedSyntheticResponse(503)),
                                error_text=exhausted.raw_content.decode(),
                                response_closed=True,
                                idle_timeout=self._stream_idle_timeout,
                                close_timeout=self._close_timeout,
                            )
                        (
                            result,
                            trigger,
                            url_observation,
                            observed_credential,
                        ) = await self._send_streaming_observed(
                            provider_info,
                            target_provider,
                            body,
                            model,
                            extra_headers=extra_headers,
                            wire_body=wire_body,
                            wire_headers=wire_headers,
                            preserve_failover_error_body=False,
                        )
                        observed = url_observation[0]
                        continue
                    if not trigger:
                        return result
                    provider_info.mark_base_url_failed(observed)
                    next_url = provider_info.next_available_base_url(observed)
                    if next_url is None:
                        message = _all_domains_502(len(provider_info.base_urls))
                        return HttpUpstreamStream(
                            cast(Any, _ClosedSyntheticResponse(502)),
                            error_text=message.decode(),
                            response_closed=True,
                            idle_timeout=self._stream_idle_timeout,
                            close_timeout=self._close_timeout,
                        )
                    await provider_info.select_base_url(next_url)
                    (
                        result,
                        trigger,
                        url_observation,
                        observed_credential,
                    ) = await self._send_streaming_observed(
                        provider_info,
                        target_provider,
                        body,
                        model,
                        extra_headers=extra_headers,
                        wire_body=wire_body,
                        wire_headers=wire_headers,
                        preserve_failover_error_body=False,
                    )
                    observed = url_observation[0]
            finally:
                await provider_info.publish_url_rotation()

    async def _send_streaming_once(
        self,
        provider_info: ProviderInfo,
        target_provider: ProviderType,
        body: dict[str, Any],
        model: str,
        *,
        extra_headers: dict[str, str] | None,
        wire_body: bytes | None,
        wire_headers: dict[str, str] | None,
        preserve_failover_error_body: bool,
        credential_headers: dict[str, str],
    ) -> tuple[HttpUpstreamStream, bool]:
        url, headers, req_body = _prepare_upstream(
            target_provider,
            provider_info,
            body,
            model,
            stream=True,
            credential_headers=credential_headers,
            extra_headers=extra_headers,
        )
        request_payload = _request_payload(
            provider_info,
            target_provider,
            req_body,
            headers,
            wire_body=wire_body,
            wire_headers=wire_headers,
        )
        client = self._pool.get(
            provider_info.proxy_url,
            allow_redirects=provider_info.allow_redirects,
        )
        try:
            resp = await _await_with_deadline(
                client.post(
                    url,
                    headers=headers,
                    stream=True,
                    timeout=self._stream_open_timeout,
                    **request_payload,
                ),
                timeout=self._stream_open_timeout,
                timeout_message=(
                    "Upstream did not open a streaming response within "
                    f"{self._stream_open_timeout:g} seconds"
                ),
            )
        except HttpResponseLimitError as exc:
            raise _header_safety_error(exc) from exc
        except (HttpClientError, ValueError) as exc:
            raise UpstreamConnectionError(str(exc)) from exc

        assert isinstance(resp, HttpStreamingResponse)
        if resp.status_code in (502, 503):
            error_text = ""
            if preserve_failover_error_body:
                raw_error = await _read_bounded_body(
                    resp,
                    MAX_UPSTREAM_ERROR_BODY_BYTES,
                )
                error_text = raw_error.decode("utf-8", errors="replace")
            else:
                await resp.aclose()
            return (
                HttpUpstreamStream(
                    resp,
                    error_text=error_text,
                    response_closed=True,
                    idle_timeout=self._stream_idle_timeout,
                    close_timeout=self._close_timeout,
                ),
                resp.status_code == 502,
            )
        await _enforce_identity_encoding(resp)
        if resp.status_code >= 400:
            raw_error = await _read_bounded_body(
                resp,
                MAX_UPSTREAM_ERROR_BODY_BYTES,
            )
            stream = HttpUpstreamStream(
                resp,
                error_text=raw_error.decode("utf-8", errors="replace"),
                response_closed=True,
                idle_timeout=self._stream_idle_timeout,
                close_timeout=self._close_timeout,
            )
            return stream, _is_base_url_rotation_trigger(resp.status_code, raw_error)
        content_type = str(resp.headers.get("content-type", "")).lower()
        if "text/html" in content_type:
            raw_content = await _read_bounded_body(resp, MAX_UPSTREAM_ERROR_BODY_BYTES)
            if _is_base_url_rotation_trigger(resp.status_code, raw_content):
                return (
                    HttpUpstreamStream(
                        resp,
                        prefetched_raw=raw_content,
                        response_closed=True,
                        idle_timeout=self._stream_idle_timeout,
                        close_timeout=self._close_timeout,
                    ),
                    True,
                )
            return (
                HttpUpstreamStream(
                    resp,
                    prefetched_raw=raw_content,
                    response_closed=True,
                    idle_timeout=self._stream_idle_timeout,
                    close_timeout=self._close_timeout,
                ),
                False,
            )
        return (
            HttpUpstreamStream(
                resp,
                idle_timeout=self._stream_idle_timeout,
                close_timeout=self._close_timeout,
            ),
            False,
        )

    async def send_passthrough(
        self,
        provider_info: ProviderInfo,
        url: str,
        body: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
        method: str = "POST",
    ) -> UpstreamResponse:
        """Send a raw passthrough request — no URL template or stream flags.

        Used for non-conversion endpoints (model listing, reranking, etc.).
        """
        await provider_info.wait_for_url_rotation()
        await provider_info.wait_for_credential_rotation()
        while True:
            if not provider_info.has_available_base_url():
                return UpstreamResponse(
                    status_code=502,
                    body=None,
                    raw_content=_all_domains_502(len(provider_info.base_urls)),
                )
            if not provider_info.has_available_credential():
                return UpstreamResponse(
                    status_code=503,
                    body=None,
                    raw_content=_all_credentials_503(len(provider_info.credential_ids)),
                )
            observed = provider_info.base_url
            observed_credential = provider_info.current_credential_id
            response = await self._send_passthrough_once(
                provider_info,
                url,
                body,
                extra_headers=extra_headers,
                method=method,
            )
            if response.status_code == 503:
                exhausted = await self._advance_credential(
                    provider_info, observed_credential
                )
                if exhausted is not None:
                    return exhausted
                continue
            if not _is_base_url_rotation_trigger(
                response.status_code, response.raw_content
            ):
                return response
            if not await provider_info.claim_url_rotation(observed):
                continue
            try:
                provider_info.mark_base_url_failed(observed)
                advance_url = True
                while True:
                    if advance_url:
                        next_url = provider_info.next_available_base_url(observed)
                        if next_url is None:
                            return UpstreamResponse(
                                status_code=502,
                                body=None,
                                raw_content=_all_domains_502(
                                    len(provider_info.base_urls)
                                ),
                            )
                        await provider_info.select_base_url(next_url)
                        observed = next_url
                    advance_url = True
                    observed_credential = provider_info.current_credential_id
                    response = await self._send_passthrough_once(
                        provider_info,
                        url,
                        body,
                        extra_headers=extra_headers,
                        method=method,
                    )
                    if response.status_code == 503:
                        exhausted = await self._advance_credential(
                            provider_info, observed_credential
                        )
                        if exhausted is not None:
                            return exhausted
                        advance_url = False
                        continue
                    if not _is_base_url_rotation_trigger(
                        response.status_code, response.raw_content
                    ):
                        return response
                    provider_info.mark_base_url_failed(observed)
            finally:
                await provider_info.publish_url_rotation()

    async def _send_passthrough_once(
        self,
        provider_info: ProviderInfo,
        url: str,
        body: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None,
        method: str,
    ) -> UpstreamResponse:
        headers = {"Content-Type": "application/json"}
        if extra_headers:
            overlay_headers_case_insensitive(headers, extra_headers)
        _force_identity_encoding(headers)
        overlay_headers_case_insensitive(headers, provider_info.auth_headers())

        client = self._pool.get(
            provider_info.proxy_url,
            allow_redirects=provider_info.allow_redirects,
        )
        try:
            request_url = provider_info.current_url_for(url)
            request_kwargs: dict[str, Any] = {
                "headers": headers,
                "stream": True,
            }
            if method == "POST":
                request_kwargs["json"] = body
                request_method = client.post
            elif method == "GET":
                request_method = client.get
            else:
                raise ValueError("Passthrough method must be GET or POST")
            resp = await request_method(request_url, **request_kwargs)
        except HttpResponseLimitError as exc:
            raise _header_safety_error(exc) from exc
        except (HttpClientError, ValueError) as exc:
            raise UpstreamConnectionError(str(exc)) from exc

        assert isinstance(resp, HttpStreamingResponse)
        if resp.status_code == 502:
            await resp.aclose()
            return UpstreamResponse(status_code=502, body=None, raw_content=b"")
        if resp.status_code == 503:
            await resp.aclose()
            return UpstreamResponse(status_code=503, body=None, raw_content=b"")
        max_bytes = (
            MAX_UPSTREAM_ERROR_BODY_BYTES
            if resp.status_code >= 400
            else MAX_UPSTREAM_SUCCESS_BODY_BYTES
        )
        raw_content = await _read_bounded_body(resp, max_bytes)
        if _is_base_url_rotation_trigger(resp.status_code, raw_content):
            return UpstreamResponse(
                status_code=resp.status_code,
                body=None,
                raw_content=raw_content,
            )
        if 200 <= resp.status_code < 300:
            invalid_json = False
            try:
                parsed_body = _parse_strict_utf8_json(raw_content)
            except ValueError, UnicodeDecodeError:
                invalid_json = True
                parsed_body = None
            if invalid_json:
                raise UpstreamProtocolError(
                    "Upstream response is not valid JSON"
                ) from None
        else:
            parsed_body = None
        return UpstreamResponse(
            status_code=resp.status_code,
            body=parsed_body,
            raw_content=raw_content,
        )

    async def close(self) -> None:
        """Close all pooled HTTP clients."""
        await self._pool.close_all()
