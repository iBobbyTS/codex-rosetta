"""Tests for the bounded static-page implementation of Codex open."""

from __future__ import annotations

import asyncio
import socket
from email.message import Message
from typing import Any
from urllib.error import HTTPError

import pytest

from codex_rosetta.gateway.codex_page import (
    PageOpenExecutionError,
    PageOpenInvalidRequest,
    PageOpenNotImplemented,
    StaticPageHTTPClient,
)


def _public_resolver(
    host: str, port: int, *, type: socket.SocketKind
) -> list[tuple[Any, ...]]:
    del host, type
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


class _FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        url: str = "https://example.com/docs",
        content_type: str = "text/html; charset=utf-8",
        status: int = 200,
    ) -> None:
        self._body = body
        self._url = url
        self._status = status
        self._offset = 0
        self.closed = False
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def read(self, amount: int) -> bytes:
        chunk = self._body[self._offset : self._offset + amount]
        self._offset += len(chunk)
        return chunk

    def geturl(self) -> str:
        return self._url

    def getcode(self) -> int:
        return self._status

    def close(self) -> None:
        self.closed = True


def test_static_html_is_normalized_without_script_content() -> None:
    response = _FakeResponse(
        b"""
        <html><head><title> Example Docs </title><script>secret()</script></head>
        <body><h1>Welcome</h1><p>Read the <strong>guide</strong>.</p></body></html>
        """
    )
    client = StaticPageHTTPClient(
        opener=lambda request, timeout: response,
        resolver=_public_resolver,
    )

    page = asyncio.run(client.open("https://example.com/docs#fragment"))

    assert page.url == "https://example.com/docs"
    assert page.title == "Example Docs"
    rendered = page.format_for_model()
    assert "L0: Example Docs" in rendered
    assert "Welcome" in rendered
    assert "Read the guide." in rendered
    assert "secret" not in rendered
    assert response.closed


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://[::1]/admin",
        "http://localhost/admin",
        "file:///etc/passwd",
        "https://user:password@example.com/",
    ],
)
def test_non_public_or_non_http_urls_are_rejected_before_request(url: str) -> None:
    calls: list[str] = []

    def opener(request: Any, timeout: float) -> _FakeResponse:
        del timeout
        calls.append(request.full_url)
        return _FakeResponse(b"not reached")

    client = StaticPageHTTPClient(opener=opener, resolver=_public_resolver)

    with pytest.raises((PageOpenInvalidRequest, PageOpenNotImplemented)):
        asyncio.run(client.open(url))
    assert calls == []


def test_redirect_target_is_revalidated_before_following() -> None:
    calls: list[str] = []

    def opener(request: Any, timeout: float) -> _FakeResponse:
        del timeout
        calls.append(request.full_url)
        headers = Message()
        headers["Location"] = "http://127.0.0.1/private"
        raise HTTPError(request.full_url, 302, "Found", headers, None)

    client = StaticPageHTTPClient(opener=opener, resolver=_public_resolver)

    with pytest.raises(PageOpenInvalidRequest, match="not public"):
        asyncio.run(client.open("https://example.com/start"))
    assert calls == ["https://example.com/start"]


def test_dns_resolution_to_private_address_is_rejected() -> None:
    def private_resolver(
        host: str, port: int, *, type: socket.SocketKind
    ) -> list[tuple[Any, ...]]:
        del host, type
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]

    client = StaticPageHTTPClient(
        opener=lambda request, timeout: _FakeResponse(b"not reached"),
        resolver=private_resolver,
    )

    with pytest.raises(PageOpenInvalidRequest, match="non-public"):
        asyncio.run(client.open("https://internal.example/"))


def test_pdf_and_oversized_pages_are_rejected() -> None:
    pdf_client = StaticPageHTTPClient(
        opener=lambda request, timeout: _FakeResponse(
            b"%PDF", content_type="application/pdf"
        ),
        resolver=_public_resolver,
    )
    with pytest.raises(PageOpenNotImplemented, match="application/pdf"):
        asyncio.run(pdf_client.open("https://example.com/file.pdf"))

    large_client = StaticPageHTTPClient(
        max_response_bytes=4,
        opener=lambda request, timeout: _FakeResponse(b"12345"),
        resolver=_public_resolver,
    )
    with pytest.raises(PageOpenExecutionError, match="exceeds 4 bytes"):
        asyncio.run(large_client.open("https://example.com/large"))
