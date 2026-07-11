"""Route-level tests for the shared Admin JSON-object contract."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from typing import Any, cast

import pytest

from codex_rosetta._vendor.httpserver import JSONResponse, Request, Response
from codex_rosetta.gateway.app import create_app
from codex_rosetta.gateway.config import GatewayConfig
from codex_rosetta.observability.request_log import RequestLogEntry


def _config_data() -> dict[str, Any]:
    return {
        "providers": {
            "test-provider": {
                "api_key": "sk-test",
                "base_url": "https://api.example.test/v1",
                "type": "openai",
            }
        },
        "models": {"gpt-test": "test-provider"},
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


@pytest.mark.parametrize("value", [[], None, "text", 1, True, 1.25])
@pytest.mark.parametrize(
    ("method", "path", "authenticated"),
    [
        ("POST", "/admin/api/login", False),
        ("PUT", "/admin/api/config/providers/new-provider", True),
        ("PUT", "/admin/api/config/models/new-model", True),
        ("PUT", "/admin/api/config/model-groups/new-group", True),
        ("PUT", "/admin/api/config/server", True),
        ("POST", "/admin/api/config/models", True),
        ("POST", "/admin/api/keys", True),
        ("PUT", "/admin/api/keys/test-client", True),
        ("POST", "/admin/api/test", True),
        ("POST", "/admin/api/profiling/enable", True),
    ],
)
def test_admin_json_routes_reject_non_object_bodies(
    tmp_path,
    method: str,
    path: str,
    authenticated: bool,
    value: object,
):
    config_data = _config_data()
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    app = create_app(GatewayConfig(config_data), config_path=str(config_path))
    headers = {"content-type": "application/json"}
    if authenticated:
        headers["x-admin-token"] = getattr(app, "auth_state").admin_token
    request = Request(
        method=method,
        path=path,
        query_string="",
        headers=headers,
        body=json.dumps(value).encode("utf-8"),
        client_addr=("198.51.100.10", 12345),
        app=app,
    )

    try:
        response = asyncio.run(app._dispatch(request))
        assert response.status_code == 400
        assert isinstance(response, JSONResponse)
        assert json.loads(response.body) == {"error": "JSON body must be an object"}
    finally:
        persistence = getattr(app, "persistence", None)
        if persistence is not None:
            persistence.close()


def test_profiling_rejects_non_integer_request_count(tmp_path):
    config_data = _config_data()
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    app = create_app(GatewayConfig(config_data), config_path=str(config_path))
    request = Request(
        method="POST",
        path="/admin/api/profiling/enable",
        query_string="",
        headers={"x-admin-token": getattr(app, "auth_state").admin_token},
        body=json.dumps({"requests": "not-an-integer"}).encode("utf-8"),
        client_addr=("198.51.100.10", 12345),
        app=app,
    )

    try:
        response = asyncio.run(app._dispatch(request))
        assert response.status_code == 400
        assert isinstance(response, JSONResponse)
        assert json.loads(response.body) == {"error": "'requests' must be an integer"}
    finally:
        persistence = getattr(app, "persistence", None)
        if persistence is not None:
            persistence.close()


def _admin_get(app: Any, path: str, query_string: str = "") -> Response:
    request = Request(
        method="GET",
        path=path,
        query_string=query_string,
        headers={"x-admin-token": getattr(app, "auth_state").admin_token},
        body=b"",
        client_addr=("198.51.100.10", 12345),
        app=app,
    )
    return asyncio.run(app._dispatch(request))


def test_profiling_download_static_route_returns_zip():
    app = cast(Any, create_app(GatewayConfig(_config_data())))
    app.profiler_state.results.append(
        {
            "model": "test/model",
            "timestamp": "2026-07-10T12:34:56+00:00",
            "html": "<html>profile</html>",
        }
    )

    response = _admin_get(app, "/admin/api/profiling/results/download")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        assert archive.namelist() == ["profile-0-test_model-2026-07-10T123456.html"]
        assert archive.read(archive.namelist()[0]) == b"<html>profile</html>"


@pytest.mark.parametrize(
    ("path", "query_string"),
    [
        ("/admin/api/metrics", "seconds=bad"),
        ("/admin/api/metrics", "seconds=0"),
        ("/admin/api/metrics", "seconds=-1"),
        ("/admin/api/metrics", "seconds=301"),
        ("/admin/api/metrics", "seconds=1&seconds=2"),
        ("/admin/api/requests", "limit=bad"),
        ("/admin/api/requests", "limit=0"),
        ("/admin/api/requests", "limit=1001"),
        ("/admin/api/requests", "limit=1&limit=2"),
        ("/admin/api/requests", "offset=-1"),
        ("/admin/api/requests", "offset=1000001"),
        ("/admin/api/error-dumps", "limit=bad"),
        ("/admin/api/error-dumps", "limit=0"),
        ("/admin/api/error-dumps", "offset=-1"),
    ],
)
def test_admin_observability_rejects_invalid_integer_queries(
    path: str,
    query_string: str,
):
    app = cast(Any, create_app(GatewayConfig(_config_data())))

    response = _admin_get(app, path, query_string)

    assert response.status_code == 400
    assert "error" in json.loads(response.body)


def test_admin_observability_integer_defaults_and_pagination_remain_valid():
    app = cast(Any, create_app(GatewayConfig(_config_data())))
    for model in ("first", "second", "third"):
        app.request_log.add(
            RequestLogEntry.create(
                model=model,
                source_provider="openai_responses",
                target_provider="openai_chat",
                is_stream=False,
                status_code=200,
                duration_ms=1.0,
            )
        )

    metrics_response = _admin_get(app, "/admin/api/metrics")
    page_response = _admin_get(
        app,
        "/admin/api/requests",
        "limit=1&offset=1",
    )

    assert metrics_response.status_code == 200
    assert page_response.status_code == 200
    page = json.loads(page_response.body)
    assert page["total"] == 3
    assert [entry["model"] for entry in page["entries"]] == ["second"]
