"""Safe static-page fetcher for the URL subset of Codex ``web.run.open``."""

from __future__ import annotations

import asyncio
import codecs
import ipaddress
import re
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

_ALLOWED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
_MAX_REDIRECTS = 5
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_RENDERED_CHARS = 200_000
_MAX_RENDERED_LINES = 400
_LINE_WINDOW = 200
_READ_CHUNK_BYTES = 64 * 1024
_USER_AGENT = "Codex-Rosetta/1.0 (+static web.run.open)"


class PageOpenError(RuntimeError):
    """Base error for local static-page opening."""


class PageOpenInvalidRequest(PageOpenError):
    """The open operation contains an invalid URL or line number."""


class PageOpenNotImplemented(PageOpenError):
    """The open operation requires unsupported page semantics."""


class PageOpenExecutionError(PageOpenError):
    """A supported page fetch failed."""


@dataclass(frozen=True)
class OpenedPage:
    """Normalized static page returned to the Codex search tool."""

    url: str
    title: str | None
    lines: tuple[str, ...]

    def format_for_model(self, *, lineno: int | None = None) -> str:
        """Format a bounded, line-addressable page view."""
        start = lineno or 0
        if start >= len(self.lines) and self.lines:
            raise PageOpenInvalidRequest(
                f"open.lineno {start} exceeds page line count {len(self.lines)}"
            )
        end = min(len(self.lines), start + _LINE_WINDOW)
        header = [f"Opened URL: {self.url}"]
        if self.title:
            header.append(f"Title: {self.title}")
        header.append(f"Lines {start}-{max(start, end - 1)} of {len(self.lines)}:")
        body = [f"L{index}: {self.lines[index]}" for index in range(start, end)]
        return "\n".join(header + body)


class StaticPageClient(Protocol):
    """Minimal protocol used by the Codex search bridge for page opening."""

    async def open(self, url: str) -> OpenedPage:
        """Fetch and normalize one public static page."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class StaticPageHTTPClient:
    """Fetch public static pages with redirect and response safety limits."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        max_redirects: int = _MAX_REDIRECTS,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        opener: Callable[..., Any] | None = None,
        resolver: Callable[..., Iterable[Any]] = socket.getaddrinfo,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_redirects < 0:
            raise ValueError("max_redirects must be non-negative")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.max_response_bytes = max_response_bytes
        self._opener = opener or build_opener(_NoRedirectHandler()).open
        self._resolver = resolver

    async def open(self, url: str) -> OpenedPage:
        """Fetch one URL without blocking the gateway event loop."""
        return await asyncio.to_thread(self._open_sync, url)

    def _open_sync(self, url: str) -> OpenedPage:
        current = url
        for redirect_count in range(self.max_redirects + 1):
            current = _validate_public_url(current, self._resolver)
            response, redirect = self._request_once(current)
            if redirect is not None:
                if redirect_count >= self.max_redirects:
                    raise PageOpenExecutionError(
                        f"Page redirect limit exceeded for {url}"
                    )
                current = redirect
                continue
            assert response is not None
            return self._normalize_response(response, current)

        raise PageOpenExecutionError(f"Page redirect limit exceeded for {url}")

    def _request_once(self, url: str) -> tuple[Any | None, str | None]:
        request = Request(
            url,
            headers={
                "Accept": "text/html, application/xhtml+xml, text/plain;q=0.9",
                "Accept-Encoding": "identity",
                "User-Agent": _USER_AGENT,
            },
            method="GET",
        )
        try:
            return self._opener(request, timeout=self.timeout), None
        except HTTPError as exc:
            try:
                if exc.code not in {301, 302, 303, 307, 308}:
                    raise PageOpenExecutionError(
                        f"Page returned HTTP {exc.code} for {url}"
                    ) from exc
                location = exc.headers.get("Location")
                if not location:
                    raise PageOpenExecutionError(
                        f"Page redirect from {url} is missing Location"
                    ) from exc
                return None, urljoin(url, location)
            finally:
                exc.close()
        except (OSError, URLError) as exc:
            raise PageOpenExecutionError(
                f"Page request failed for {url}: {exc}"
            ) from exc

    def _normalize_response(self, response: Any, requested_url: str) -> OpenedPage:
        try:
            final_url = _validate_public_url(response.geturl(), self._resolver)
            status = int(response.getcode())
            if status < 200 or status >= 300:
                raise PageOpenExecutionError(
                    f"Page returned HTTP {status} for {requested_url}"
                )
            content_encoding = str(response.headers.get("Content-Encoding") or "")
            if content_encoding.lower() not in {"", "identity"}:
                raise PageOpenNotImplemented(
                    f"Page content encoding is not supported: {content_encoding}"
                )
            content_type_header = str(response.headers.get("Content-Type") or "")
            content_type = content_type_header.split(";", 1)[0].strip().lower()
            if content_type not in _ALLOWED_CONTENT_TYPES:
                shown = content_type or "missing"
                raise PageOpenNotImplemented(
                    f"Page content type is not supported: {shown}"
                )
            raw = _read_bounded(response, self.max_response_bytes)
        finally:
            response.close()

        text = raw.decode(_content_charset(content_type_header), errors="replace")
        title, lines = _normalize_page_text(text, content_type)
        if not lines:
            raise PageOpenExecutionError(
                f"Page returned no readable text for {final_url}"
            )
        return OpenedPage(url=final_url, title=title, lines=lines)


