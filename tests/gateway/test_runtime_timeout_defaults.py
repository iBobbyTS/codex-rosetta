"""Regression contract for production runtime timeout defaults."""

from codex_rosetta.converters.google_genai.image_fetch import ImageFetchPolicy
from codex_rosetta.gateway import (
    app as gateway_app,
    codex_page,
    desktop_sidecar,
    web_run_health,
    web_run_supervisor,
    web_search,
)
from codex_rosetta.gateway.admin import runtime as admin_runtime
from codex_rosetta.gateway.admin.routes import (
    config as admin_config_routes,
    observability as observability_routes,
)
from codex_rosetta.gateway.config import (
    DEFAULT_WEB_RUN_SIDECAR_TIMEOUT_SECONDS,
    MAX_WEB_RUN_SIDECAR_TIMEOUT_SECONDS,
)
from codex_rosetta.gateway.resources.web_run import bing_search, google_search
from codex_rosetta.gateway.transport.http.client_pool import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
)
from codex_rosetta.gateway.web_run_sidecar import WebRunSidecarHTTPClient


def test_gateway_and_auxiliary_timeout_defaults_are_extended() -> None:
    assert gateway_app._INBOUND_REQUEST_LINE_TIMEOUT_SECONDS == 15.0
    assert gateway_app._INBOUND_HEADER_TIMEOUT_SECONDS == 30.0
    assert gateway_app._INBOUND_BODY_TIMEOUT_SECONDS == 120.0
    assert DEFAULT_HTTP_TIMEOUT_SECONDS == 600.0
    assert ImageFetchPolicy().timeout_seconds == 120.0
    assert codex_page.StaticPageHTTPClient().timeout == 60.0
    assert web_search.TavilyHTTPClient("test-token").timeout == 120.0


def test_sidecar_admin_and_browser_timeout_defaults_are_extended() -> None:
    sidecar = WebRunSidecarHTTPClient("http://web-run:8080", "test-token")

    assert DEFAULT_WEB_RUN_SIDECAR_TIMEOUT_SECONDS == 300.0
    assert MAX_WEB_RUN_SIDECAR_TIMEOUT_SECONDS == 600.0
    assert sidecar._timeout == 300.0
    assert web_run_health.WEB_RUN_HEALTH_TIMEOUT_SECONDS == 5.0
    assert web_run_supervisor.WEB_RUN_STARTUP_TIMEOUT_SECONDS == 300.0
    assert admin_runtime.DEFAULT_TEST_TASK_TIMEOUT_SECONDS == 900.0
    assert observability_routes._NETWORK_DIAGNOSTICS_TIMEOUT_SECONDS == 60.0
    assert admin_config_routes._PROVIDER_MODEL_DISCOVERY_TIMEOUT_SECONDS == 60.0
    assert google_search._SEARCH_TIMEOUT_MS == 120_000
    assert bing_search._SEARCH_TIMEOUT_MS == 120_000


def test_desktop_bind_budget_is_fifteen_seconds() -> None:
    assert (
        desktop_sidecar._STARTUP_BIND_ATTEMPTS
        * desktop_sidecar._STARTUP_BIND_POLL_SECONDS
        == 15.0
    )
