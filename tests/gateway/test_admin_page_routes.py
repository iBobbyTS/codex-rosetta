"""Tests for admin page URL routes."""

from __future__ import annotations

import asyncio

import pytest

from codex_rosetta._vendor.httpserver import Request
from codex_rosetta.gateway.app import create_app
from codex_rosetta.gateway.config import GatewayConfig


def _make_app():
    config = GatewayConfig(
        {
            "providers": {
                "test-provider": {
                    "api_key": "sk-test",
                    "base_url": "https://api.example.test/v1",
                    "type": "openai",
                }
            },
            "models": {"gpt-test": "test-provider"},
            "server": {},
        }
    )
    return create_app(config)


def _request(app, path: str) -> Request:
    return Request(
        method="GET",
        path=path,
        query_string="",
        headers={},
        body=b"",
        client_addr=("127.0.0.1", 12345),
        app=app,
    )


@pytest.mark.parametrize(
    "path",
    [
        "/admin",
        "/admin/",
        "/admin/providers",
        "/admin/providers/",
        "/admin/models",
        "/admin/keys",
        "/admin/keys/",
        "/admin/web-search",
        "/admin/web-search/",
        "/admin/dashboard",
        "/admin/logs",
        "/admin/gateway-logs",
    ],
)
def test_admin_page_routes_serve_admin_html(path: str):
    app = _make_app()

    response = asyncio.run(app._dispatch(_request(app, path)))

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert b'class="admin-nav"' in response.body