def _validate_public_url(url: str, resolver: Callable[..., Iterable[Any]]) -> str:
    if not isinstance(url, str) or not url.strip():
        raise PageOpenInvalidRequest("open.ref_id must be a non-empty URL")
    try:
        parsed = urlsplit(url.strip())
        hostname = parsed.hostname
    except ValueError as exc:
        raise PageOpenInvalidRequest("open.ref_id is not a valid URL") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise PageOpenNotImplemented(
            "open.ref_id must be a direct public HTTP(S) URL; stored references are not implemented"
        )
    if parsed.username is not None or parsed.password is not None:
        raise PageOpenInvalidRequest("open.ref_id must not contain URL credentials")
    if not hostname:
        raise PageOpenInvalidRequest("open.ref_id must include a hostname")
    hostname = hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(_BLOCKED_HOST_SUFFIXES):
        raise PageOpenInvalidRequest("open.ref_id hostname is not public")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise PageOpenInvalidRequest("open.ref_id contains an invalid port") from exc

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            addresses = list(resolver(hostname, port, type=socket.SOCK_STREAM))
        except OSError as exc:
            raise PageOpenExecutionError(
                f"Could not resolve page hostname {hostname}: {exc}"
            ) from exc
        if not addresses:
            raise PageOpenExecutionError(f"Could not resolve page hostname {hostname}")
        resolved_ips = {entry[4][0] for entry in addresses}
        if any(not _is_public_ip(value) for value in resolved_ips):
            raise PageOpenInvalidRequest("open.ref_id resolves to a non-public address")
    else:
        if not literal_ip.is_global:
            raise PageOpenInvalidRequest("open.ref_id address is not public")

    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, "")
    )


def _is_public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def _content_charset(content_type: str) -> str:
    match = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type, re.I)
    charset = match.group(1) if match else "utf-8"
    try:
        codecs.lookup(charset)
    except LookupError:
        return "utf-8"
    return charset


def _read_bounded(response: Any, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(_READ_CHUNK_BYTES, max_bytes + 1 - total))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > max_bytes:
            raise PageOpenExecutionError(f"Page response exceeds {max_bytes} bytes")
        chunks.append(chunk)


class _ReadableHTMLParser(HTMLParser):
    _SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})
    _BLOCK_TAGS = frozenset(
        {
            "article",
            "aside",
            "blockquote",
            "br",
            "dd",
            "div",
            "dl",
            "dt",
            "figcaption",
            "footer",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "hr",
            "li",
            "main",
            "nav",
            "ol",
            "p",
            "pre",
            "section",
            "table",
            "td",
            "th",
            "tr",
            "ul",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        self._parts.append(data)

    def result(self) -> tuple[str | None, tuple[str, ...]]:
        title = " ".join(" ".join(self._title_parts).split()).strip() or None
        return title, _normalize_text_lines("".join(self._parts))


def _extract_html(value: str) -> tuple[str | None, tuple[str, ...]]:
    parser = _ReadableHTMLParser()
    try:
        parser.feed(value[:_MAX_RENDERED_CHARS])
        parser.close()
    except (AssertionError, ValueError) as exc:
        raise PageOpenExecutionError(f"Could not parse page HTML: {exc}") from exc
    return parser.result()


def _normalize_page_text(
    value: str, content_type: str
) -> tuple[str | None, tuple[str, ...]]:
    if content_type == "text/plain":
        return None, _normalize_text_lines(value)
    return _extract_html(value)


def _normalize_text_lines(value: str) -> tuple[str, ...]:
    lines: list[str] = []
    for raw_line in value[:_MAX_RENDERED_CHARS].splitlines():
        line = " ".join(raw_line.split())
        if line and (not lines or line != lines[-1]):
            lines.append(line)
        if len(lines) >= _MAX_RENDERED_LINES:
            break
    return tuple(lines)
