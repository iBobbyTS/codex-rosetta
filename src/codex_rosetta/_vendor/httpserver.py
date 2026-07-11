# /// zerodep
# version = "0.2.3"
# deps = []
# tier = "subsystem"
# category = "network"
# note = "Install/update via `zerodep add httpserver`"
# ///

"""Zero-dependency async HTTP server with decorator-based routing.

Part of zerodep: https://github.com/Oaklight/zerodep
Copyright (c) 2026 Peng Ding. MIT License.

Async HTTP/1.1 server built on ``asyncio.start_server()``.  Supports
decorator-based routing, JSON request/response, static file serving,
streaming responses (SSE), and graceful shutdown.

Usage::

    from httpserver import App, JSONResponse

    app = App()

    @app.route("/status")
    async def status(request):
        return JSONResponse({"state": "idle"})

    @app.route("/echo", methods=["POST"])
    def echo(request):
        return JSONResponse(request.json())

    app.run(host="127.0.0.1", port=8000)
"""

# ── Imports ──────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json as _json
import logging
import mimetypes
import os
import re
import signal
import sys
import time
from collections.abc import AsyncIterator, Callable
from email.utils import formatdate
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

__all__ = [
    # Application
    "App",
    # Request / Response
    "Request",
    "Response",
    "JSONResponse",
    "StreamingResponse",
    "FileResponse",
    # Exceptions
    "HTTPException",
    # Utilities
    "abort",
]

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_MAX_BODY_SIZE = 1_048_576  # 1 MB
DEFAULT_READ_TIMEOUT = 30.0  # seconds
DEFAULT_REQUEST_LINE_TIMEOUT = 5.0  # seconds
DEFAULT_MAX_HEADER_COUNT = 100
DEFAULT_MAX_HEADER_BYTES = 64 * 1024
DEFAULT_HEADER_TIMEOUT = 10.0  # seconds
DEFAULT_BODY_TIMEOUT = 30.0  # seconds
DEFAULT_MAX_CONCURRENT_REQUEST_PARSES = 64

_STATUS_REASONS: dict[int, str] = {
    100: "Continue",
    101: "Switching Protocols",
    200: "OK",
    201: "Created",
    202: "Accepted",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found",
    303: "See Other",
    304: "Not Modified",
    307: "Temporary Redirect",
    308: "Permanent Redirect",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    408: "Request Timeout",
    409: "Conflict",
    413: "Content Too Large",
    415: "Unsupported Media Type",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    431: "Request Header Fields Too Large",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}

# Type converters for path parameters
_PARAM_CONVERTERS: dict[str, tuple[str, Callable[[str], Any]]] = {
    "str": (r"([^/]+)", str),
    "int": (r"(-?\d+)", int),
    "float": (r"(-?[0-9]+(?:\.[0-9]+)?)", float),
    "path": (r"(.+)", str),
}

# Regex to find <type:name> or <name> segments in route patterns
_PARAM_RE = re.compile(r"<(?:(\w+):)?(\w+)>")

_SENTINEL = object()


# ── Exceptions ───────────────────────────────────────────────────────────────


class HTTPException(Exception):
    """HTTP error that maps to a specific status code.

    Raise directly or via :func:`abort` to short-circuit request handling.

    Args:
        status_code: HTTP status code (e.g. 404, 500).
        message: Optional human-readable error message.
    """

    __slots__ = ("status_code", "message")

    def __init__(self, status_code: int, message: str | None = None):
        self.status_code = status_code
        self.message = message or _STATUS_REASONS.get(status_code, "Error")
        super().__init__(self.message)


class _BadRequest(Exception):
    """Internal: malformed HTTP request from client."""


def abort(status_code: int, message: str | None = None) -> None:
    """Raise an :class:`HTTPException` with the given status code.

    Args:
        status_code: HTTP status code.
        message: Optional error message.
    """
    raise HTTPException(status_code, message)


# ── Request ──────────────────────────────────────────────────────────────────


