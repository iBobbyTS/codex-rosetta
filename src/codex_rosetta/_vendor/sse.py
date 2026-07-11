# /// zerodep
# version = "0.3.3"
# deps = ["httpclient"]
# tier = "subsystem"
# category = "network"
# note = "Install/update via `zerodep add sse`"
# ///
"""Zero-dependency SSE (Server-Sent Events) client.

Part of zerodep: https://github.com/Oaklight/zerodep
Copyright (c) 2026 Peng Ding. MIT License.

Provides three abstraction layers:

1. **Low-level parser** (``EventSource`` / ``AsyncEventSource``):
   Parse any ``Iterable[str]`` or ``AsyncIterable[str]`` of lines into
   ``SSEEvent`` objects. No network dependency.

2. **High-level client** (``SSEClient`` / ``AsyncSSEClient``):
   Open a streaming HTTP GET, parse SSE events, and auto-reconnect
   on connection loss. Requires sibling ``httpclient`` module.

3. **Convenience functions** (``connect`` / ``async_connect``):
   Shorthand for creating ``SSEClient`` / ``AsyncSSEClient``.

Usage::

    # High-level (auto-connect + reconnect)
    from sse import connect, async_connect

    with connect("https://api.example.com/events") as events:
        for event in events:
            print(event.event, event.data)

    async with async_connect("https://api.example.com/events") as events:
        async for event in events:
            print(event.data)

    # Low-level (parse from any line source)
    from sse import EventSource

    for event in EventSource(["data: hello", "", "data: world", ""]):
        print(event.data)  # "hello", then "world"

Requires Python 3.10+.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
import time
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from typing import Any, Callable

__all__ = [
    # Constants
    "DEFAULT_RETRY_INTERVAL",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_LINE_BYTES",
    "DEFAULT_MAX_EVENT_BYTES",
    # Data classes
    "SSEEvent",
    # Low-level parsers
    "EventSource",
    "AsyncEventSource",
    # Exceptions
    "SSEError",
    "SSELimitError",
    "SSEConnectionError",
    "SSEHTTPError",
    # High-level clients
    "SSEClient",
    "AsyncSSEClient",
    # Convenience functions
    "connect",
    "async_connect",
]


def _ensure_sibling_path(name: str) -> str:
    """Return the sibling module directory and prepend it to ``sys.path``."""
    sibling_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", name)
    if sibling_dir not in sys.path:
        sys.path.insert(0, sibling_dir)
    return sibling_dir


# ── Sibling httpclient import (guarded) ──

try:
    _httpclient_dir = _ensure_sibling_path("httpclient")
    from httpclient import HttpConnectionError as _HttpConnectionError
    from httpclient import HttpResponseLimitError as _HttpResponseLimitError
    from httpclient import HttpTimeoutError as _HttpTimeoutError
    from httpclient import async_get as _http_async_get
    from httpclient import get as _http_get

    _HAS_HTTPCLIENT = True
except (ImportError, AttributeError):
    _HAS_HTTPCLIENT = False

    class _HttpResponseLimitError(Exception):
        """Fallback type used when the optional httpclient is unavailable."""

        kind: str
        limit: int
        actual: int

# ── Sentinel for injection parameters ──────────────────────────────────────


class _Unset:
    """Sentinel indicating 'use default sibling auto-discovery'."""

    _instance: _Unset | None = None

    def __new__(cls) -> _Unset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"


_UNSET = _Unset()

# ── Constants ──

DEFAULT_RETRY_INTERVAL = 3000  # ms, per W3C spec
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_LINE_BYTES = 1024 * 1024
DEFAULT_MAX_EVENT_BYTES = 8 * 1024 * 1024


# ── Data classes ──


@dataclasses.dataclass(frozen=True, slots=True)
class SSEEvent:
    """A single Server-Sent Event.

    Attributes:
        event: Event type (default ``"message"``).
        data: Event payload. Multiple ``data:`` lines are joined with ``\\n``.
        id: Last event ID. Persists across events until changed by the server.
        retry: Reconnection interval in milliseconds, or ``None``.
    """

    event: str = "message"
    data: str = ""
    id: str = ""
    retry: int | None = None

    def __repr__(self) -> str:
        d = self.data[:50] + "..." if len(self.data) > 50 else self.data
        return f"<SSEEvent event={self.event!r} data={d!r} id={self.id!r}>"


# ── Core parser ──


class SSEError(Exception):
    """Base exception for SSE errors."""


class SSELimitError(SSEError):
    """Raised when an SSE line or event exceeds a configured byte limit.

    Attributes:
        kind: The SSE element that exceeded its limit.
        limit: Maximum permitted size in bytes.
        actual: Observed size in bytes when the limit was detected.
    """

    def __init__(self, kind: str, limit: int, actual: int) -> None:
        self.kind = kind
        self.limit = limit
        self.actual = actual
        super().__init__(f"SSE {kind} exceeds {limit} bytes (observed {actual} bytes)")


class _SSEParser:
    """Stateful W3C SSE line parser.

    Feed individual lines via ``feed_line()``; it returns an ``SSEEvent``
    when an empty line triggers dispatch.
    """

    __slots__ = (
        "_event_type",
        "_data_buf",
        "_last_id",
        "_retry",
        "_first_line",
        "_max_event_bytes",
        "_event_bytes",
    )

    def __init__(
        self,
        *,
        last_id: str = "",
        retry: int | None = None,
        max_event_bytes: int | None = DEFAULT_MAX_EVENT_BYTES,
    ) -> None:
        if max_event_bytes is not None and max_event_bytes <= 0:
            raise ValueError("max_event_bytes must be positive or None")
        self._event_type: str = ""
        self._data_buf: list[str] = []
        self._last_id: str = last_id
        self._retry: int | None = retry
        self._first_line: bool = True
        self._max_event_bytes = max_event_bytes
        self._event_bytes = 0

    @property
    def last_event_id(self) -> str:
        """Current last-event-id (persists across events)."""
        return self._last_id

    @property
    def retry_interval(self) -> int | None:
        """Current retry interval in ms (persists across events)."""
        return self._retry

    def feed_line(self, line: str) -> SSEEvent | None:
        """Process one line and return an event if dispatched.

        Args:
            line: A single line from the event stream (already stripped of
                trailing CR/LF by the transport).

        Returns:
            An ``SSEEvent`` if an empty line triggers dispatch, else ``None``.
        """
        # Strip BOM from the very first line of the stream
        if self._first_line:
            self._first_line = False
            if line.startswith("\ufeff"):
                line = line[1:]

        # Empty line -> dispatch
        if not line:
            return self._dispatch()

        # Comment
        if line.startswith(":"):
            return None

        # Split field:value
        if ":" in line:
            field, _, value = line.partition(":")
            # Strip exactly one leading space from value (per W3C spec)
            if value.startswith(" "):
                value = value[1:]
        else:
            field = line
            value = ""

        # Process field
        if field == "event":
            self._event_type = value
        elif field == "data":
            value_bytes = len(value.encode("utf-8"))
            event_bytes = self._event_bytes + value_bytes
            if self._data_buf:
                event_bytes += 1
            if (
                self._max_event_bytes is not None
                and event_bytes > self._max_event_bytes
            ):
                raise SSELimitError("event", self._max_event_bytes, event_bytes)
            self._data_buf.append(value)
            self._event_bytes = event_bytes
        elif field == "id":
            if "\0" not in value:
                self._last_id = value
        elif field == "retry":
            if value.isdigit() and value:
                self._retry = int(value)

        return None

    def _dispatch(self) -> SSEEvent | None:
        """Dispatch the accumulated event and reset per-event state."""
        if not self._data_buf:
            return None
        event = SSEEvent(
            event=self._event_type or "message",
            data="\n".join(self._data_buf),
            id=self._last_id,
            retry=self._retry,
        )
        # Reset per-event state (id and retry persist)
        self._event_type = ""
        self._data_buf = []
        self._event_bytes = 0
        return event


# ── Iterator wrappers (no httpclient dependency) ──


class EventSource:
    """Sync SSE parser wrapping any line iterable.

    Example::

        lines = ["event: greeting", "data: hello", "", "data: world", ""]
        for event in EventSource(lines):
            print(event.event, event.data)
    """

    def __init__(
        self,
        lines: Iterable[str],
        *,
        max_event_bytes: int | None = DEFAULT_MAX_EVENT_BYTES,
    ) -> None:
        self._lines = lines
        self._max_event_bytes = max_event_bytes

    def __iter__(self) -> Iterator[SSEEvent]:
        parser = _SSEParser(max_event_bytes=self._max_event_bytes)
        for line in self._lines:
            event = parser.feed_line(line)
            if event is not None:
                yield event


class AsyncEventSource:
    """Async SSE parser wrapping any async line iterable.

    Example::

        async for event in AsyncEventSource(async_line_source):
            print(event.data)
    """

    def __init__(
        self,
        lines: AsyncIterable[str],
        *,
        max_event_bytes: int | None = DEFAULT_MAX_EVENT_BYTES,
    ) -> None:
        self._lines = lines
        self._max_event_bytes = max_event_bytes

    async def __aiter__(self) -> AsyncIterator[SSEEvent]:
        parser = _SSEParser(max_event_bytes=self._max_event_bytes)
        async for line in self._lines:
            event = parser.feed_line(line)
            if event is not None:
                yield event


# ── Exceptions ──


class SSEConnectionError(SSEError):
    """Raised when max retries exhausted."""

    def __init__(
        self, url: str, retries: int, last_error: Exception | None = None
    ) -> None:
        self.url = url
        self.retries = retries
        self.last_error = last_error
        super().__init__(
            f"SSE connection to {url} failed after {retries} retries"
            + (f": {last_error}" if last_error else "")
        )


class SSEHTTPError(SSEError):
    """Raised on non-2xx HTTP response (other than 204)."""

    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(f"SSE request to {url} returned HTTP {status_code}")


# ── High-level clients (require httpclient) ──


def _require_httpclient() -> None:
    if not _HAS_HTTPCLIENT:
        raise ImportError(
            "SSEClient requires the sibling httpclient module. "
            "Place httpclient.py in a sibling directory or on sys.path."
        )


class _SSEClientMixin:
    """Shared helpers for sync and async SSE clients."""

    _last_event_id: str
    _retry_interval: int
    _max_retries: int
    _url: str
    _max_line_bytes: int | None
    _max_event_bytes: int | None

    def _init_parser(self) -> _SSEParser:
        """Create a parser with restored persistent state."""
        return _SSEParser(
            last_id=self._last_event_id,
            retry=(
                self._retry_interval
                if self._retry_interval != DEFAULT_RETRY_INTERVAL
                else None
            ),
            max_event_bytes=self._max_event_bytes,
        )

    @staticmethod
    def _line_size(line: str) -> int:
        """Return the UTF-8 byte size of a transport-decoded SSE line."""
        return len(line.encode("utf-8"))

    def _check_line_size(self, line: str) -> None:
        """Enforce the line cap for custom transports without limit support."""
        if self._max_line_bytes is None:
            return
        actual = self._line_size(line)
        if actual > self._max_line_bytes:
            raise SSELimitError("line", self._max_line_bytes, actual)

    def _iter_response_lines(self, response: Any) -> Iterator[str]:
        """Yield bounded sync lines, retaining legacy transport compatibility."""
        try:
            lines = response.iter_lines(max_line_bytes=self._max_line_bytes)
        except TypeError:
            lines = response.iter_lines()
        for line in lines:
            self._check_line_size(line)
            yield line

    async def _aiter_response_lines(self, response: Any) -> AsyncIterator[str]:
        """Yield bounded async lines, retaining legacy transport compatibility."""
        try:
            lines = response.aiter_lines(max_line_bytes=self._max_line_bytes)
        except TypeError:
            lines = response.aiter_lines()
        async for line in lines:
            self._check_line_size(line)
            yield line

    def _handle_event(self, event: SSEEvent) -> None:
        """Update reconnection state from a received event."""
        if event.id:
            self._last_event_id = event.id
        if event.retry is not None:
            self._retry_interval = event.retry

    def _check_reconnect(self, retries: int, last_error: Exception | None) -> None:
        """Raise ``SSEConnectionError`` if max retries exceeded."""
        if self._max_retries >= 0 and retries > self._max_retries:
            raise SSEConnectionError(self._url, retries, last_error)


class SSEClient(_SSEClientMixin):
    """Synchronous SSE client with auto-reconnection.

    Opens a streaming HTTP GET, parses ``text/event-stream``, and
    automatically reconnects when the connection drops.

    Args:
        url: SSE endpoint URL.
        headers: Extra HTTP headers to send.
        timeout: Connection/read timeout in seconds.
        retry_interval: Initial reconnection delay in milliseconds.
        max_retries: Maximum reconnection attempts (``-1`` = unlimited).
        verify: Whether to verify TLS certificates.
        last_event_id: Initial ``Last-Event-ID`` header value.
        max_line_bytes: Maximum bytes per SSE line, or ``None`` for unlimited.
        max_event_bytes: Maximum accumulated data bytes per SSE event, or
            ``None`` for unlimited.
        transport: Sync HTTP GET callable. Defaults to ``_UNSET``
            (auto-discover sibling ``httpclient.get``). Must accept
            ``(url, *, headers, stream, timeout, verify)`` and return
            a response with ``.status_code``, ``.ok``, ``.close()``,
            and ``.iter_lines()`` attributes.

    Example::

        with SSEClient("https://api.example.com/events") as client:
            for event in client:
                print(event.data)
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry_interval: int = DEFAULT_RETRY_INTERVAL,
        max_retries: int = -1,
        verify: bool = True,
        last_event_id: str = "",
        max_line_bytes: int | None = DEFAULT_MAX_LINE_BYTES,
        max_event_bytes: int | None = DEFAULT_MAX_EVENT_BYTES,
        transport: Callable[..., Any] | None | _Unset = _UNSET,
    ) -> None:
        if max_line_bytes is not None and max_line_bytes <= 0:
            raise ValueError("max_line_bytes must be positive or None")
        if max_event_bytes is not None and max_event_bytes <= 0:
            raise ValueError("max_event_bytes must be positive or None")
        self._transport: Callable[..., Any]
        if isinstance(transport, _Unset):
            _require_httpclient()
            self._transport = _http_get
            self._reconnect_errors: tuple[type[Exception], ...] = (
                _HttpConnectionError,
                _HttpTimeoutError,
                ConnectionError,
                OSError,
            )
        elif transport is None:
            raise ValueError(
                "SSEClient requires a transport; pass a callable "
                "or omit to use sibling httpclient"
            )
        else:
            self._transport = transport
            self._reconnect_errors = (ConnectionError, OSError)
        self._url = url
        self._user_headers = headers or {}
        self._timeout = timeout
        self._retry_interval = retry_interval
        self._max_retries = max_retries
        self._verify = verify
        self._last_event_id = last_event_id
        self._max_line_bytes = max_line_bytes
        self._max_event_bytes = max_event_bytes
        self._response: Any = None
        self._closed = False

    def __enter__(self) -> SSEClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __iter__(self) -> Iterator[SSEEvent]:
        retries = 0
        last_error: Exception | None = None

        while not self._closed:
            try:
                self._response = self._connect()
                parser = self._init_parser()

                for line in self._iter_response_lines(self._response):
                    if self._closed:
                        return
                    event = parser.feed_line(line)
                    if event is not None:
                        self._handle_event(event)
                        retries = 0
                        yield event

                # Stream ended normally — attempt reconnect
                if self._closed:
                    return

            except _HttpResponseLimitError as exc:
                raise SSELimitError(exc.kind, exc.limit, exc.actual) from exc
            except self._reconnect_errors as exc:
                last_error = exc
            finally:
                self._close_response()

            retries += 1
            self._check_reconnect(retries, last_error)
            time.sleep(self._retry_interval / 1000)

    def _connect(self) -> Any:
        """Open a streaming GET request."""
        headers = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            **self._user_headers,
        }
        if self._last_event_id:
            headers["Last-Event-ID"] = self._last_event_id

        resp = self._transport(
            self._url,
            headers=headers,
            stream=True,
            timeout=self._timeout,
            verify=self._verify,
        )

        if resp.status_code == 204:
            resp.close()
            self._closed = True
            return resp

        if not resp.ok:
            status = resp.status_code
            resp.close()
            raise SSEHTTPError(status, self._url)

        return resp

    def _close_response(self) -> None:
        if self._response is not None:
            # Tier 3: best-effort silent — reconnect cleanup
            try:
                self._response.close()
            except Exception:
                pass
            self._response = None

    def close(self) -> None:
        """Close the SSE connection."""
        self._closed = True
        self._close_response()


