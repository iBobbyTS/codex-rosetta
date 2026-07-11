"""Security tests for Google URL-image retrieval."""

from __future__ import annotations

import urllib.error
import urllib.request
import time
from unittest.mock import MagicMock, patch

import pytest

from codex_rosetta.converters.google_genai.image_fetch import (
    ImageFetchError,
    ImageFetchTimeoutError,
    ImageFetchPolicy,
    _PinnedHTTPHandler,
    _PinnedHTTPSHandler,
    _SafeRedirectHandler,
    _create_public_connection,
    _validate_public_url,
    fetch_image_url,
)
from codex_rosetta.pipeline import ConversionError, ConversionPipeline


class _Response:
    def __init__(self, chunks: list[bytes], headers: dict[str, str]) -> None:
        self._chunks = iter(chunks)
        self.headers = headers
        self.closed = False

    def read(self, _size: int) -> bytes:
        return next(self._chunks, b"")

    def close(self) -> None:
        self.closed = True


def _address_info(*addresses: str) -> list[tuple]:
    return [(2, 1, 6, "", (address, 443)) for address in addresses]


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "2001:db8::1",
        "::1",
    ],
)
def test_validate_public_url_rejects_non_public_addresses(address: str):
    with patch(
        "codex_rosetta.converters.google_genai.image_fetch.socket.getaddrinfo",
        return_value=_address_info(address),
    ):
        with pytest.raises(ImageFetchError, match="not publicly routable"):
            _validate_public_url("https://images.example.test/private.png")


def test_validate_public_url_rejects_mixed_public_and_private_dns_results():
    with patch(
        "codex_rosetta.converters.google_genai.image_fetch.socket.getaddrinfo",
        return_value=_address_info("93.184.216.34", "10.0.0.1"),
    ):
        with pytest.raises(ImageFetchError, match="not publicly routable"):
            _validate_public_url("https://images.example.test/image.png")


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("file:///etc/passwd", "scheme is not supported"),
        ("https://user:secret@example.test/image.png", "credentials are not allowed"),
        ("https:///image.png", "host is missing"),
    ],
)
def test_validate_public_url_rejects_unsafe_url_shapes(url: str, message: str):
    with pytest.raises(ImageFetchError, match=message):
        _validate_public_url(url)


def test_redirect_handler_revalidates_target_and_enforces_limit():
    request = urllib.request.Request("https://public.example.test/image.png")
    handler = _SafeRedirectHandler(max_redirects=1)
    with patch(
        "codex_rosetta.converters.google_genai.image_fetch.socket.getaddrinfo",
        return_value=_address_info("127.0.0.1"),
    ):
        with pytest.raises(ImageFetchError, match="not publicly routable"):
            handler.redirect_request(
                request,
                object(),
                302,
                "Found",
                {},
                "http://localhost/internal",
            )

    with patch(
        "codex_rosetta.converters.google_genai.image_fetch._validate_public_url",
        return_value="https://public.example.test/next.png",
    ):
        with pytest.raises(ImageFetchError, match="redirected too many times"):
            handler.redirect_request(
                request,
                object(),
                302,
                "Found",
                {},
                "https://public.example.test/next.png",
            )


def test_fetch_disables_environment_proxy_when_policy_has_no_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://stale-proxy.example:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://stale-proxy.example:8080")
    response = _Response([b"image", b""], {"Content-Type": "image/png"})
    opener = MagicMock()
    opener.open.return_value = response

    with (
        patch(
            "codex_rosetta.converters.google_genai.image_fetch._validate_public_url",
            return_value="https://public.example.test/image.png",
        ),
        patch(
            "codex_rosetta.converters.google_genai.image_fetch.urllib.request.build_opener",
            return_value=opener,
        ) as build_opener,
    ):
        body, media_type = fetch_image_url("https://public.example.test/image.png")

    proxy_handler = build_opener.call_args.args[0]
    assert proxy_handler.proxies == {}
    assert any(
        isinstance(handler, _PinnedHTTPHandler)
        for handler in build_opener.call_args.args
    )
    assert any(
        isinstance(handler, _PinnedHTTPSHandler)
        for handler in build_opener.call_args.args
    )
    assert body == b"image"
    assert media_type == "image/png"
    assert response.closed is True


def test_fetch_uses_only_explicit_proxy():
    response = _Response([b"image", b""], {"Content-Type": "image/jpeg"})
    opener = MagicMock()
    opener.open.return_value = response
    policy = ImageFetchPolicy(proxy_url="http://app-proxy.example:9090")

    with (
        patch(
            "codex_rosetta.converters.google_genai.image_fetch._validate_public_url",
            return_value="https://public.example.test/image.jpg",
        ),
        patch(
            "codex_rosetta.converters.google_genai.image_fetch.urllib.request.build_opener",
            return_value=opener,
        ) as build_opener,
    ):
        fetch_image_url("https://public.example.test/image.jpg", policy)

    proxy_handler = build_opener.call_args.args[0]
    assert proxy_handler.proxies == {
        "http": "http://app-proxy.example:9090",
        "https": "http://app-proxy.example:9090",
    }
    assert not any(
        isinstance(handler, (_PinnedHTTPHandler, _PinnedHTTPSHandler))
        for handler in build_opener.call_args.args
    )


