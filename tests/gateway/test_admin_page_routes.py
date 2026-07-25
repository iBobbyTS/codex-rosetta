"""Tests for admin page URL routes."""

from __future__ import annotations

import asyncio
import importlib.resources
import json

import pytest

from codex_rosetta._vendor.httpserver import Request
from codex_rosetta.gateway.app import create_app
from codex_rosetta.gateway.admin.static import load_admin_asset, load_admin_html
from codex_rosetta.gateway.config import GatewayConfig


def _make_app():
    config = GatewayConfig(
        {
            "providers": {
                "test-provider": {
                    "provider": "custom",
                    "api_key": "sk-test",
                    "base_url": "https://api.example.test/v1",
                    "api_type": "chat",
                }
            },
            "model_groups": {
                "test": {
                    "provider": "test-provider",
                    "type": "llm",
                    "models": {"gpt-test": {"upstream_model": "gpt-5.6-terra"}},
                }
            },
            "server": {
                "admin_password": "test-admin-password",
                "api_keys": [
                    {
                        "id": "test-client",
                        "label": "Test client",
                        "key": "test-gateway-key",
                    }
                ],
            },
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
        "/admin/tools",
        "/admin/tools/",
        "/admin/network-search",
        "/admin/network-search/",
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
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert b'<div id="app"></div>' in response.body
    assert b"/admin/assets/" in response.body


def test_admin_i18n_dictionary_has_matching_language_keys() -> None:
    package_files = importlib.resources.files("codex_rosetta.gateway.admin")
    translations = json.loads(
        package_files.joinpath("admin_i18n.json").read_text("utf-8")
    )

    assert set(translations) == {"en", "zh"}
    assert translations["en"].keys() == translations["zh"].keys()


def test_admin_entry_has_no_inline_script_or_style() -> None:
    admin_html = load_admin_html()

    assert '<script type="module"' in admin_html
    assert "<script>" not in admin_html
    assert "<style" not in admin_html


def test_manifest_allows_only_generated_assets() -> None:
    package_files = importlib.resources.files("codex_rosetta.gateway.admin")
    manifest = json.loads(
        package_files.joinpath("dist", "manifest.json").read_text("utf-8")
    )
    entry = next(iter(manifest.values()))

    script = load_admin_asset(entry["file"])

    assert script.content_type == "text/javascript; charset=utf-8"
    assert script.body
    with pytest.raises(FileNotFoundError):
        load_admin_asset("../admin_i18n.json")
    with pytest.raises(FileNotFoundError):
        load_admin_asset("assets/not-in-manifest.js")


def test_manifest_bundles_all_provider_logos() -> None:
    package_files = importlib.resources.files("codex_rosetta.gateway.admin")
    manifest = json.loads(
        package_files.joinpath("dist", "manifest.json").read_text("utf-8")
    )
    logo_assets = manifest["admin.html"]["assets"]

    assert len(logo_assets) == 12
    assert any(
        path.startswith("assets/opencode-") and path.endswith(".png")
        for path in logo_assets
    )
    assert all(path.startswith("assets/") for path in logo_assets)
    for path in logo_assets:
        logo = load_admin_asset(path)
        assert logo.content_type in {"image/png", "image/svg+xml"}
        assert logo.body

    script = load_admin_asset(manifest["admin.html"]["file"])
    assert b"cdn.jsdelivr.net" not in script.body


def test_admin_asset_route_uses_immutable_cache_policy() -> None:
    app = _make_app()
    package_files = importlib.resources.files("codex_rosetta.gateway.admin")
    manifest = json.loads(
        package_files.joinpath("dist", "manifest.json").read_text("utf-8")
    )
    path = "/admin/" + next(iter(manifest.values()))["file"]

    response = asyncio.run(app._dispatch(_request(app, path)))

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