class Request:
    """Parsed HTTP request.

    Attributes:
        method: Uppercase HTTP method (GET, POST, ...).
        path: URL path, percent-decoded.
        query_string: Raw query string (without leading ``?``).
        query_params: Parsed query string as ``{key: [values]}``.
        headers: Case-insensitive header dict (keys stored lowercase).
        body: Raw request body bytes.
        path_params: Parameters extracted from the route pattern.
        client_addr: Client ``(host, port)`` tuple.
        app: Reference to the :class:`App` instance handling this request.
    """

    __slots__ = (
        "method",
        "path",
        "query_string",
        "query_params",
        "headers",
        "body",
        "path_params",
        "client_addr",
        "app",
        "_json",
        "_pre_body_hooks_ran",
    )

    def __init__(
        self,
        method: str,
        path: str,
        query_string: str,
        headers: dict[str, str],
        body: bytes,
        client_addr: tuple[str, int],
        app: App | None = None,
    ):
        self.method = method
        self.path = path
        self.query_string = query_string
        self.query_params: dict[str, list[str]] = parse_qs(query_string)
        self.headers = headers
        self.body = body
        self.path_params: dict[str, Any] = {}
        self.client_addr = client_addr
        self.app = app
        self._json: Any = _SENTINEL
        self._pre_body_hooks_ran = False

    def json(self) -> Any:
        """Parse body as JSON (cached)."""
        if self._json is _SENTINEL:
            self._json = _json.loads(self.body)
        return self._json

    def text(self) -> str:
        """Decode body as UTF-8."""
        return self.body.decode("utf-8")

    def form(self) -> dict[str, list[str]]:
        """Parse URL-encoded form body."""
        return parse_qs(self.body.decode("utf-8"))


# ── Response Classes ─────────────────────────────────────────────────────────


class Response:
    """HTTP response with a fixed body.

    Args:
        body: Response body (bytes or str).
        status_code: HTTP status code.
        headers: Extra response headers.
        content_type: Shorthand for ``Content-Type`` header.
    """

    __slots__ = ("status_code", "headers", "body")

    def __init__(
        self,
        body: bytes | str = b"",
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content_type: str | None = None,
    ):
        self.status_code = status_code
        self.headers: dict[str, str] = headers.copy() if headers else {}
        if isinstance(body, str):
            self.body = body.encode("utf-8")
        else:
            self.body = body
        if content_type is not None:
            self.headers["Content-Type"] = content_type

    async def _write(self, writer: asyncio.StreamWriter) -> None:
        """Serialize and write the full HTTP response."""
        reason = _STATUS_REASONS.get(self.status_code, "Unknown")
        self.headers.setdefault("Content-Length", str(len(self.body)))
        self.headers.setdefault("Content-Type", "text/plain; charset=utf-8")
        self.headers.setdefault("Date", _http_date())
        self.headers.setdefault("Connection", "close")

        buf = bytearray()
        buf.extend(f"HTTP/1.1 {self.status_code} {reason}\r\n".encode("latin-1"))
        for k, v in self.headers.items():
            buf.extend(f"{k}: {v}\r\n".encode("latin-1"))
        buf.extend(b"\r\n")
        buf.extend(self.body)
        writer.write(bytes(buf))
        await writer.drain()


class JSONResponse(Response):
    """Response serialized as JSON.

    Args:
        data: Python object to serialize.
        status_code: HTTP status code.
        headers: Extra response headers.
    """

    def __init__(
        self,
        data: Any,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ):
        body = _json.dumps(data, ensure_ascii=False).encode("utf-8")
        super().__init__(
            body=body,
            status_code=status_code,
            headers=headers,
            content_type="application/json; charset=utf-8",
        )


class StreamingResponse:
    """HTTP response streamed from an async generator.

    All streaming responses use ``Transfer-Encoding: chunked`` for
    maximum compatibility with reverse proxies and intermediaries.
    SSE (``text/event-stream``) responses additionally set
    ``Cache-Control: no-cache``.

    Args:
        generator: Async iterator yielding ``bytes`` or ``str`` chunks.
        status_code: HTTP status code.
        headers: Extra response headers.
        content_type: MIME type (default ``application/octet-stream``).
    """

    __slots__ = ("_generator", "status_code", "headers", "content_type")

    def __init__(
        self,
        generator: AsyncIterator[bytes | str],
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content_type: str = "application/octet-stream",
    ):
        self._generator = generator
        self.status_code = status_code
        self.headers: dict[str, str] = headers.copy() if headers else {}
        self.content_type = content_type

    async def _write(self, writer: asyncio.StreamWriter) -> None:
        """Write status line, headers, then stream the body."""
        reason = _STATUS_REASONS.get(self.status_code, "Unknown")
        is_sse = self.content_type.startswith("text/event-stream")

        self.headers["Content-Type"] = self.content_type
        self.headers.setdefault("Transfer-Encoding", "chunked")
        if is_sse:
            self.headers.setdefault("Cache-Control", "no-cache")
        self.headers.setdefault("Date", _http_date())
        self.headers.setdefault("Connection", "close")

        buf = bytearray()
        buf.extend(f"HTTP/1.1 {self.status_code} {reason}\r\n".encode("latin-1"))
        for k, v in self.headers.items():
            buf.extend(f"{k}: {v}\r\n".encode("latin-1"))
        buf.extend(b"\r\n")
        writer.write(bytes(buf))
        await writer.drain()

        try:
            async for chunk in self._generator:
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                writer.write(f"{len(chunk):x}\r\n".encode("latin-1"))
                writer.write(chunk)
                writer.write(b"\r\n")
                await writer.drain()
            writer.write(b"0\r\n\r\n")
            await writer.drain()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            logger.debug("Client disconnected during streaming")
        finally:
            aclose = getattr(self._generator, "aclose", None)
            if aclose is not None:
                await aclose()