def test_direct_connection_pins_validated_numeric_address():
    connected_socket = MagicMock()
    with (
        patch(
            "codex_rosetta.converters.google_genai.image_fetch.socket.getaddrinfo",
            return_value=_address_info("93.184.216.34"),
        ),
        patch(
            "codex_rosetta.converters.google_genai.image_fetch.socket.create_connection",
            return_value=connected_socket,
        ) as create_connection,
    ):
        result = _create_public_connection(("images.example.test", 443), 5.0)

    assert result is connected_socket
    create_connection.assert_called_once_with(("93.184.216.34", 443), 5.0, None)


@pytest.mark.parametrize(
    ("headers", "chunks", "message"),
    [
        ({"Content-Type": "text/plain"}, [b"not an image"], "content type"),
        (
            {"Content-Type": "image/png", "Content-Length": "5"},
            [b"image"],
            "too large",
        ),
        ({"Content-Type": "image/png"}, [b"1234", b"5"], "too large"),
    ],
)
def test_fetch_rejects_non_image_and_oversized_responses(
    headers: dict[str, str],
    chunks: list[bytes],
    message: str,
):
    response = _Response(chunks, headers)
    opener = MagicMock()
    opener.open.return_value = response
    policy = ImageFetchPolicy(max_bytes=4)
    with (
        patch(
            "codex_rosetta.converters.google_genai.image_fetch._validate_public_url",
            return_value="https://public.example.test/image.png",
        ),
        patch(
            "codex_rosetta.converters.google_genai.image_fetch.urllib.request.build_opener",
            return_value=opener,
        ),
    ):
        with pytest.raises(ImageFetchError, match=message):
            fetch_image_url("https://public.example.test/image.png", policy)
    assert response.closed is True


def test_fetch_wraps_network_errors_without_leaking_url():
    secret_url = "https://public.example.test/image.png?token=secret"
    opener = MagicMock()
    opener.open.side_effect = urllib.error.URLError(f"failed for {secret_url}")
    with (
        patch(
            "codex_rosetta.converters.google_genai.image_fetch._validate_public_url",
            return_value=secret_url,
        ),
        patch(
            "codex_rosetta.converters.google_genai.image_fetch.urllib.request.build_opener",
            return_value=opener,
        ),
    ):
        with pytest.raises(ImageFetchError) as raised:
            fetch_image_url(secret_url)

    assert str(raised.value) == "Image download failed"
    assert secret_url not in str(raised.value)


def test_fetch_uses_one_deadline_across_slow_body_reads():
    class _SlowResponse(_Response):
        def read(self, _size: int) -> bytes:
            time.sleep(0.03)
            return super().read(_size)

    response = _SlowResponse(
        [b"a", b"b", b"c", b""],
        {"Content-Type": "image/png"},
    )
    opener = MagicMock()
    opener.open.return_value = response
    policy = ImageFetchPolicy(timeout_seconds=0.05)

    with (
        patch(
            "codex_rosetta.converters.google_genai.image_fetch._validate_public_url",
            return_value="https://public.example.test/image.png",
        ),
        patch(
            "codex_rosetta.converters.google_genai.image_fetch.urllib.request.build_opener",
            return_value=opener,
        ),
    ):
        started = time.monotonic()
        with pytest.raises(ImageFetchTimeoutError, match="timed out"):
            fetch_image_url("https://public.example.test/image.png", policy)

    assert time.monotonic() - started < 0.15
    assert response.closed is True


def test_direct_fetch_rejects_dns_result_after_deadline():
    def _slow_dns(*_args, **_kwargs):
        time.sleep(0.04)
        return _address_info("93.184.216.34")

    with patch(
        "codex_rosetta.converters.google_genai.image_fetch.socket.getaddrinfo",
        side_effect=_slow_dns,
    ):
        with pytest.raises(ImageFetchTimeoutError, match="timed out"):
            fetch_image_url(
                "https://public.example.test/image.png",
                ImageFetchPolicy(timeout_seconds=0.01),
            )


def test_responses_to_google_pipeline_rejects_loopback_image_url():
    pipeline = ConversionPipeline("openai_responses", "google")
    body = {
        "model": "gemini-test",
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": "http://127.0.0.1:8080/internal",
                    }
                ],
            }
        ],
    }

    with pytest.raises(ConversionError, match="not publicly routable") as raised:
        pipeline.convert_request(body)

    assert raised.value.phase == "ir_to_target"
