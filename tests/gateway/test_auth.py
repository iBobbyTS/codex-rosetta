"""Gateway auth hook unit tests."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from codex_rosetta.gateway.auth import (
    AuthState,
    api_key_label_var,
    api_key_principal_var,
    create_auth_hook,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    path: str,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    query_params: dict[str, list[str]] | None = None,
) -> MagicMock:
    """Build a minimal mock request matching httpserver conventions."""
    req = MagicMock()
    req.path = path
    req.method = method
    req.headers = headers or {}
    req.query_params = query_params or {}
    return req


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# No API keys configured
# ---------------------------------------------------------------------------


class TestNoApiKey:
    """A misconfigured empty key set never opens protected APIs."""

    def test_health_is_public_but_protected_api_is_rejected(self):
        state = AuthState({}, {}, None, admin_password="admin-password")
        hook = create_auth_hook(state)

        assert _run(hook(_make_request("/health"))) is None
        for path in ["/v1/responses", "/v1/models"]:
            resp = _run(hook(_make_request(path)))
            assert resp is not None
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# With API keys
# ---------------------------------------------------------------------------


class TestWithApiKey:
    """When api_key is configured, requests must provide valid credentials."""

    KEY = "test-gateway-key-123"

    @pytest.fixture()
    def hook(self):
        state = AuthState(
            {self.KEY: "test-principal"},
            {},
            None,
            admin_password="admin-password",
        )
        return create_auth_hook(state)

    # --- Health is always public ---
    def test_health_no_auth(self, hook: Any):
        resp = _run(hook(_make_request("/health", method="GET")))
        assert resp is None

    # --- OpenAI Responses ---
    def test_openai_responses_valid(self, hook: Any):
        req = _make_request(
            "/v1/responses",
            headers={"authorization": f"Bearer {self.KEY}"},
        )
        assert _run(hook(req)) is None

    def test_openai_responses_missing(self, hook: Any):
        req = _make_request("/v1/responses")
        resp = _run(hook(req))
        assert resp is not None
        assert resp.status_code == 401

    def test_openai_responses_wrong(self, hook: Any):
        req = _make_request(
            "/v1/responses",
            headers={"authorization": "Bearer wrong-key"},
        )
        resp = _run(hook(req))
        assert resp is not None
        assert resp.status_code == 401

    def test_openai_responses_ignores_anthropic_key_shape(self, hook: Any):
        req = _make_request("/v1/responses", headers={"x-api-key": self.KEY})
        resp = _run(hook(req))
        assert resp is not None
        assert resp.status_code == 401

    def test_openai_responses_ignores_google_key_shape(self, hook: Any):
        req = _make_request(
            "/v1/responses",
            headers={"x-goog-api-key": self.KEY},
            query_params={"key": [self.KEY]},
        )
        resp = _run(hook(req))
        assert resp is not None
        assert resp.status_code == 401

    # --- Models list ---
    def test_models_list_valid(self, hook: Any):
        req = _make_request(
            "/v1/models",
            method="GET",
            headers={"authorization": f"Bearer {self.KEY}"},
        )
        assert _run(hook(req)) is None

    # --- The /v1 namespace fails closed, including removed endpoints ---
    @pytest.mark.parametrize(
        "path,headers,query_params",
        [
            ("/v1", {}, None),
            ("/v1/chat/completions", {}, None),
            ("/v1/messages", {"x-api-key": KEY}, None),
            ("/v1/embeddings", {}, None),
        ],
    )
    def test_removed_v1_paths_require_api_key_before_routing(
        self,
        hook: Any,
        path: str,
        headers: dict[str, str],
        query_params: dict[str, list[str]] | None,
    ):
        req = _make_request(path, headers=headers, query_params=query_params)
        response = _run(hook(req))
        assert response is not None
        assert response.status_code == 401

    # --- Other provider namespaces remain outside API-key auth ---
    @pytest.mark.parametrize(
        "path,headers,query_params",
        [
            (
                "/v1beta/models/gemini:generateContent",
                {"x-goog-api-key": KEY},
                {"key": [KEY]},
            ),
            ("/v1beta/models", {"x-goog-api-key": KEY}, None),
        ],
    )
    def test_non_v1_downstream_paths_not_api_key_protected(
        self,
        hook: Any,
        path: str,
        headers: dict[str, str],
        query_params: dict[str, list[str]] | None,
    ):
        req = _make_request(path, headers=headers, query_params=query_params)
        assert _run(hook(req)) is None

    # --- Admin uses its own mandatory auth ---
    def test_admin_html_no_auth(self, hook: Any):
        req = _make_request("/admin", method="GET")
        assert _run(hook(req)) is None

    def test_admin_api_requires_auth(self, hook: Any):
        req = _make_request("/admin/api/config", method="GET")
        resp = _run(hook(req))
        assert resp is not None
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Multiple API keys
# ---------------------------------------------------------------------------


class TestMultiKey:
    """When multiple API keys are configured via api_key_set."""

    KEYS = {"key-alpha", "key-beta", "key-gamma"}

    @pytest.fixture()
    def hook(self):
        state = AuthState(
            {key: f"principal-{key}" for key in self.KEYS},
            {},
            None,
            admin_password="admin-password",
        )
        return create_auth_hook(state)

    def test_first_key_valid(self, hook: Any):
        req = _make_request(
            "/v1/responses",
            headers={"authorization": "Bearer key-alpha"},
        )
        assert _run(hook(req)) is None

    def test_second_key_valid(self, hook: Any):
        req = _make_request(
            "/v1/responses",
            headers={"authorization": "Bearer key-beta"},
        )
        assert _run(hook(req)) is None

    def test_third_key_valid(self, hook: Any):
        req = _make_request(
            "/v1/responses",
            headers={"authorization": "Bearer key-gamma"},
        )
        assert _run(hook(req)) is None

    def test_invalid_key_rejected(self, hook: Any):
        req = _make_request(
            "/v1/responses",
            headers={"authorization": "Bearer wrong-key"},
        )
        resp = _run(hook(req))
        assert resp is not None
        assert resp.status_code == 401

    def test_missing_key_rejected(self, hook: Any):
        req = _make_request("/v1/responses")
        resp = _run(hook(req))
        assert resp is not None
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Internal token
# ---------------------------------------------------------------------------


class TestInternalToken:
    """Internal token bypasses API key auth for admin panel test requests."""

    KEY = "real-api-key"
    INTERNAL = "rsk-internal-abc123"

    @pytest.fixture()
    def hook(self):
        state = AuthState(
            {self.KEY: "real-principal"},
            {},
            self.INTERNAL,
            admin_password="admin-password",
        )
        return create_auth_hook(state)

    def test_internal_token_accepted(self, hook: Any):
        req = _make_request(
            "/v1/responses",
            headers={"authorization": f"Bearer {self.INTERNAL}"},
        )
        assert _run(hook(req)) is None

    def test_real_key_still_works(self, hook: Any):
        req = _make_request(
            "/v1/responses",
            headers={"authorization": f"Bearer {self.KEY}"},
        )
        assert _run(hook(req)) is None

    def test_wrong_key_still_rejected(self, hook: Any):
        req = _make_request(
            "/v1/responses",
            headers={"authorization": "Bearer wrong"},
        )
        resp = _run(hook(req))
        assert resp is not None
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Key label tracking
# ---------------------------------------------------------------------------


async def _run_and_get_identity(
    hook: Any, req: Any
) -> tuple[Any, str | None, str | None]:
    """Run auth and return response, display label, and stable principal."""
    resp = await hook(req)
    return resp, api_key_label_var.get(), api_key_principal_var.get()


class TestKeyLabelTracking:
    """API key label is attached to contextvars for logging."""

    KEYS = {"key-prod", "key-dev"}
    LABELS = {"key-prod": "Production", "key-dev": "Development"}
    PRINCIPALS = {"key-prod": "prod-id", "key-dev": "dev-id"}
    INTERNAL = "rsk-internal-test"

    @pytest.fixture()
    def hook(self):
        state = AuthState(
            self.PRINCIPALS,
            self.LABELS,
            self.INTERNAL,
            admin_password="admin-password",
        )
        return create_auth_hook(state)

    def test_label_attached_for_prod_key(self, hook: Any):
        req = _make_request(
            "/v1/responses",
            headers={"authorization": "Bearer key-prod"},
        )
        _, label, principal = _run(_run_and_get_identity(hook, req))
        assert label == "Production"
        assert principal == "prod-id"

    def test_label_attached_for_dev_key(self, hook: Any):
        req = _make_request(
            "/v1/responses",
            headers={"authorization": "Bearer key-dev"},
        )
        _, label, principal = _run(_run_and_get_identity(hook, req))
        assert label == "Development"
        assert principal == "dev-id"

    def test_internal_token_label(self, hook: Any):
        req = _make_request(
            "/v1/responses",
            headers={"authorization": f"Bearer {self.INTERNAL}"},
        )
        _, label, principal = _run(_run_and_get_identity(hook, req))
        assert label == "internal"
        assert principal == "__admin_internal__"