class AsyncSSEClient(_SSEClientMixin):
    """Asynchronous SSE client with auto-reconnection.

    Opens a streaming HTTP GET, parses ``text/event-stream``, and
    automatically reconnects when the connection drops.

    Args:
        url: SSE endpoint URL.
        headers: Extra HTTP headers to send.
        timeout: Connection/read timeout in seconds.
        retry_interval: Initial reconnection delay in milliseconds.
        max_retries: Maximum reconnection attempts (``-1`` = unlimited).
        verify: Whether to verify TLS certificates.
        last_event_id: Initial ``Last-Event-ID`` header value.
        max_line_bytes: Maximum bytes per SSE line, or ``None`` for unlimited.
        max_event_bytes: Maximum accumulated data bytes per SSE event, or
            ``None`` for unlimited.
        transport: Async HTTP GET callable. Defaults to ``_UNSET``
            (auto-discover sibling ``httpclient.async_get``). Must accept
            ``(url, *, headers, stream, timeout, verify)`` and return
            a response with ``.status_code``, ``.ok``, ``.aclose()``,
            and ``.aiter_lines()`` attributes.

    Example::

        async with AsyncSSEClient("https://api.example.com/events") as client:
            async for event in client:
                print(event.data)
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry_interval: int = DEFAULT_RETRY_INTERVAL,
        max_retries: int = -1,
        verify: bool = True,
        last_event_id: str = "",
        max_line_bytes: int | None = DEFAULT_MAX_LINE_BYTES,
        max_event_bytes: int | None = DEFAULT_MAX_EVENT_BYTES,
        transport: Callable[..., Any] | None | _Unset = _UNSET,
    ) -> None:
        if max_line_bytes is not None and max_line_bytes <= 0:
            raise ValueError("max_line_bytes must be positive or None")
        if max_event_bytes is not None and max_event_bytes <= 0:
            raise ValueError("max_event_bytes must be positive or None")
        self._transport: Callable[..., Any]
        if isinstance(transport, _Unset):
            _require_httpclient()
            self._transport = _http_async_get
            self._reconnect_errors: tuple[type[Exception], ...] = (
                _HttpConnectionError,
                _HttpTimeoutError,
                ConnectionError,
                OSError,
            )
        elif transport is None:
            raise ValueError(
                "AsyncSSEClient requires a transport; pass a callable "
                "or omit to use sibling httpclient"
            )
        else:
            self._transport = transport
            self._reconnect_errors = (ConnectionError, OSError)
        self._url = url
        self._user_headers = headers or {}
        self._timeout = timeout
        self._retry_interval = retry_interval
        self._max_retries = max_retries
        self._verify = verify
        self._last_event_id = last_event_id
        self._max_line_bytes = max_line_bytes
        self._max_event_bytes = max_event_bytes
        self._response: Any = None
        self._closed = False

    async def __aenter__(self) -> AsyncSSEClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def __aiter__(self) -> AsyncIterator[SSEEvent]:
        retries = 0
        last_error: Exception | None = None

        while not self._closed:
            try:
                self._response = await self._connect()
                parser = self._init_parser()

                async for line in self._aiter_response_lines(self._response):
                    if self._closed:
                        return
                    event = parser.feed_line(line)
                    if event is not None:
                        self._handle_event(event)
                        retries = 0
                        yield event

                if self._closed:
                    return

            except _HttpResponseLimitError as exc:
                raise SSELimitError(exc.kind, exc.limit, exc.actual) from exc
            except self._reconnect_errors as exc:
                last_error = exc
            finally:
                await self._close_response()

            retries += 1
            self._check_reconnect(retries, last_error)
            await asyncio.sleep(self._retry_interval / 1000)

    async def _connect(self) -> Any:
        """Open a streaming async GET request."""
        headers = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            **self._user_headers,
        }
        if self._last_event_id:
            headers["Last-Event-ID"] = self._last_event_id

        resp = await self._transport(
            self._url,
            headers=headers,
            stream=True,
            timeout=self._timeout,
            verify=self._verify,
        )

        if resp.status_code == 204:
            await resp.aclose()
            self._closed = True
            return resp

        if not resp.ok:
            status = resp.status_code
            await resp.aclose()
            raise SSEHTTPError(status, self._url)

        return resp

    async def _close_response(self) -> None:
        if self._response is not None:
            # Tier 3: best-effort silent — reconnect cleanup
            try:
                await self._response.aclose()
            except Exception:
                pass
            self._response = None

    async def close(self) -> None:
        """Close the SSE connection."""
        self._closed = True
        await self._close_response()


# ── Convenience functions ──


def connect(url: str, **kwargs: Any) -> SSEClient:
    """Open a synchronous SSE connection.

    Shorthand for ``SSEClient(url, **kwargs)``.
    Use as a context manager::

        with connect("https://example.com/events") as events:
            for event in events:
                print(event.data)

    Args:
        url: SSE endpoint URL.
        **kwargs: Passed to ``SSEClient``.

    Returns:
        An ``SSEClient`` instance.
    """
    return SSEClient(url, **kwargs)


def async_connect(url: str, **kwargs: Any) -> AsyncSSEClient:
    """Open an asynchronous SSE connection.

    Shorthand for ``AsyncSSEClient(url, **kwargs)``.
    Use as an async context manager::

        async with async_connect("https://example.com/events") as events:
            async for event in events:
                print(event.data)

    Args:
        url: SSE endpoint URL.
        **kwargs: Passed to ``AsyncSSEClient``.

    Returns:
        An ``AsyncSSEClient`` instance.
    """
    return AsyncSSEClient(url, **kwargs)