class FileResponse(Response):
    """Response serving a file from disk.

    Args:
        path: Path to the file.
        content_type: MIME type (auto-detected from extension if ``None``).
        status_code: HTTP status code.
    """

    def __init__(
        self,
        path: str | Path,
        content_type: str | None = None,
        status_code: int = 200,
    ):
        file_path = Path(path)
        body = file_path.read_bytes()
        if content_type is None:
            guessed, _ = mimetypes.guess_type(str(file_path))
            content_type = guessed or "application/octet-stream"
        headers = {
            "Last-Modified": _http_date(os.path.getmtime(file_path)),
        }
        super().__init__(
            body=body,
            status_code=status_code,
            headers=headers,
            content_type=content_type,
        )


# ── Routing ──────────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True, slots=True)
class _Route:
    """Internal route entry."""

    methods: list[str]  # uppercase, e.g. ["GET", "POST"], or ["*"]
    pattern: re.Pattern[str]
    handler: Callable[..., Any]
    is_async: bool
    param_names: list[str]
    param_converters: list[Callable[[str], Any]]


def _compile_route(
    path: str,
) -> tuple[re.Pattern[str], list[str], list[Callable[[str], Any]]]:
    """Compile a path pattern into a regex and parameter metadata.

    Supports ``<name>``, ``<int:name>``, ``<float:name>``, ``<path:name>``.

    Args:
        path: URL path pattern (e.g. ``/users/<int:id>``).

    Returns:
        Tuple of (compiled regex, param names, param converters).
    """
    param_names: list[str] = []
    param_converters: list[Callable[[str], Any]] = []
    regex_parts: list[str] = []
    last_end = 0

    for m in _PARAM_RE.finditer(path):
        regex_parts.append(re.escape(path[last_end : m.start()]))
        type_name = m.group(1) or "str"
        name = m.group(2)
        if type_name not in _PARAM_CONVERTERS:
            raise ValueError(f"Unknown path parameter type: {type_name!r}")
        regex_fragment, converter = _PARAM_CONVERTERS[type_name]
        regex_parts.append(regex_fragment)
        param_names.append(name)
        param_converters.append(converter)
        last_end = m.end()

    regex_parts.append(re.escape(path[last_end:]))
    full_regex = "^" + "".join(regex_parts) + "$"
    return re.compile(full_regex), param_names, param_converters


# ── HTTP Parsing ─────────────────────────────────────────────────────────────


def _deadline(timeout: float) -> float:
    """Return a monotonic deadline for one bounded parser phase."""
    return time.monotonic() + timeout


