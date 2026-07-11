"""Regression coverage for bounded, per-app upstream error logging."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from codex_rosetta.gateway import logging as gateway_logging
from codex_rosetta.gateway.admin.routes import _shared
from codex_rosetta.gateway.config import GatewayConfig
from codex_rosetta.gateway.logging import UpstreamErrorLogState


def _config(token: str) -> GatewayConfig:
    return GatewayConfig(
        {
            "server": {
                "admin_password": "test-admin-password",
                "api_keys": [{"id": "caller", "key": token, "label": "caller"}],
            }
        }
    )


def test_upstream_error_sanitizer_is_targeted_single_line_and_bounded() -> None:
    state = UpstreamErrorLogState({"sk-live-token"}, max_chars=140)
    safe = state.sanitize(
        "提示🙂 password=keep secret=keep client_secret=keep "
        "api_key=remove Authorization: Bearer bearer-secret "
        "configured=sk-live-token\r\nFORGED\u2028" + "x" * 200
    )

    assert len(safe) == 140
    assert safe.endswith("...[truncated]")
    assert "password=keep" in safe
    assert "secret=keep" in safe
    assert "client_secret=keep" in safe
    assert "remove" not in safe
    assert "bearer-secret" not in safe
    assert "sk-live-token" not in safe
    assert "\n" not in safe
    assert "\r" not in safe
    assert "\u2028" not in safe


def test_upstream_error_json_redacts_only_token_fields() -> None:
    state = UpstreamErrorLogState()
    safe = state.sanitize(
        '{"prompt":"keep PII","password":"keep","secret":"keep",'
        '"client_secret":"keep","access_token":"remove",'
        '"api_key":"remove-too"}'
    )

    assert '"prompt":"keep PII"' in safe
    assert '"password":"keep"' in safe
    assert '"secret":"keep"' in safe
    assert '"client_secret":"keep"' in safe
    assert "remove" not in safe
    assert safe.count("[REDACTED]") == 2


def test_upstream_error_cap_is_exact_even_when_shorter_than_suffix() -> None:
    assert UpstreamErrorLogState(max_chars=5).sanitize("x" * 20) == "...[t"


@pytest.mark.parametrize("is_streaming", [False, True])
def test_log_upstream_error_never_falls_back_to_raw_text(
    monkeypatch: pytest.MonkeyPatch,
    is_streaming: bool,
) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        gateway_logging._logger, "error", lambda *args: calls.append(args)
    )

    gateway_logging.log_upstream_error(
        502,
        "Authorization: Bearer sk-raw\nFORGED",
        is_streaming=is_streaming,
    )

    safe = calls[0][-1]
    assert "sk-raw" not in safe
    assert "\n" not in safe
    assert r"\n" in safe
    assert calls[0][2] == ("streaming" if is_streaming else "non-streaming")


def test_hot_reload_and_rollback_keep_error_redactors_isolated_per_app() -> None:
    initial_a = _config("token-a-old")
    app_a = SimpleNamespace(
        gateway_config=initial_a,
        admin_cors_origins=(),
        internal_token="internal-a",
        upstream_error_log_state=UpstreamErrorLogState({"token-a-old", "internal-a"}),
    )
    app_b = SimpleNamespace(
        gateway_config=_config("token-b"),
        admin_cors_origins=(),
        internal_token="internal-b",
        upstream_error_log_state=UpstreamErrorLogState({"token-b", "internal-b"}),
    )

    rollback = _shared._activate_gateway_config(
        SimpleNamespace(app=app_a),
        _config("token-a-new"),
    )

    assert "token-a-new" not in app_a.upstream_error_log_state.sanitize("token-a-new")
    assert app_a.upstream_error_log_state.sanitize("token-a-old") == "token-a-old"
    assert "token-b" not in app_b.upstream_error_log_state.sanitize("token-b")
    assert app_b.upstream_error_log_state.sanitize("token-a-new") == "token-a-new"

    _shared._rollback_gateway_activation(SimpleNamespace(app=app_a), rollback)
    assert "token-a-old" not in app_a.upstream_error_log_state.sanitize("token-a-old")
    assert app_a.upstream_error_log_state.sanitize("token-a-new") == "token-a-new"
