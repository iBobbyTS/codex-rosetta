"""Pure-mock redirect policy tests for bounded auxiliary HTTP requests."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from codex_rosetta._vendor.httpclient import (
    DEFAULT_MAX_REDIRECTS,
    CaseInsensitiveDict,
    StreamingResponse,
)
from codex_rosetta.gateway.transport._base import UpstreamResponseTooLargeError
from codex_rosetta.gateway.transport.http.transport import request_bounded_response


class _FakeWriter:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _FakeClient:
    def __init__(self, response: StreamingResponse) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> StreamingResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self._response


def _streaming_response(
    status_code: int,
    body: bytes,
) -> tuple[StreamingResponse, _FakeWriter]:
    reader = asyncio.StreamReader()
    reader.feed_data(body)
    reader.feed_eof()
    writer = _FakeWriter()
    response = StreamingResponse._from_async(
        status_code,
        CaseInsensitiveDict(
            {
                "Location": "https://target.test/private",
                "Content-Length": str(len(body)),
            }
        ),
        "https://source.test/start",
        reader,
        cast(asyncio.StreamWriter, writer),
        False,
        len(body),
        1.0,
    )
    return response, writer


@pytest.mark.asyncio
async def test_bounded_request_disables_redirect_following_and_preserves_3xx() -> None:
    response, writer = _streaming_response(302, b"redirect-body")
    client = _FakeClient(response)

    bounded = await request_bounded_response(
        client,
        "POST",
        "https://source.test/start",
        headers={"Authorization": "Bearer secret"},
        json={"private": True},
    )

    assert bounded.status_code == 302
    assert bounded.headers["Location"] == "https://target.test/private"
    assert bounded.content == b"redirect-body"
    assert client.calls[0]["follow_redirects"] is False
    assert "max_redirects" not in client.calls[0]
    assert writer.closed


@pytest.mark.asyncio
async def test_bounded_redirect_uses_error_body_limit() -> None:
    response, writer = _streaming_response(302, b"redirect-body")
    client = _FakeClient(response)

    with pytest.raises(UpstreamResponseTooLargeError, match="exceeds 5 bytes"):
        await request_bounded_response(
            client,
            "GET",
            "https://source.test/start",
            max_success_bytes=100,
            max_error_bytes=5,
        )

    assert writer.closed


@pytest.mark.asyncio
async def test_bounded_request_enables_existing_redirect_policy_when_allowed() -> None:
    response, writer = _streaming_response(200, b"ok")
    client = _FakeClient(response)

    bounded = await request_bounded_response(
        client,
        "GET",
        "https://source.test/start",
        allow_redirects=True,
    )

    assert bounded.status_code == 200
    assert client.calls[0]["follow_redirects"] is True
    assert client.calls[0]["max_redirects"] == DEFAULT_MAX_REDIRECTS
    assert writer.closed
