"""Tests for app-owned Admin login authentication and rate limiting."""

from __future__ import annotations

import asyncio
import hmac
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from codex_rosetta.gateway.admin import runtime as runtime_module
from codex_rosetta.gateway.admin.routes import auth as auth_routes
from codex_rosetta.gateway.admin.runtime import (
    DEFAULT_LOGIN_MAX_ATTEMPTS,
    AdminLoginLimiter,
    AdminRuntimeState,
)


def _app(*, limiter: AdminLoginLimiter | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        auth_state=SimpleNamespace(
            admin_password="correct-password",
            admin_token="admin-token",
        ),
        admin_runtime_state=AdminRuntimeState(login_limiter=limiter),
    )


def _request(
    app: SimpleNamespace,
    *,
    password: object = "wrong-password",
    client_ip: str = "198.51.100.10",
    headers: dict[str, str] | None = None,
) -> SimpleNamespace:
    request = SimpleNamespace(
        app=app,
        client_addr=(client_ip, 12345),
        headers=headers or {},
    )
    request.json = lambda: {"password": password}
    return request


def _body(response: Any) -> dict[str, object]:
    return json.loads(response.body.decode("utf-8"))


def test_client_ip_ignores_untrusted_forwarded_header() -> None:
    request = _request(
        _app(),
        headers={"x-forwarded-for": "203.0.113.99"},
    )

    assert auth_routes._get_client_ip(request) == "198.51.100.10"


def test_rotating_forwarded_header_does_not_bypass_login_lockout() -> None:
    app = _app()
    for index in range(DEFAULT_LOGIN_MAX_ATTEMPTS):
        response = asyncio.run(
            auth_routes.admin_login(
                _request(
                    app,
                    headers={"x-forwarded-for": f"203.0.113.{index}"},
                )
            )
        )
        assert response.status_code == 401

    response = asyncio.run(
        auth_routes.admin_login(
            _request(
                app,
                password="correct-password",
                headers={"x-forwarded-for": "203.0.113.250"},
            )
        )
    )

    assert response.status_code == 429


def test_login_failure_store_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: now[0])
    limiter = AdminLoginLimiter(capacity=3)

    for index in range(4):
        now[0] += 1
        limiter.record_failure(f"198.51.100.{index}")

    assert limiter.entry_count == 3
    assert "198.51.100.0" not in limiter._failures


def test_inactive_login_failure_is_swept(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: now[0])
    limiter = AdminLoginLimiter(entry_ttl_seconds=10)
    limiter.record_failure("198.51.100.10")

    now[0] += 11

    assert limiter.check("198.51.100.11") == (False, 0.0)
    assert limiter.entry_count == 0


def test_admin_password_uses_constant_time_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compare_digest = Mock(wraps=hmac.compare_digest)
    monkeypatch.setattr(auth_routes.hmac, "compare_digest", compare_digest)

    response = asyncio.run(
        auth_routes.admin_login(_request(_app(), password="correct-password"))
    )

    assert response.status_code == 200
    assert _body(response) == {"ok": True, "token": "admin-token"}
    compare_digest.assert_called_once_with("correct-password", "correct-password")


def test_failed_logins_in_one_app_do_not_lock_another_app() -> None:
    app_a = _app()
    app_b = _app()
    for _ in range(DEFAULT_LOGIN_MAX_ATTEMPTS):
        response = asyncio.run(auth_routes.admin_login(_request(app_a)))
        assert response.status_code == 401

    response = asyncio.run(
        auth_routes.admin_login(_request(app_b, password="correct-password"))
    )

    assert response.status_code == 200
    assert app_a.admin_runtime_state is not app_b.admin_runtime_state
    assert (
        app_a.admin_runtime_state.login_limiter
        is not app_b.admin_runtime_state.login_limiter
    )