def _remaining(deadline: float) -> float:
    """Return positive time remaining or raise the stable timeout signal."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise asyncio.TimeoutError
    return remaining


async def _read_request_head(
    reader: asyncio.StreamReader,
    request_line_timeout: float,
    header_timeout: float,
) -> tuple[str, str, str, dict[str, str]]:
    """Read one request line and bounded header section."""
    request_line_deadline = _deadline(request_line_timeout)
    try:
        raw_line = await asyncio.wait_for(
            reader.readline(), timeout=_remaining(request_line_deadline)
        )
    except ValueError:
        raise _BadRequest("Request line is too large") from None
    if time.monotonic() > request_line_deadline:
        raise asyncio.TimeoutError
    if not raw_line:
        raise _BadRequest("Empty request")
    request_line = raw_line.decode("latin-1").rstrip("\r\n")
    parts = request_line.split(" ", 2)
    if len(parts) != 3:
        raise _BadRequest(f"Malformed request line: {request_line!r}")
    method, raw_url, _version = parts

    parsed = urlparse(raw_url)
    path = unquote(parsed.path)
    query_string = parsed.query
    headers = await _read_header_section(
        reader,
        deadline=_deadline(header_timeout),
    )
    return method.upper(), path, query_string, headers


async def _read_request_body(
    reader: asyncio.StreamReader,
    headers: dict[str, str],
    *,
    body_timeout: float,
    header_timeout: float,
    max_body_size: int,
) -> bytes:
    """Read one fixed or chunked body under a single monotonic deadline."""
    body_deadline = _deadline(body_timeout)
    cl = headers.get("content-length")
    if cl is not None:
        try:
            length = int(cl)
        except ValueError:
            raise _BadRequest("Invalid Content-Length") from None
        if length < 0:
            raise _BadRequest("Invalid Content-Length")
        if length > max_body_size:
            raise HTTPException(413, f"Request body too large ({length} bytes)")
        if length > 0:
            body = await asyncio.wait_for(
                reader.readexactly(length), timeout=_remaining(body_deadline)
            )
            if time.monotonic() > body_deadline:
                raise asyncio.TimeoutError
            return body
        return b""
    if headers.get("transfer-encoding", "").lower() == "chunked":
        return await _read_chunked_body(
            reader,
            deadline=body_deadline,
            header_timeout=header_timeout,
            max_body_size=max_body_size,
        )
    return b""


async def _read_request(
    reader: asyncio.StreamReader,
    timeout: float,
    max_body_size: int,
) -> tuple[str, str, str, dict[str, str], bytes]:
    """Backward-compatible complete request reader.

    Returns:
        Tuple of (method, path, query_string, headers, body).

    Raises:
        _BadRequest: If the request is malformed.
        asyncio.TimeoutError: If reading times out.
    """
    method, path, query_string, headers = await _read_request_head(
        reader,
        request_line_timeout=min(timeout, DEFAULT_REQUEST_LINE_TIMEOUT),
        header_timeout=min(timeout, DEFAULT_HEADER_TIMEOUT),
    )
    body = await _read_request_body(
        reader,
        headers,
        body_timeout=timeout,
        header_timeout=min(timeout, DEFAULT_HEADER_TIMEOUT),
        max_body_size=max_body_size,
    )
    return method, path, query_string, headers, body


async def _read_header_section(
    reader: asyncio.StreamReader,
    *,
    deadline: float,
    discard: bool = False,
) -> dict[str, str]:
    """Read one bounded HTTP header or trailer section.

    The aggregate byte budget includes each raw name/value line, its CRLF
    framing, and the final empty-line delimiter.  The monotonic deadline starts
    immediately before the first header read and cannot be extended by a peer
    that keeps producing individual lines within the ordinary read timeout.
    """
    total_bytes = 0
    count = 0
    headers: dict[str, str] = {}
    while True:
        try:
            line = await asyncio.wait_for(
                reader.readline(),
                timeout=_remaining(deadline),
            )
        except ValueError:
            # StreamReader raises ValueError when one line exceeds its own
            # configured limit.  Keep the response stable and do not echo it.
            raise HTTPException(431, "Request header section is too large") from None
        if not line:
            raise _BadRequest("Incomplete request header section")
        if time.monotonic() > deadline:
            raise asyncio.TimeoutError

        total_bytes += len(line)
        if total_bytes > DEFAULT_MAX_HEADER_BYTES:
            raise HTTPException(431, "Request header section is too large")

        decoded = line.decode("latin-1").rstrip("\r\n")
        if not decoded:
            return headers

        count += 1
        if count > DEFAULT_MAX_HEADER_COUNT:
            raise HTTPException(431, "Too many request header fields")
        if discard:
            continue
        if ":" in decoded:
            key, value = decoded.split(":", 1)
            headers[key.strip().lower()] = value.strip()


async def _read_chunked_body(
    reader: asyncio.StreamReader,
    *,
    deadline: float,
    header_timeout: float,
    max_body_size: int,
) -> bytes:
    """Read a chunked transfer-encoded body."""
    parts: list[bytes] = []
    total = 0
    while True:
        size_line = await asyncio.wait_for(
            reader.readline(), timeout=_remaining(deadline)
        )
        size_str = size_line.decode("latin-1").split(";")[0].strip()
        if not size_str:
            break
        chunk_size = int(size_str, 16)
        if chunk_size == 0:
            trailer_deadline = min(deadline, _deadline(header_timeout))
            await _read_header_section(
                reader,
                deadline=trailer_deadline,
                discard=True,
            )
            break
        total += chunk_size
        if total > max_body_size:
            raise HTTPException(413, "Request body too large")
        data = await asyncio.wait_for(
            reader.readexactly(chunk_size), timeout=_remaining(deadline)
        )
        await asyncio.wait_for(reader.readline(), timeout=_remaining(deadline))
        parts.append(data)
    if time.monotonic() > deadline:
        raise asyncio.TimeoutError
    return b"".join(parts)


# ── Utilities ────────────────────────────────────────────────────────────────


def _http_date(timestamp: float | None = None) -> str:
    """Format a timestamp as an HTTP-date (RFC 7231)."""
    return formatdate(timeval=timestamp, localtime=False, usegmt=True)


def _coerce_response(result: Any) -> Response | StreamingResponse:
    """Convert a handler return value into a Response object."""
    if isinstance(result, (Response, StreamingResponse)):
        return result

    if result is None:
        return Response(status_code=204)

    if isinstance(result, dict):
        return JSONResponse(result)

    if isinstance(result, tuple):
        if len(result) == 2:
            body, status = result
            resp = _coerce_response(body)
            resp.status_code = status
            return resp
        if len(result) == 3:
            body, status, extra_headers = result
            resp = _coerce_response(body)
            resp.status_code = status
            resp.headers.update(extra_headers)
            return resp
        raise ValueError(f"Unsupported tuple length: {len(result)}")

    if isinstance(result, bytes):
        return Response(body=result, content_type="application/octet-stream")

    if isinstance(result, str):
        return Response(body=result, content_type="text/plain; charset=utf-8")

    raise TypeError(
        f"Cannot coerce handler return type {type(result).__name__} to Response"
    )


# ── Static File Resolution ───────────────────────────────────────────────────


def _resolve_static_file(
    request_path: str,
    url_prefix: str,
    directory: str,
) -> FileResponse | None:
    """Try to resolve a static file request.

    Returns a FileResponse if the file exists and the path is safe,
    otherwise None.
    """
    if not request_path.startswith(url_prefix):
        return None

    relative = request_path[len(url_prefix) :].lstrip("/")
    if not relative:
        return None

    base = Path(directory).resolve()
    target = (base / relative).resolve()

    # Prevent directory traversal
    if not str(target).startswith(str(base)):
        return None

    if not target.is_file():
        return None

    return FileResponse(target)


# ── App ──────────────────────────────────────────────────────────────────────


class App:
    """Async HTTP server application.

    Args:
        max_body_size: Maximum request body size in bytes.
        read_timeout: Legacy body-read timeout. Phase-specific values below
            take precedence; request-line and header phases never inherit a
            value above their secure defaults.
        request_line_timeout: Monotonic total deadline for the request line.
        header_timeout: Monotonic total deadline for each header/trailer section.
        body_timeout: Monotonic total deadline for the complete request body.
        max_concurrent_request_parses: Maximum connections allowed to parse a
            request concurrently. Excess connections receive an immediate 503.

    Example::

        app = App()

        @app.get("/hello")
        async def hello(request):
            return {"message": "Hello, world!"}

        app.run()
    """

    def __init__(
        self,
        *,
        max_body_size: int = DEFAULT_MAX_BODY_SIZE,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        request_line_timeout: float | None = None,
        header_timeout: float | None = None,
        body_timeout: float | None = None,
        max_concurrent_request_parses: int = DEFAULT_MAX_CONCURRENT_REQUEST_PARSES,
    ):
        if isinstance(max_concurrent_request_parses, bool) or not isinstance(
            max_concurrent_request_parses, int
        ):
            raise TypeError("max_concurrent_request_parses must be an integer")
        if max_concurrent_request_parses <= 0:
            raise ValueError("max_concurrent_request_parses must be positive")
        if read_timeout <= 0:
            raise ValueError("read_timeout must be positive")

        resolved_request_line_timeout = (
            min(read_timeout, DEFAULT_REQUEST_LINE_TIMEOUT)
            if request_line_timeout is None
            else request_line_timeout
        )
        resolved_header_timeout = (
            min(read_timeout, DEFAULT_HEADER_TIMEOUT)
            if header_timeout is None
            else header_timeout
        )
        resolved_body_timeout = read_timeout if body_timeout is None else body_timeout
        for name, value in (
            ("request_line_timeout", resolved_request_line_timeout),
            ("header_timeout", resolved_header_timeout),
            ("body_timeout", resolved_body_timeout),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")

        self._routes: list[_Route] = []
        self._static_routes: list[tuple[str, str]] = []
        self._before_body_handlers: list[Callable[..., Any]] = []
        self._before_request_handlers: list[Callable[..., Any]] = []
        self._after_request_handlers: list[Callable[..., Any]] = []
        self._error_handlers: dict[int | type, Callable[..., Any]] = {}
        self._server: asyncio.Server | None = None
        self._shutdown_event: asyncio.Event | None = None
        self.max_body_size = max_body_size
        self.read_timeout = read_timeout
        self.request_line_timeout = resolved_request_line_timeout
        self.header_timeout = resolved_header_timeout
        self.body_timeout = resolved_body_timeout
        self.max_concurrent_request_parses = max_concurrent_request_parses
        self._active_request_parses = 0
        self.port: int | None = None
        self.host: str | None = None

    # ── Route Registration ───────────────────────────────────────────────

    def route(
        self, url_pattern: str, methods: list[str] | None = None
    ) -> Callable[..., Any]:
        """Register a route handler.

        Args:
            url_pattern: URL pattern with optional parameters.
            methods: HTTP methods to handle (e.g. ``["GET", "POST"]``).
                Defaults to ``["GET"]``.

        Example::

            @app.route("/users/<int:id>", methods=["GET", "POST"])
            async def user(request, id):
                return {"id": id}
        """
        if methods is None:
            methods = ["GET"]

        def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
            pattern, param_names, converters = _compile_route(url_pattern)
            is_async = inspect.iscoroutinefunction(handler)
            self._routes.append(
                _Route(
                    methods=[m.upper() for m in methods],
                    pattern=pattern,
                    handler=handler,
                    is_async=is_async,
                    param_names=param_names,
                    param_converters=converters,
                )
            )
            return handler

        return decorator

    def get(self, path: str) -> Callable[..., Any]:
        """Shorthand for ``@app.route(path, methods=["GET"])``."""
        return self.route(path, methods=["GET"])

    def post(self, path: str) -> Callable[..., Any]:
        """Shorthand for ``@app.route(path, methods=["POST"])``."""
        return self.route(path, methods=["POST"])

    def put(self, path: str) -> Callable[..., Any]:
        """Shorthand for ``@app.route(path, methods=["PUT"])``."""
        return self.route(path, methods=["PUT"])

    def delete(self, path: str) -> Callable[..., Any]:
        """Shorthand for ``@app.route(path, methods=["DELETE"])``."""
        return self.route(path, methods=["DELETE"])

    def patch(self, path: str) -> Callable[..., Any]:
        """Shorthand for ``@app.route(path, methods=["PATCH"])``."""
        return self.route(path, methods=["PATCH"])

    def static(self, url_prefix: str, directory: str) -> None:
        """Register a directory for static file serving.

        Args:
            url_prefix: URL prefix (e.g. ``"/static"``).
            directory: Filesystem path to the directory.

        Example::

            app.static("/assets", "./public")
        """
        url_prefix = url_prefix.rstrip("/")
        abs_dir = os.path.abspath(directory)
        self._static_routes.append((url_prefix, abs_dir))

    # ── Middleware ────────────────────────────────────────────────────────

    def before_body(self, handler: Callable[..., Any]) -> Callable[..., Any]:
        """Register an after-headers, before-body hook.

        The hook receives a ``Request`` whose method, path, query, headers,
        client address, and app are available, while ``body`` is still empty.
        It may return a ``Response`` to reject the request without consuming
        body bytes. If the same callable is also registered with
        :meth:`before_request`, it runs only once for socket-parsed requests
        while direct ``_dispatch`` calls retain the normal fallback.
        """
        self._before_body_handlers.append(handler)
        return handler

    def before_request(self, handler: Callable[..., Any]) -> Callable[..., Any]:
        """Register a before-request hook.

        The hook receives ``(request)`` and may return a ``Response`` to
        short-circuit the route handler.
        """
        self._before_request_handlers.append(handler)
        return handler

    def after_request(self, handler: Callable[..., Any]) -> Callable[..., Any]:
        """Register an after-request hook.

        The hook receives ``(request, response)`` and may return a new
        or modified ``Response``.
        """
        self._after_request_handlers.append(handler)
        return handler

    def errorhandler(self, code_or_exc: int | type) -> Callable[..., Any]:
        """Register an error handler.

        Args:
            code_or_exc: HTTP status code (int) or exception class.

        The handler receives ``(request, exception)`` and must return a
        ``Response``.
        """

        def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
            self._error_handlers[code_or_exc] = handler
            return handler

        return decorator

    # ── Request Dispatch ─────────────────────────────────────────────────

    def _match_route(
        self, request: Request
    ) -> tuple[_Route | None, re.Match[str] | None, bool]:
        """Find the first route matching the request path and method.

        Returns:
            (matched_route, regex_match, path_existed).  *path_existed* is
            True when a route matched the path but not the HTTP method.
        """
        path_existed = False
        for route in self._routes:
            m = route.pattern.match(request.path)
            if m is None:
                continue
            path_existed = True
            if "*" not in route.methods and request.method not in route.methods:
                continue
            return route, m, True
        return None, None, path_existed

    async def _invoke_route(
        self, route: _Route, match: re.Match[str], request: Request
    ) -> Response | StreamingResponse:
        """Extract path params, call the handler, return a response."""
        for name, converter, value in zip(
            route.param_names, route.param_converters, match.groups()
        ):
            request.path_params[name] = converter(value)

        try:
            result = await _invoke(route.handler, request, **request.path_params)
            return _coerce_response(result)
        except HTTPException as exc:
            return await self._handle_error(request, exc)
        except Exception as exc:
            logger.exception(
                "Unhandled exception in handler %s",
                getattr(route.handler, "__name__", repr(route.handler)),
            )
            return await self._handle_error(request, exc)

    async def _run_after_hooks(
        self, request: Request, response: Response | StreamingResponse
    ) -> Response | StreamingResponse:
        """Run after-request hooks, allowing them to replace the response."""
        for hook in self._after_request_handlers:
            hook_result = await _invoke(hook, request, response)
            if hook_result is not None:
                response = _coerce_response(hook_result)
        return response

    async def _dispatch(self, request: Request) -> Response | StreamingResponse:
        """Match a request to a route and invoke the handler."""
        # -- before_request hooks --
        for hook in self._before_request_handlers:
            if request._pre_body_hooks_ran and hook in self._before_body_handlers:
                continue
            result = await _invoke(hook, request)
            if result is not None:
                return _coerce_response(result)

        # -- Static file check --
        for prefix, directory in self._static_routes:
            file_resp = _resolve_static_file(request.path, prefix, directory)
            if file_resp is not None:
                return file_resp

        # -- Route matching --
        route, match, path_existed = self._match_route(request)

        if route is not None and match is not None:
            response = await self._invoke_route(route, match, request)
            return await self._run_after_hooks(request, response)

        # -- No route matched --
        if path_existed:
            allowed = sorted(
                {
                    m
                    for r in self._routes
                    if r.pattern.match(request.path)
                    for m in r.methods
                    if m != "*"
                }
            )
            exc = HTTPException(405, "Method Not Allowed")
            response = await self._handle_error(request, exc)
            if isinstance(response, Response):
                response.headers["Allow"] = ", ".join(allowed)
            return response

        exc = HTTPException(404, "Not Found")
        return await self._handle_error(request, exc)

    async def _handle_error(
        self, request: Request, exc: Exception
    ) -> Response | StreamingResponse:
        """Resolve an error into a response, consulting registered handlers."""
        if isinstance(exc, HTTPException):
            handler = self._error_handlers.get(exc.status_code)
            if handler is not None:
                result = await _invoke(handler, request, exc)
                return _coerce_response(result)

        for exc_cls, handler in self._error_handlers.items():
            if isinstance(exc_cls, type) and isinstance(exc, exc_cls):
                result = await _invoke(handler, request, exc)
                return _coerce_response(result)

        if isinstance(exc, HTTPException):
            return JSONResponse(
                {"error": exc.message},
                status_code=exc.status_code,
            )
        return JSONResponse(
            {"error": "Internal Server Error"},
            status_code=500,
        )

    # ── Connection Handling ───────────────────────────────────────────────

    def _try_acquire_request_parse(self) -> bool:
        """Acquire one parser slot without creating a waiting task."""
        if self._active_request_parses >= self.max_concurrent_request_parses:
            return False
        self._active_request_parses += 1
        return True

    def _release_request_parse(self) -> None:
        """Release one parser slot exactly once for the current request."""
        if self._active_request_parses <= 0:
            raise RuntimeError("request parse slot released without acquisition")
        self._active_request_parses -= 1

    @property
    def active_request_parses(self) -> int:
        """Return the current number of request parsers holding a slot."""
        return self._active_request_parses

    async def _run_before_body_hooks(
        self, request: Request
    ) -> Response | StreamingResponse | None:
        """Run early hooks after headers and before consuming body bytes."""
        for hook in self._before_body_handlers:
            result = await _invoke(hook, request)
            if result is not None:
                return _coerce_response(result)
        request._pre_body_hooks_ran = True
        return None

    @staticmethod
    async def _send_error_and_close(
        writer: asyncio.StreamWriter,
        response: Response | JSONResponse,
    ) -> None:
        """Write an error response to the client and close the connection.

        Swallows broken-pipe / reset errors that occur when the client has
        already disconnected.
        """
        try:
            await response._write(writer)
        except (BrokenPipeError, ConnectionResetError):
            pass
        writer.close()
        try:
            await writer.wait_closed()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection."""
        peer = writer.get_extra_info("peername")
        client_addr = (peer[0], peer[1]) if peer else ("unknown", 0)
        request: Request | None = None

        if not self._try_acquire_request_parse():
            await self._send_error_and_close(
                writer,
                JSONResponse(
                    {"error": "Request parser capacity reached"},
                    status_code=503,
                ),
            )
            return

        try:
            try:
                method, path, qs, headers = await _read_request_head(
                    reader,
                    request_line_timeout=self.request_line_timeout,
                    header_timeout=self.header_timeout,
                )
                request = Request(
                    method=method,
                    path=path,
                    query_string=qs,
                    headers=headers,
                    body=b"",
                    client_addr=client_addr,
                    app=self,
                )
                early_response = await self._run_before_body_hooks(request)
                if early_response is None:
                    request.body = await _read_request_body(
                        reader,
                        headers,
                        body_timeout=self.body_timeout,
                        header_timeout=self.header_timeout,
                        max_body_size=self.max_body_size,
                    )
            finally:
                self._release_request_parse()

            logger.debug("%s %s from %s", method, path, client_addr)
            if early_response is not None:
                response = await self._run_after_hooks(request, early_response)
            else:
                response = await self._dispatch(request)
            await response._write(writer)
        except _BadRequest as exc:
            logger.debug("Bad request from %s: %s", client_addr, exc)
            await self._send_error_and_close(
                writer,
                Response(
                    body=str(exc),
                    status_code=400,
                    content_type="text/plain; charset=utf-8",
                ),
            )
        except HTTPException as exc:
            await self._send_error_and_close(
                writer,
                JSONResponse({"error": exc.message}, status_code=exc.status_code),
            )
        except asyncio.TimeoutError:
            logger.debug("Request read timed out from %s", client_addr)
            await self._send_error_and_close(
                writer,
                JSONResponse({"error": "Request Timeout"}, status_code=408),
            )
        except asyncio.IncompleteReadError:
            logger.debug("Incomplete request body from %s", client_addr)
            await self._send_error_and_close(
                writer,
                JSONResponse(
                    {"error": "Bad Request: incomplete body"}, status_code=400
                ),
            )
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            logger.debug("Connection reset by %s during response", client_addr)
        except Exception:
            logger.exception("Error handling request from %s", client_addr)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    # ── Server Lifecycle ─────────────────────────────────────────────────

    def run(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        socket: str | None = None,
    ) -> None:
        """Start the server (blocking).

        Args:
            host: Bind address (ignored when *socket* is set).
            port: Bind port. Use ``0`` for OS-assigned port (ignored when
                *socket* is set).
            socket: Unix domain socket path. When set, the server listens
                on a Unix socket instead of TCP. The socket file permissions
                are restricted to owner-only (``0o600``) after creation.
                Only available on Unix-like systems.
        """
        try:
            asyncio.run(self._serve(host, port, socket=socket))
        except KeyboardInterrupt:
            pass

    async def _serve(self, host: str, port: int, *, socket: str | None = None) -> None:
        """Internal async server loop."""
        self._shutdown_event = asyncio.Event()
        self._socket_path: str | None = None

        if socket:
            server = await self._start_unix_socket(socket)
        else:
            server = await asyncio.start_server(
                self._handle_connection,
                host,
                port,
            )
            addrs = server.sockets[0].getsockname() if server.sockets else (host, port)
            self.host = addrs[0]
            self.port = addrs[1]
            logger.info("Serving on %s:%d", self.host, self.port)

        self._server = server

        loop = asyncio.get_running_loop()
        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self._shutdown_event.set)

        async with server:
            await self._shutdown_event.wait()
            logger.info("Shutting down server")
            if self._socket_path:
                self._cleanup_socket()

    async def _start_unix_socket(self, socket_path: str) -> asyncio.Server:
        """Start listening on a Unix domain socket.

        Handles stale socket cleanup, permission hardening (``0o600``),
        and registers the path for shutdown cleanup.

        Args:
            socket_path: Path for the Unix domain socket file.

        Returns:
            The ``asyncio.Server`` instance.

        Raises:
            SystemExit: If the path exists but is not a socket, or the
                parent directory does not exist.
        """
        import stat as stat_mod

        path = os.path.realpath(socket_path)

        # Remove stale socket if present
        if os.path.exists(path):
            try:
                st = os.stat(path)
                if stat_mod.S_ISSOCK(st.st_mode):
                    os.unlink(path)
                    logger.info("Removed stale socket: %s", path)
                else:
                    logger.error("Socket path exists and is not a socket: %s", path)
                    sys.exit(1)
            except OSError as exc:
                logger.error("Cannot remove stale socket %s: %s", path, exc)
                sys.exit(1)

        # Ensure parent directory exists
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            logger.error("Socket parent directory does not exist: %s", parent)
            sys.exit(1)

        server = await asyncio.start_unix_server(
            self._handle_connection,
            path=path,
        )

        # Restrict permissions to owner-only
        if os.path.exists(path):
            os.chmod(path, 0o600)

        self._socket_path = path
        logger.info("Serving on unix:%s (mode 0600)", path)
        return server

    def _cleanup_socket(self) -> None:
        """Remove the Unix socket file on shutdown."""
        if self._socket_path and os.path.exists(self._socket_path):
            try:
                os.unlink(self._socket_path)
                logger.info("Removed socket: %s", self._socket_path)
            except OSError:
                pass

    def shutdown(self) -> None:
        """Request a graceful server shutdown.

        Safe to call from a request handler.
        """
        if self._shutdown_event is not None:
            self._shutdown_event.set()


# ── Handler Invocation ───────────────────────────────────────────────────────


async def _invoke(handler: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Invoke a handler, wrapping sync functions with ``asyncio.to_thread``."""
    if inspect.iscoroutinefunction(handler):
        return await handler(*args, **kwargs)
    return await asyncio.to_thread(handler, *args, **kwargs)
