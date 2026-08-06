"""Tests for admin config route handlers."""

from __future__ import annotations

import asyncio
import json
import sys
import tomllib
from types import SimpleNamespace
from typing import Any, cast

import pytest

from codex_rosetta.gateway.admin.routes import _shared
from codex_rosetta.gateway import web_run_health
from codex_rosetta.gateway.admin.routes.config import (
    delete_model_group,
    delete_provider,
    get_config,
    get_network_search_status,
    put_codex_settings,
    put_model_group,
    put_provider,
    put_server_settings,
    reload_config,
)
from codex_rosetta.gateway.admin.routes.observability import get_provider_key
from codex_rosetta.gateway.app import create_app
from codex_rosetta.gateway.auth import AuthState
from codex_rosetta.gateway.config import (
    CONFIGURED_RESPONSES_WEB_SEARCH_MODELS,
    GatewayConfig,
    MAX_WEB_SEARCH_PROVIDERS,
)
from codex_rosetta.gateway.logging import BodyLogState
from codex_rosetta.gateway.stream_trace import StreamTraceState
from codex_rosetta.observability.metrics import MetricsCollector
from codex_rosetta.observability.request_log import RequestLogEntry


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _config_data() -> dict[str, Any]:
    return {
        "providers": {
            "openai": {
                "provider": "openai",
                "api_type": "chat",
                "base_url": "https://api.example.com",
                "api_key": "sk-test",
            }
        },
        "model_groups": {
            "OpenAI": {
                "provider": "openai",
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


class _PersistenceState:
    def __init__(self, redactor: Any) -> None:
        self._redactor = redactor
        self.success_max = 50000
        self.error_max = 10000

    def prepare_update(
        self,
        values: set[str],
        *,
        success_max: int,
        error_max: int,
    ) -> tuple[set[str], int, int]:
        return set(values), success_max, error_max

    def commit_update(
        self, prepared: tuple[set[str], int, int]
    ) -> tuple[Any, int, int]:
        rollback = (self._redactor, self.success_max, self.error_max)
        self._redactor, self.success_max, self.error_max = prepared
        return rollback

    def rollback_update(self, rollback: tuple[Any, int, int]) -> None:
        self._redactor, self.success_max, self.error_max = rollback


def _log_entry(index: int, *, status_code: int = 200) -> dict[str, Any]:
    return RequestLogEntry.create(
        model=f"model-{index}",
        source_provider="openai_responses",
        target_provider="openai_chat",
        is_stream=False,
        status_code=status_code,
        duration_ms=1.0,
    ).to_dict()


def test_put_server_settings_updates_stream_trace_and_runtime_state(tmp_path):
    """Admin stream trace settings persist to config and hot-reload state."""
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(_config_data()), encoding="utf-8")

    initial_config = GatewayConfig(_config_data())
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app)
    request.json = lambda: {
        "stream_trace": {
            "enabled": True,
            "filter": "glm,opencode",
            "path": "~/trace/log.jsonl",
            "max_string_chars": 1234,
        }
    }

    response = _run(put_server_settings(request))

    assert response.status_code == 200
    assert "admin_password" not in json.loads(response.body.decode("utf-8"))["server"]
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["server"]["stream_trace"] == {
        "enabled": True,
        "filter": "glm,opencode",
        "path": "~/trace/log.jsonl",
        "max_string_chars": 1234,
    }
    assert app.stream_trace_state.config.enabled is True
    assert app.stream_trace_state.config.filter == "glm,opencode"
    assert app.stream_trace_state.config.path == "~/trace/log.jsonl"


@pytest.mark.parametrize(
    ("value", "expected_bytes"),
    [
        (64, 64 * 1024 * 1024),
        (128, 128 * 1024 * 1024),
        (256, 256 * 1024 * 1024),
        (512, 512 * 1024 * 1024),
        (1024, 1024 * 1024 * 1024),
        ("unlimited", sys.maxsize),
    ],
)
def test_put_server_settings_updates_request_body_limit_at_runtime(
    tmp_path, value, expected_bytes
):
    """Admin body-limit settings persist and affect new requests immediately."""
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(_config_data()), encoding="utf-8")
    initial_config = GatewayConfig(_config_data())
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        max_body_size=initial_config.request_body_limit_bytes,
        auth_state=None,
        stream_trace_state=None,
    )
    request = SimpleNamespace(app=app, json=lambda: {"request_body_limit_mb": value})

    response = _run(put_server_settings(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["server"]["request_body_limit_mb"] == value
    assert app.gateway_config.request_body_limit_config_value == value
    assert app.max_body_size == expected_bytes


def test_put_server_settings_rejects_invalid_request_body_limit(tmp_path):
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(_config_data()).encode()
    config_path.write_bytes(original)
    initial_config = GatewayConfig(_config_data())
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        max_body_size=initial_config.request_body_limit_bytes,
        auth_state=None,
        stream_trace_state=None,
    )
    request = SimpleNamespace(app=app, json=lambda: {"request_body_limit_mb": 129})

    response = _run(put_server_settings(request))

    assert response.status_code == 400
    assert b"request_body_limit_mb must be one of" in response.body
    assert config_path.read_bytes() == original
    assert app.gateway_config is initial_config
    assert app.max_body_size == 128 * 1024 * 1024


def test_reload_config_rotates_runtime_admin_credentials(tmp_path):
    config_path = tmp_path / "config.jsonc"
    initial_data = _config_data()
    config_path.write_text(json.dumps(initial_data), encoding="utf-8")
    initial_config = GatewayConfig(initial_data)
    auth_state = AuthState(
        dict(initial_config.api_key_principals),
        dict(initial_config.api_key_labels),
        "internal-token",
        initial_config.admin_password,
    )
    previous_token = auth_state.admin_token
    captured_tokens: set[str] = set()
    persistence = _PersistenceState(captured_tokens)
    metrics = MetricsCollector()
    metrics.update_token_values(initial_config.token_values)
    health_invalidations = []
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=None,
        persistence=persistence,
        metrics=metrics,
        internal_token="internal-token",
        auth_state=auth_state,
        web_run_health_state=SimpleNamespace(
            invalidate=lambda: health_invalidations.append(True)
        ),
    )

    updated_data = _config_data()
    updated_data["server"]["admin_password"] = "rotated-admin-password"
    updated_data["server"]["api_keys"][0]["key"] = "rotated-gateway-token"
    updated_data["server"]["proxy"] = "http://user:ordinary-proxy-password@example.test"
    updated_data["server"]["request_body_limit_mb"] = 512
    updated_data["providers"]["openai"]["api_key"] = "rotated-provider-token"
    updated_data["providers"]["openai"]["client_secret"] = "ordinary-client-secret"
    config_path.write_text(json.dumps(updated_data), encoding="utf-8")

    response = _run(reload_config(SimpleNamespace(app=app)))

    assert response.status_code == 200
    assert auth_state.admin_password == "rotated-admin-password"
    assert auth_state.admin_token is not None
    assert auth_state.admin_token != previous_token
    assert app.max_body_size == 512 * 1024 * 1024
    assert health_invalidations == [True]
    assert persistence._redactor == {
        "internal-token",
        "rotated-gateway-token",
        "rotated-provider-token",
    }
    assert (
        metrics.redact_sensitive(
            "rotated-provider-token prompt=user@example.com password=ordinary-password"
        )
        == "[REDACTED] prompt=user@example.com password=ordinary-password"
    )


def _runtime_redactors(app: Any) -> list[Any]:
    return [
        app.stream_trace_state._redactor,
        app.upstream_error_log_state._redactor,
        app.body_log_state._redactor,
        app.persistence._redactor,
        app.metrics._redactor,
    ]


def _assert_exact_tokens(
    redactors: list[Any],
    *,
    hidden: tuple[str, ...],
    visible: tuple[str, ...] = (),
) -> None:
    for redactor in redactors:
        for token in hidden:
            assert token not in redactor.redact(f"before {token} after")
        for token in visible:
            assert redactor.redact(token) == token


def test_startup_registers_every_legacy_provider_key_in_all_runtime_redactors(
    tmp_path,
) -> None:
    data = _config_data()
    raw_keys = " first-startup , , startup-prefix,startup-prefix-long,first-startup "
    data["providers"]["openai"]["api_key"] = raw_keys
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    config = GatewayConfig(data)
    app = cast(Any, create_app(config, config_path=str(config_path)))

    try:
        assert config.providers["openai"].credential_values == ("first-startup",)
        assert raw_keys in config.token_values
        _assert_exact_tokens(
            _runtime_redactors(app),
            hidden=("first-startup", "startup-prefix", "startup-prefix-long"),
        )
    finally:
        app.persistence.close()


def test_hot_reload_and_rollback_atomically_swap_all_provider_credentials(
    tmp_path,
) -> None:
    old_tokens = ("old-first", "old-prefix", "old-prefix-long")
    new_tokens = ("new-first", "new-prefix", "new-prefix-long")
    initial_data = _config_data()
    initial_data["providers"]["openai"]["api_key"] = ",".join(old_tokens)
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(initial_data), encoding="utf-8")
    initial_config = GatewayConfig(initial_data)
    app = cast(Any, create_app(initial_config, config_path=str(config_path)))

    candidate = _config_data()
    candidate["providers"]["openai"]["api_key"] = (
        " new-first, ,new-prefix,new-prefix-long,new-first "
    )
    new_config = GatewayConfig(candidate)

    try:
        prepared = _shared._prepare_gateway_activation(
            SimpleNamespace(app=app), new_config
        )
        assert app.gateway_config is initial_config
        _assert_exact_tokens(
            _runtime_redactors(app), hidden=old_tokens, visible=new_tokens
        )

        rollback = _shared._activate_gateway_config(
            SimpleNamespace(app=app), new_config, prepared
        )

        assert app.gateway_config is new_config
        assert app.gateway_config.providers["openai"].credential_values == (
            "new-first",
        )
        _assert_exact_tokens(
            _runtime_redactors(app), hidden=new_tokens, visible=old_tokens
        )

        _shared._rollback_gateway_activation(SimpleNamespace(app=app), rollback)

        assert app.gateway_config is initial_config
        assert app.gateway_config.providers["openai"].credential_values == (
            "old-first",
        )
        _assert_exact_tokens(
            _runtime_redactors(app), hidden=old_tokens, visible=new_tokens
        )
    finally:
        app.persistence.close()


def test_reload_config_preserves_special_environment_password_as_data(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    special = 'admin","credential_visible":true,"injected":"\\line\nrest'
    monkeypatch.setenv("SPECIAL_ADMIN_PASSWORD", special)
    config_path = tmp_path / "config.jsonc"
    stored_data = _config_data()
    stored_data["server"]["admin_password"] = "${SPECIAL_ADMIN_PASSWORD}"
    stored_data["server"]["credential_visible"] = False
    config_path.write_text(json.dumps(stored_data), encoding="utf-8")

    initial_config = GatewayConfig(_config_data())
    auth_state = AuthState(
        dict(initial_config.api_key_principals),
        dict(initial_config.api_key_labels),
        "internal-token",
        initial_config.admin_password,
    )
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=None,
        persistence=None,
        metrics=None,
        internal_token="internal-token",
        auth_state=auth_state,
    )

    response = _run(reload_config(SimpleNamespace(app=app)))

    assert response.status_code == 200
    assert app.gateway_config.admin_password == special
    assert app.gateway_config.credential_visible is False
    assert auth_state.admin_password == special
    assert "injected" not in json.loads(config_path.read_text())["server"]


@pytest.mark.parametrize(
    "failure_stage",
    ["auth", "trace", "body_log", "persistence", "metrics", "cors"],
)
def test_config_prepare_failure_leaves_disk_and_all_runtime_state_unchanged(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
):
    """Every fallible activation stage completes before config persistence."""
    config_path = tmp_path / "config.jsonc"
    initial_data = _config_data()
    initial_data["server"]["admin_cors_origins"] = ["https://old.example"]
    original = json.dumps(initial_data, indent=2).encode()
    config_path.write_bytes(original)

    initial_config = GatewayConfig(initial_data)
    auth_state = AuthState(
        dict(initial_config.api_key_principals),
        dict(initial_config.api_key_labels),
        "internal-token",
        initial_config.admin_password,
    )
    trace_state = StreamTraceState(
        initial_config.stream_trace,
        token_values=initial_config.token_values,
    )
    persistence_redactor = object()
    persistence = _PersistenceState(persistence_redactor)
    body_log_state = BodyLogState(
        enabled=False,
        token_values={"test-gateway-key", "internal-token"},
    )
    metrics_redactor = object()
    metrics = SimpleNamespace(
        _redactor=metrics_redactor,
        prepare_token_values=lambda values: object(),
    )
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        auth_state=auth_state,
        stream_trace_state=trace_state,
        body_log_state=body_log_state,
        persistence=persistence,
        metrics=metrics,
        internal_token="internal-token",
        admin_cors_origins=("https://old.example",),
    )
    request = SimpleNamespace(app=app)

    def _fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"simulated {failure_stage} prepare failure")

    if failure_stage == "auth":
        monkeypatch.setattr(auth_state, "prepare_update", _fail)
    elif failure_stage == "trace":
        monkeypatch.setattr(trace_state, "prepare_update", _fail)
    elif failure_stage == "body_log":
        monkeypatch.setattr(body_log_state, "prepare_update", _fail)
    elif failure_stage == "persistence":
        monkeypatch.setattr(persistence, "prepare_update", _fail)
    elif failure_stage == "metrics":
        monkeypatch.setattr(metrics, "prepare_token_values", _fail)
    else:
        monkeypatch.setattr(_shared, "_prepare_admin_cors_origins", _fail)

    candidate = _config_data()
    candidate["server"]["admin_password"] = "new-admin-password"
    candidate["server"]["api_keys"][0]["key"] = "new-gateway-key"
    candidate["server"]["stream_trace"] = {"enabled": True}
    candidate["server"]["admin_cors_origins"] = ["https://new.example"]
    candidate["debug"] = {"log_bodies": True}

    _config, error = _shared._commit_gateway_config(
        request, str(config_path), candidate
    )

    assert _config is None
    assert error is not None
    assert error.status_code == 500
    assert f"simulated {failure_stage} prepare failure" in error.body.decode()
    assert config_path.read_bytes() == original
    assert app.gateway_config is initial_config
    assert auth_state.admin_password == "test-admin-password"
    assert auth_state.principals == {"test-gateway-key": "test-client"}
    assert trace_state.config is initial_config.stream_trace
    assert body_log_state.enabled is False
    assert "test-gateway-key" not in body_log_state.render("test-gateway-key")
    assert persistence._redactor is persistence_redactor
    assert metrics._redactor is metrics_redactor
    assert app.admin_cors_origins == ("https://old.example",)


def test_config_commit_persists_normalized_cors_and_updates_live_allowlist(tmp_path):
    config_path = tmp_path / "config.jsonc"
    initial_data = _config_data()
    config_path.write_text(json.dumps(initial_data), encoding="utf-8")
    initial_config = GatewayConfig(initial_data)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        auth_state=None,
        stream_trace_state=None,
        persistence=None,
        admin_cors_origins=(),
    )
    candidate = _config_data()
    candidate["server"]["admin_cors_origins"] = [
        "HTTPS://ADMIN.EXAMPLE:443/",
        "https://admin.example",
    ]

    config, error = _shared._commit_gateway_config(
        SimpleNamespace(app=app), str(config_path), candidate
    )

    assert error is None
    assert config is not None
    assert app.admin_cors_origins == ("https://admin.example",)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["server"]["admin_cors_origins"] == ["https://admin.example"]


def test_config_commit_hot_reloads_caps_and_prunes_immediately(tmp_path, monkeypatch):
    monkeypatch.delenv("REQUEST_LOG_SUCCESS_MAX", raising=False)
    monkeypatch.delenv("REQUEST_LOG_ERROR_MAX", raising=False)
    initial_data = _config_data()
    initial_data["server"]["request_log"] = {"success_max": 10, "error_max": 10}
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(initial_data), encoding="utf-8")
    app = cast(
        Any,
        create_app(GatewayConfig(initial_data), config_path=str(config_path)),
    )
    app.persistence.insert_log_entries(
        [_log_entry(index) for index in range(5)]
        + [_log_entry(index, status_code=500) for index in range(5, 9)]
    )
    candidate = _config_data()
    candidate["server"]["request_log"] = {"success_max": 2, "error_max": 1}

    try:
        config, error = _shared._commit_gateway_config(
            SimpleNamespace(app=app),
            str(config_path),
            candidate,
        )

        assert error is None
        assert config is not None
        assert app.gateway_config is config
        assert app.persistence.success_max == 2
        assert app.persistence.error_max == 1
        assert app.persistence.count_success_entries() == 2
        assert app.persistence.count_error_entries() == 1
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["server"]["request_log"] == {
            "success_max": 2,
            "error_max": 1,
        }
    finally:
        app.persistence.close()


def test_config_commit_zero_caps_prunes_both_request_classes(tmp_path, monkeypatch):
    monkeypatch.delenv("REQUEST_LOG_SUCCESS_MAX", raising=False)
    monkeypatch.delenv("REQUEST_LOG_ERROR_MAX", raising=False)
    initial_data = _config_data()
    initial_data["server"]["request_log"] = {"success_max": 10, "error_max": 10}
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(initial_data), encoding="utf-8")
    app = cast(
        Any, create_app(GatewayConfig(initial_data), config_path=str(config_path))
    )
    app.persistence.insert_log_entries(
        [_log_entry(index) for index in range(3)]
        + [_log_entry(index, status_code=500) for index in range(3, 6)]
    )
    candidate = _config_data()
    candidate["server"]["request_log"] = {"success_max": 0, "error_max": 0}

    try:
        config, error = _shared._commit_gateway_config(
            SimpleNamespace(app=app), str(config_path), candidate
        )

        assert error is None
        assert config is not None
        assert app.persistence.count_success_entries() == 0
        assert app.persistence.count_error_entries() == 0
    finally:
        app.persistence.close()


def test_config_write_failure_after_activation_restores_runtime_and_pruned_rows(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("REQUEST_LOG_SUCCESS_MAX", raising=False)
    monkeypatch.delenv("REQUEST_LOG_ERROR_MAX", raising=False)
    initial_data = _config_data()
    initial_data["server"]["request_log"] = {"success_max": 10, "error_max": 10}
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(initial_data).encode("utf-8")
    config_path.write_bytes(original)
    initial_config = GatewayConfig(initial_data)
    app = cast(Any, create_app(initial_config, config_path=str(config_path)))
    app.persistence.insert_log_entries([_log_entry(index) for index in range(5)])
    old_admin_token = app.auth_state.admin_token
    candidate = _config_data()
    candidate["server"]["admin_password"] = "new-admin-password"
    candidate["server"]["request_log"] = {"success_max": 1, "error_max": 1}
    candidate["server"]["request_body_limit_mb"] = 256
    candidate["debug"] = {"log_bodies": True}

    def activate_then_fail(
        _path: str,
        _data: dict[str, Any],
        *,
        activate: Any,
    ) -> None:
        activate()
        raise OSError("simulated post-activation write failure")

    monkeypatch.setattr(_shared, "write_config", activate_then_fail)

    try:
        config, error = _shared._commit_gateway_config(
            SimpleNamespace(app=app),
            str(config_path),
            candidate,
        )

        assert config is None
        assert error is not None
        assert error.status_code == 500
        assert app.gateway_config is initial_config
        assert app.auth_state.admin_password == "test-admin-password"
        assert app.auth_state.admin_token == old_admin_token
        assert app.body_log_state.enabled is False
        assert app.max_body_size == 128 * 1024 * 1024
        assert "test-gateway-key" not in app.body_log_state.render("test-gateway-key")
        assert app.persistence.success_max == 10
        assert app.persistence.error_max == 10
        assert app.persistence.count_success_entries() == 5
        assert config_path.read_bytes() == original
    finally:
        app.persistence.close()


def test_retention_activation_is_isolated_between_apps(tmp_path, monkeypatch):
    monkeypatch.delenv("REQUEST_LOG_SUCCESS_MAX", raising=False)
    monkeypatch.delenv("REQUEST_LOG_ERROR_MAX", raising=False)
    initial_data = _config_data()
    initial_data["server"]["request_log"] = {"success_max": 10, "error_max": 10}
    path_a = tmp_path / "a" / "config.jsonc"
    path_b = tmp_path / "b" / "config.jsonc"
    path_a.parent.mkdir()
    path_b.parent.mkdir()
    path_a.write_text(json.dumps(initial_data), encoding="utf-8")
    path_b.write_text(json.dumps(initial_data), encoding="utf-8")
    app_a = cast(
        Any,
        create_app(GatewayConfig(initial_data), config_path=str(path_a)),
    )
    app_b = cast(
        Any,
        create_app(GatewayConfig(initial_data), config_path=str(path_b)),
    )
    app_a.persistence.insert_log_entries([_log_entry(index) for index in range(5)])
    app_b.persistence.insert_log_entries([_log_entry(index) for index in range(5)])
    updated_data = _config_data()
    updated_data["server"]["request_log"] = {"success_max": 1, "error_max": 2}

    try:
        _shared._activate_gateway_config(
            SimpleNamespace(app=app_a),
            GatewayConfig(updated_data),
        )

        assert app_a.persistence.success_max == 1
        assert app_a.persistence.count_success_entries() == 1
        assert app_b.persistence.success_max == 10
        assert app_b.persistence.count_success_entries() == 5
    finally:
        app_a.persistence.close()
        app_b.persistence.close()


def test_get_config_masks_tavily_api_key(tmp_path):
    """Admin config canonicalizes and masks a legacy Tavily API key."""
    config = _config_data()
    config["server"]["web_search"] = {"tavily_api_key": "tvly-1234567890"}
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(config).encode("utf-8")
    config_path.write_bytes(original)

    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=GatewayConfig(config),
    )
    request = SimpleNamespace(app=app)

    response = _run(get_config(request))

    assert response.status_code == 200
    body = json.loads(response.body.decode("utf-8"))
    assert body["server"]["web_search"] == {
        "providers": [
            {
                "id": "legacy-0",
                "provider": "tavily",
                "tavily_api_key": "tvly***7890",
            }
        ]
    }
    assert config_path.read_bytes() == original
    assert body["server"]["request_body_limit_mb"] == 128


def test_get_config_masks_all_canonical_tavily_api_keys(tmp_path):
    """Admin config response masks canonical Tavily rows without reordering."""
    raw_keys = ["tvly-primary-1234567890", "tvly-fallback-0987654321"]
    config = _config_data()
    config["providers"]["search-upstream"] = {
        "provider": "openai",
        "api_type": "responses",
        "base_url": "https://search.example.com/v1",
        "api_key": "search-provider-key",
    }
    config["server"]["web_search"] = {
        "providers": [
            {
                "id": "primary",
                "provider": "tavily",
                "tavily_api_key": raw_keys[0],
            },
            {
                "id": "responses",
                "provider": "configured_responses_provider",
                "responses_provider": "search-upstream",
                "responses_model": "gpt-5.6-terra",
            },
            {"id": "local", "provider": "self_hosted_google"},
            {
                "id": "fallback",
                "provider": "tavily",
                "tavily_api_key": raw_keys[1],
            },
        ]
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=GatewayConfig(config),
    )

    response = _run(get_config(SimpleNamespace(app=app)))

    assert response.status_code == 200
    serialized = response.body.decode("utf-8")
    assert all(raw_key not in serialized for raw_key in raw_keys)
    body = json.loads(serialized)
    assert body["server"]["web_search"]["providers"] == [
        {
            "id": "primary",
            "provider": "tavily",
            "tavily_api_key": "tvly***7890",
        },
        {
            "id": "responses",
            "provider": "configured_responses_provider",
            "responses_provider": "search-upstream",
            "responses_model": "gpt-5.6-terra",
        },
        {"id": "local", "provider": "self_hosted_google"},
        {
            "id": "fallback",
            "provider": "tavily",
            "tavily_api_key": "tvly***4321",
        },
    ]
    assert body["web_search_contract"] == {
        "provider_types": [
            "tavily",
            "configured_responses_provider",
            "self_hosted_bing",
            "self_hosted_bing_browser",
            "self_hosted_google",
        ],
        "responses_models": list(CONFIGURED_RESPONSES_WEB_SEARCH_MODELS),
        "max_providers": MAX_WEB_SEARCH_PROVIDERS,
    }


@pytest.mark.parametrize(
    ("legacy", "extra_providers", "expected_masked", "expected_saved"),
    [
        (
            {"provider": "tavily", "tavily_api_key": "tvly-legacy-secret"},
            {},
            {
                "id": "legacy-0",
                "provider": "tavily",
                "tavily_api_key": "tvly***cret",
            },
            {
                "id": "legacy-0",
                "provider": "tavily",
                "tavily_api_key": "tvly-legacy-secret",
            },
        ),
        (
            {
                "provider": "configured_responses_provider",
                "responses_provider": "search-upstream",
                "responses_model": "gpt-5.6-terra",
            },
            {
                "search-upstream": {
                    "provider": "openai",
                    "api_type": "responses",
                    "base_url": "https://search.example.test/v1",
                    "api_key": "responses-search-secret",
                }
            },
            {
                "id": "legacy-0",
                "provider": "configured_responses_provider",
                "responses_provider": "search-upstream",
                "responses_model": "gpt-5.6-terra",
            },
            {
                "id": "legacy-0",
                "provider": "configured_responses_provider",
                "responses_provider": "search-upstream",
                "responses_model": "gpt-5.6-terra",
            },
        ),
        (
            {"provider": "self_hosted_bing_browser"},
            {},
            {"id": "legacy-0", "provider": "self_hosted_bing_browser"},
            {"id": "legacy-0", "provider": "self_hosted_bing_browser"},
        ),
    ],
    ids=["tavily", "responses", "self-hosted"],
)
def test_legacy_web_search_get_then_unchanged_canonical_put_migrates_safely(
    tmp_path,
    legacy,
    extra_providers,
    expected_masked,
    expected_saved,
):
    """Admin GET exposes one canonical row that unchanged PUT safely migrates."""
    data = _config_data()
    data["providers"].update(extra_providers)
    data["server"]["web_search"] = legacy
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(data).encode("utf-8")
    config_path.write_bytes(original)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=GatewayConfig(data),
        auth_state=None,
        stream_trace_state=None,
    )

    get_response = _run(get_config(SimpleNamespace(app=app)))

    assert get_response.status_code == 200
    returned = json.loads(get_response.body)["server"]["web_search"]
    assert returned == {"providers": [expected_masked]}
    assert config_path.read_bytes() == original

    put_response = _run(
        put_server_settings(
            SimpleNamespace(app=app, json=lambda: {"web_search": returned})
        )
    )

    assert put_response.status_code == 200
    assert set(returned) == {"providers"}
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["server"]["web_search"] == {"providers": [expected_saved]}
    assert app.gateway_config.web_search.providers == [expected_saved]


def test_put_server_settings_preserves_masked_web_search_key_and_hot_reloads(
    tmp_path,
):
    config = _config_data()
    config["server"]["web_search"] = {
        "provider": "tavily",
        "tavily_api_key": "tvly-secret-value",
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        auth_state=None,
        stream_trace_state=None,
    )
    request = SimpleNamespace(
        app=app,
        json=lambda: {
            "web_search": {
                "provider": "tavily",
                "tavily_api_key": "tvly***alue",
            }
        },
    )

    response = _run(put_server_settings(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["server"]["web_search"] == {
        "providers": [
            {
                "id": "legacy-0",
                "provider": "tavily",
                "tavily_api_key": "tvly-secret-value",
            }
        ]
    }
    assert (
        app.gateway_config.web_search.providers[0]["tavily_api_key"]
        == "tvly-secret-value"
    )
    assert "tvly-secret-value" in app.gateway_config.token_values
    assert (
        json.loads(response.body)["server"]["web_search"]["providers"][0][
            "tavily_api_key"
        ]
        == "tvly***alue"
    )


def test_put_server_settings_clears_web_search_key(tmp_path):
    config = _config_data()
    config["server"]["web_search"] = {
        "provider": "tavily",
        "tavily_api_key": "tvly-secret-value",
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        auth_state=None,
        stream_trace_state=None,
    )
    request = SimpleNamespace(
        app=app,
        json=lambda: {"web_search": {"provider": "tavily", "tavily_api_key": ""}},
    )

    response = _run(put_server_settings(request))

    assert response.status_code == 200
    assert json.loads(config_path.read_text(encoding="utf-8"))["server"][
        "web_search"
    ] == {"providers": []}
    assert app.gateway_config.web_search.providers == []


def test_put_server_settings_selects_self_hosted_google_and_preserves_tavily_key(
    tmp_path,
):
    config = _config_data()
    config["server"]["web_search"] = {
        "provider": "tavily",
        "tavily_api_key": "tvly-secret-value",
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=GatewayConfig(config),
        auth_state=None,
        stream_trace_state=None,
    )
    request = SimpleNamespace(
        app=app,
        json=lambda: {
            "web_search": {
                "provider": "self_hosted_google",
                "tavily_api_key": "tvly***alue",
            }
        },
    )

    response = _run(put_server_settings(request))

    assert response.status_code == 200
    assert json.loads(config_path.read_text(encoding="utf-8"))["server"][
        "web_search"
    ] == {"providers": [{"id": "legacy-0", "provider": "self_hosted_google"}]}
    assert app.gateway_config.web_search.providers == [
        {"id": "legacy-0", "provider": "self_hosted_google"}
    ]


def test_put_server_settings_selects_configured_responses_provider(tmp_path):
    config = _config_data()
    config["providers"]["search"] = {
        "provider": "openai",
        "api_type": "responses",
        "api_key": "search-secret",
        "base_url": "https://search.example/v1",
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=GatewayConfig(config),
        auth_state=None,
        stream_trace_state=None,
    )
    request = SimpleNamespace(
        app=app,
        json=lambda: {
            "web_search": {
                "provider": "configured_responses_provider",
                "responses_model": "gpt-5.6-terra",
                "responses_provider": "search",
            }
        },
    )

    response = _run(put_server_settings(request))

    assert response.status_code == 200
    assert json.loads(config_path.read_text(encoding="utf-8"))["server"][
        "web_search"
    ] == {
        "providers": [
            {
                "id": "legacy-0",
                "provider": "configured_responses_provider",
                "responses_model": "gpt-5.6-terra",
                "responses_provider": "search",
            }
        ]
    }
    assert app.gateway_config.web_search.providers[0]["responses_provider"] == "search"
    assert (
        app.gateway_config.web_search.providers[0]["responses_model"] == "gpt-5.6-terra"
    )


def test_put_server_settings_rejects_configured_non_responses_provider(tmp_path):
    config = _config_data()
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        auth_state=None,
        stream_trace_state=None,
    )
    request = SimpleNamespace(
        app=app,
        json=lambda: {
            "web_search": {
                "provider": "configured_responses_provider",
                "responses_provider": next(iter(config["providers"])),
            }
        },
    )

    response = _run(put_server_settings(request))

    assert response.status_code == 400
    assert "api_type 'responses'" in json.loads(response.body)["error"]
    assert app.gateway_config is initial_config


def test_put_server_settings_rejects_invalid_web_search_fields(tmp_path):
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(_config_data()).encode()
    config_path.write_bytes(original)
    initial_config = GatewayConfig(_config_data())
    app = SimpleNamespace(config_path=str(config_path), gateway_config=initial_config)
    request = SimpleNamespace(
        app=app,
        json=lambda: {"web_search": {"provider": "other", "token": "legacy"}},
    )

    response = _run(put_server_settings(request))

    assert response.status_code == 400
    assert config_path.read_bytes() == original
    assert app.gateway_config is initial_config


def test_put_server_settings_saves_canonical_search_rows_and_merges_key_by_id(tmp_path):
    data = _config_data()
    data["server"]["web_search"] = {
        "providers": [
            {"id": "tv", "provider": "tavily", "tavily_api_key": "tvly-secret"},
            {"id": "local", "provider": "self_hosted_google"},
        ]
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    initial = GatewayConfig(data)
    request = SimpleNamespace(
        app=SimpleNamespace(config_path=str(config_path), gateway_config=initial),
        json=lambda: {
            "web_search": {
                "providers": [
                    {"id": "tv", "provider": "tavily", "tavily_api_key": "tvly***cret"},
                    {"id": "local", "provider": "self_hosted_google"},
                ]
            }
        },
    )
    response = _run(put_server_settings(request))
    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert (
        saved["server"]["web_search"]["providers"][0]["tavily_api_key"] == "tvly-secret"
    )


@pytest.mark.parametrize(
    ("web_search", "extra_providers", "secrets"),
    [
        (
            {
                "providers": [
                    {
                        "id": "primary",
                        "provider": "tavily",
                        "tavily_api_key": "tvly-canonical-secret",
                    }
                ]
            },
            {},
            {"tvly-canonical-secret"},
        ),
        (
            {
                "providers": [
                    {
                        "id": "responses",
                        "provider": "configured_responses_provider",
                        "responses_provider": "search-upstream",
                        "responses_model": "gpt-5.6-terra",
                    }
                ]
            },
            {
                "search-upstream": {
                    "provider": "openai",
                    "api_type": "responses",
                    "base_url": "https://search.example.test/v1",
                    "api_key": "responses-upstream-secret",
                }
            },
            {"responses-upstream-secret"},
        ),
        (
            {
                "providers": [
                    {
                        "id": "primary",
                        "provider": "tavily",
                        "tavily_api_key": "tvly-multi-row-secret",
                    },
                    {
                        "id": "responses",
                        "provider": "configured_responses_provider",
                        "responses_provider": "search-upstream",
                        "responses_model": "gpt-5.6-terra",
                    },
                    {"id": "local", "provider": "self_hosted_google"},
                ]
            },
            {
                "search-upstream": {
                    "provider": "openai",
                    "api_type": "responses",
                    "base_url": "https://search.example.test/v1",
                    "api_key": "responses-multi-row-secret",
                }
            },
            {"tvly-multi-row-secret", "responses-multi-row-secret"},
        ),
    ],
    ids=["tavily", "responses", "multiple-rows"],
)
def test_put_server_settings_rejects_legacy_page_save_for_canonical_search(
    tmp_path,
    web_search,
    extra_providers,
    secrets,
):
    data = _config_data()
    data["providers"].update(extra_providers)
    data["server"]["web_search"] = web_search
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(data).encode("utf-8")
    config_path.write_bytes(original)
    initial_config = GatewayConfig(data)
    initial_rows = [dict(row) for row in initial_config.web_search.providers]
    initial_tokens = set(initial_config.token_values)
    app = SimpleNamespace(config_path=str(config_path), gateway_config=initial_config)

    get_response = _run(get_config(SimpleNamespace(app=app)))
    assert get_response.status_code == 200
    serialized = get_response.body.decode("utf-8")
    assert all(secret not in serialized for secret in secrets)
    returned_search = json.loads(serialized)["server"]["web_search"]
    assert "provider" not in returned_search
    assert "tavily_api_key" not in returned_search

    legacy_page_payload = {
        "provider": returned_search.get("provider", "tavily"),
        "tavily_api_key": returned_search.get("tavily_api_key", "").strip(),
    }
    response = _run(
        put_server_settings(
            SimpleNamespace(
                app=app,
                json=lambda: {"web_search": legacy_page_payload},
            )
        )
    )

    assert response.status_code == 409
    assert json.loads(response.body) == {
        "error": "Legacy 'web_search' payload cannot replace canonical provider rows"
    }
    assert config_path.read_bytes() == original
    assert app.gateway_config is initial_config
    assert app.gateway_config.web_search.providers == initial_rows
    assert app.gateway_config.token_values == initial_tokens
    assert secrets <= app.gateway_config.token_values


def test_put_server_settings_rejects_unknown_masked_search_row(tmp_path):
    data = _config_data()
    data["server"]["web_search"] = {
        "providers": [
            {"id": "tv", "provider": "tavily", "tavily_api_key": "tvly-secret"}
        ]
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path), gateway_config=GatewayConfig(data)
        ),
        json=lambda: {
            "web_search": {
                "providers": [
                    {
                        "id": "other",
                        "provider": "tavily",
                        "tavily_api_key": "tvly***cret",
                    }
                ]
            }
        },
    )
    response = _run(put_server_settings(request))
    assert response.status_code == 400
    assert b"mask does not match" in response.body


class _FakeAsyncClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None


def test_network_search_status_is_unconfigured_without_sidecar():
    request = SimpleNamespace(
        app=SimpleNamespace(gateway_config=GatewayConfig(_config_data()))
    )

    response = _run(get_network_search_status(request))

    assert json.loads(response.body) == {
        "configured": False,
        "service_online": False,
        "browser_ready": None,
    }


@pytest.mark.parametrize(
    ("health", "expected"),
    [
        ({"status": "ok", "browser_ready": False}, (True, False)),
        ({"status": "ok", "browser_ready": True}, (True, True)),
    ],
)
def test_network_search_status_reports_service_and_browser(
    monkeypatch, health, expected
):
    config = _config_data()
    config["server"]["web_run"] = {
        "base_url": "http://web-run:8080",
        "token": "sidecar-token",
    }
    request = SimpleNamespace(app=SimpleNamespace(gateway_config=GatewayConfig(config)))
    calls = []

    async def fake_request(client, method, url, **kwargs):
        calls.append((client.kwargs, method, url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: health)

    monkeypatch.setattr(web_run_health, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(web_run_health, "request_bounded_response", fake_request)

    response = _run(get_network_search_status(request))

    body = json.loads(response.body)
    assert body == {
        "configured": True,
        "service_online": expected[0],
        "browser_ready": expected[1],
    }
    assert calls[0][0]["timeout"] == 5.0
    assert calls[0][1:3] == ("GET", "http://web-run:8080/health")
    assert calls[0][3] == {
        "max_success_bytes": 64 * 1024,
        "max_error_bytes": 64 * 1024,
    }


def test_network_search_status_hides_unreachable_sidecar_error(monkeypatch):
    config = _config_data()
    config["server"]["web_run"] = {
        "base_url": "http://web-run:8080",
        "token": "sidecar-token",
    }
    request = SimpleNamespace(app=SimpleNamespace(gateway_config=GatewayConfig(config)))

    async def fail_request(*args, **kwargs):
        raise RuntimeError("sensitive upstream detail")

    monkeypatch.setattr(web_run_health, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(web_run_health, "request_bounded_response", fail_request)

    response = _run(get_network_search_status(request))

    assert json.loads(response.body) == {
        "configured": True,
        "service_online": False,
        "browser_ready": None,
    }
    assert b"sensitive upstream detail" not in response.body


def test_get_config_masks_web_run_sidecar_token(tmp_path):
    config = _config_data()
    config["server"]["web_run"] = {
        "base_url": "http://web-run:8080",
        "token": "sidecar-secret-token-1234567890",
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=GatewayConfig(config),
    )

    response = _run(get_config(SimpleNamespace(app=app)))

    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["server"]["web_run"] == {
        "base_url": "http://web-run:8080",
        "token": "side***7890",
    }


@pytest.mark.parametrize("credential_visible", [False, True])
@pytest.mark.parametrize(
    ("stored_password", "runtime_password"),
    [
        ("literal-admin-password", "literal-admin-password"),
        ("${TEST_ADMIN_PASSWORD}", "environment-admin-password"),
    ],
)
def test_get_config_never_returns_admin_password(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    credential_visible: bool,
    stored_password: str,
    runtime_password: str,
):
    """Admin config responses never expose literal or env-backed passwords."""
    monkeypatch.setenv("TEST_ADMIN_PASSWORD", runtime_password)
    config = _config_data()
    config["server"]["admin_password"] = stored_password
    config["server"]["credential_visible"] = credential_visible
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path),
            gateway_config=GatewayConfig.from_raw_with_env(config),
        )
    )

    response = _run(get_config(request))

    assert response.status_code == 200
    body = json.loads(response.body.decode("utf-8"))
    assert "admin_password" not in body["server"]
    assert stored_password not in response.body.decode("utf-8")
    assert runtime_password not in response.body.decode("utf-8")


def test_put_provider_persists_provider_url_and_api_type(tmp_path):
    """Admin persists the supplier while leaving its variant derived."""
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(_config_data()), encoding="utf-8")

    initial_config = GatewayConfig(_config_data())
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "DeepSeek"})
    request.json = lambda: {
        "provider": "deepseek",
        "api_type": "chat",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-new",
        "allow_redirects": True,
        "soft_interrupt": False,
    }

    response = _run(put_provider(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["providers"]["DeepSeek"] == {
        "api_key": "sk-new",
        "base_url": "https://api.deepseek.com",
        "provider": "deepseek",
        "api_type": "chat",
        "allow_redirects": True,
        "soft_interrupt": False,
    }
    assert "type" not in saved["providers"]["DeepSeek"]
    assert app.gateway_config.provider_types["DeepSeek"] == "openai_chat"
    assert app.gateway_config.provider_shim_names["DeepSeek"] == "deepseek"
    assert app.gateway_config.providers["DeepSeek"].allow_redirects is True
    assert app.gateway_config.providers["DeepSeek"].soft_interrupt is False


def test_get_config_canonicalizes_legacy_provider_mask_without_writing(tmp_path):
    data = _config_data()
    data["providers"]["openai"]["api_key"] = (
        " first-provider-secret, discarded-provider-secret "
    )
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(data, indent=2).encode()
    config_path.write_bytes(original)
    config = GatewayConfig(data)
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path),
            gateway_config=config,
            codex_home="",
        )
    )

    response = _run(get_config(request))

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["providers"]["openai"]["api_key"] == "firs***cret"
    assert config._raw_providers["openai"]["api_key"] == "first-provider-secret"
    assert "discarded-provider-secret" in config.token_values
    assert config_path.read_bytes() == original


def test_get_provider_key_returns_first_legacy_credential_without_writing(tmp_path):
    data = _config_data()
    data["providers"]["openai"]["api_key"] = " first-secret, discarded-secret "
    data["server"]["credential_visible"] = True
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(data, indent=2).encode()
    config_path.write_bytes(original)
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path), gateway_config=GatewayConfig(data)
        ),
        path_params={"name": "openai"},
    )

    response = _run(get_provider_key(request))

    assert json.loads(response.body) == {"api_key": "first-secret"}
    assert config_path.read_bytes() == original


@pytest.mark.parametrize("submitted_key", [None, "", "firs***cret"])
def test_put_provider_without_new_key_converges_existing_legacy_csv(
    tmp_path, submitted_key
):
    data = _config_data()
    data["providers"]["openai"]["api_key"] = " first-secret, discarded-secret "
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    initial_config = GatewayConfig(data)
    body = {
        "provider": "openai",
        "api_type": "chat",
        "base_url": "https://api.example.com",
    }
    if submitted_key is not None:
        body["api_key"] = submitted_key
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path),
            gateway_config=initial_config,
            stream_trace_state=StreamTraceState(initial_config.stream_trace),
            auth_state=None,
        ),
        path_params={"name": "openai"},
        json=lambda: body,
    )

    response = _run(put_provider(request))

    assert response.status_code == 200
    assert json.loads(config_path.read_text())["providers"]["openai"]["api_key"] == (
        "first-secret"
    )


def test_put_provider_normalizes_submitted_csv_and_rejects_empty_csv_without_write(
    tmp_path,
):
    data = _config_data()
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    initial_config = GatewayConfig(data)
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path),
            gateway_config=initial_config,
            stream_trace_state=StreamTraceState(initial_config.stream_trace),
            auth_state=None,
        ),
        path_params={"name": "openai"},
    )
    request.json = lambda: {
        "provider": "openai",
        "api_type": "chat",
        "base_url": "https://api.example.com",
        "api_key": " first-new, discarded-new ",
    }

    response = _run(put_provider(request))

    assert response.status_code == 200
    assert json.loads(config_path.read_text())["providers"]["openai"]["api_key"] == (
        "first-new"
    )

    persisted = config_path.read_bytes()
    request.json = lambda: {
        "provider": "openai",
        "api_type": "chat",
        "base_url": "https://api.example.com",
        "api_key": " , , ",
    }
    response = _run(put_provider(request))

    assert response.status_code == 400
    assert config_path.read_bytes() == persisted


def test_put_provider_rejects_soft_interrupt_for_non_chat_protocol(tmp_path):
    config_path = tmp_path / "config.jsonc"
    original = _config_data()
    config_path.write_text(json.dumps(original), encoding="utf-8")
    initial_config = GatewayConfig(original)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "DeepSeek"})
    request.json = lambda: {
        "provider": "deepseek",
        "api_type": "anthropic",
        "base_url": "https://api.deepseek.com/anthropic",
        "api_key": "sk-new",
        "soft_interrupt": True,
    }

    response = _run(put_provider(request))

    assert response.status_code == 400
    assert "supported only for api_type 'chat'" in response.body.decode("utf-8")
    assert json.loads(config_path.read_text(encoding="utf-8")) == original


def test_put_provider_persists_and_hot_loads_force_rosetta_compaction(tmp_path):
    config_path = tmp_path / "config.jsonc"
    original = _config_data()
    config_path.write_text(json.dumps(original), encoding="utf-8")
    initial_config = GatewayConfig(original)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "DeepSeek"})
    request.json = lambda: {
        "provider": "deepseek",
        "api_type": "responses",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-new",
        "force_rosetta_compaction": True,
    }

    response = _run(put_provider(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["providers"]["DeepSeek"]["force_rosetta_compaction"] is True
    assert app.gateway_config.providers["DeepSeek"].force_rosetta_compaction is True

    request.json = lambda: {
        "provider": "deepseek",
        "api_type": "responses",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-new",
        "force_rosetta_compaction": False,
    }
    response = _run(put_provider(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert "force_rosetta_compaction" not in saved["providers"]["DeepSeek"]
    assert app.gateway_config.providers["DeepSeek"].force_rosetta_compaction is False


def test_put_provider_rejects_force_rosetta_compaction_for_chat(tmp_path):
    config_path = tmp_path / "config.jsonc"
    original = _config_data()
    config_path.write_text(json.dumps(original), encoding="utf-8")
    initial_config = GatewayConfig(original)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "DeepSeek"})
    request.json = lambda: {
        "provider": "deepseek",
        "api_type": "chat",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-new",
        "force_rosetta_compaction": True,
    }

    response = _run(put_provider(request))

    assert response.status_code == 400
    assert "supported only for api_type 'responses'" in response.body.decode("utf-8")
    assert json.loads(config_path.read_text(encoding="utf-8")) == original


def test_put_provider_sorts_new_provider_by_name_before_persisting(tmp_path):
    config = _config_data()
    config["providers"]["zulu"] = {
        "api_key": "sk-zulu",
        "base_url": "https://zulu.example.test",
        "provider": "openai",
        "api_type": "chat",
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    initial_config = GatewayConfig(config)
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path),
            gateway_config=initial_config,
            stream_trace_state=StreamTraceState(initial_config.stream_trace),
            auth_state=None,
        ),
        path_params={"name": "Alpha"},
        json=lambda: {
            "provider": "openai",
            "api_type": "chat",
            "base_url": "https://alpha.example.test",
            "api_key": "sk-alpha",
        },
    )

    response = _run(put_provider(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert list(saved["providers"]) == ["Alpha", "openai", "zulu"]
    assert json.loads(response.body)["providers"] == ["Alpha", "openai", "zulu"]


def test_put_provider_sorts_renamed_provider_and_updates_references(tmp_path):
    config = _config_data()
    config["providers"]["Zulu"] = {
        "api_key": "sk-zulu",
        "base_url": "https://zulu.example.test",
        "provider": "openai",
        "api_type": "chat",
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    initial_config = GatewayConfig(config)
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path),
            gateway_config=initial_config,
            stream_trace_state=StreamTraceState(initial_config.stream_trace),
            auth_state=None,
        ),
        path_params={"name": "beta"},
        json=lambda: {
            "rename_from": "openai",
            "provider": "openai",
            "api_type": "chat",
            "base_url": "https://beta.example.test",
        },
    )

    response = _run(put_provider(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert list(saved["providers"]) == ["beta", "Zulu"]
    assert saved["model_groups"]["OpenAI"]["provider"] == "beta"
    assert json.loads(response.body)["providers"] == ["beta", "Zulu"]


def test_put_provider_rename_updates_search_dependency(tmp_path):
    config = _config_data()
    config["providers"]["search"] = {
        "api_key": "search-key",
        "base_url": "https://search.example.test",
        "provider": "openai",
        "api_type": "responses",
    }
    config["server"]["web_search"] = {
        "providers": [
            {
                "id": "r",
                "provider": "configured_responses_provider",
                "responses_provider": "search",
                "responses_model": "gpt-5.6-terra",
            }
        ]
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    initial = GatewayConfig(config)
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path), gateway_config=initial, auth_state=None
        ),
        path_params={"name": "renamed"},
        json=lambda: {
            "rename_from": "search",
            "provider": "openai",
            "api_type": "responses",
            "base_url": "https://new.example.test",
        },
    )
    response = _run(put_provider(request))
    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert (
        saved["server"]["web_search"]["providers"][0]["responses_provider"] == "renamed"
    )


def test_delete_provider_rejects_search_dependency(tmp_path):
    config = _config_data()
    config["providers"]["search"] = {
        "api_key": "search-key",
        "base_url": "https://search.example.test",
        "provider": "openai",
        "api_type": "responses",
    }
    config["server"]["web_search"] = {
        "providers": [
            {
                "id": "r",
                "provider": "configured_responses_provider",
                "responses_provider": "search",
                "responses_model": "gpt-5.6-terra",
            }
        ]
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    request = SimpleNamespace(
        app=SimpleNamespace(config_path=str(config_path)),
        path_params={"name": "search"},
        query_params={},
    )
    response = _run(delete_provider(request))
    assert response.status_code == 409
    assert b"web search rows" in response.body


def _legacy_responses_search_config() -> dict[str, Any]:
    config = _config_data()
    config["providers"]["search"] = {
        "api_key": "search-key",
        "base_url": "https://search.example.test",
        "provider": "openai",
        "api_type": "responses",
    }
    config["server"]["web_search"] = {
        "provider": "configured_responses_provider",
        "responses_provider": "search",
        "responses_model": "gpt-5.6-terra",
    }
    return config


def test_delete_provider_clears_legacy_search_dependency(tmp_path):
    config = _legacy_responses_search_config()
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    initial_config = GatewayConfig(config)
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path),
            gateway_config=initial_config,
            auth_state=None,
        ),
        path_params={"name": "search"},
        query_params={},
    )

    response = _run(delete_provider(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert "search" not in saved["providers"]
    assert "web_search" not in saved["server"]
    assert "search" not in request.app.gateway_config.providers
    assert not request.app.gateway_config.web_search.providers


@pytest.mark.parametrize("failure_phase", ["write", "activate"])
def test_delete_provider_legacy_search_failure_preserves_disk_and_live_config(
    tmp_path,
    monkeypatch,
    failure_phase,
):
    config = _legacy_responses_search_config()
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(config).encode("utf-8")
    config_path.write_bytes(original)
    initial_config = GatewayConfig(config)
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path),
            gateway_config=initial_config,
            auth_state=None,
        ),
        path_params={"name": "search"},
        query_params={},
    )

    if failure_phase == "write":

        def fail_write(*args, **kwargs):
            raise OSError("simulated config write failure")

        monkeypatch.setattr(_shared, "write_config", fail_write)
    else:

        def fail_activation(*args, **kwargs):
            raise RuntimeError("simulated config activation failure")

        monkeypatch.setattr(_shared, "_activate_gateway_config", fail_activation)

    response = _run(delete_provider(request))

    assert response.status_code == 500
    assert config_path.read_bytes() == original
    assert request.app.gateway_config is initial_config
    assert "search" in request.app.gateway_config.providers
    assert (
        request.app.gateway_config.web_search.providers[0]["responses_provider"]
        == "search"
    )


def test_put_provider_rejects_missing_persisted_provider(tmp_path):
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(_config_data())
    config_path.write_text(original, encoding="utf-8")
    initial_config = GatewayConfig(_config_data())
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path), gateway_config=initial_config
        ),
        path_params={"name": "MissingSupplier"},
        json=lambda: {
            "api_type": "chat",
            "base_url": "https://api.example.test",
            "api_key": "sk-new",
        },
    )

    response = _run(put_provider(request))

    assert response.status_code == 400
    assert b"'api_key', 'base_url', and 'provider' are required" in response.body
    assert config_path.read_text(encoding="utf-8") == original
    assert request.app.gateway_config is initial_config


def test_put_provider_persists_direct_responses_protocol(tmp_path):
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(_config_data()), encoding="utf-8")
    initial_config = GatewayConfig(_config_data())
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "Qwen"})
    request.json = lambda: {
        "provider": "qwen",
        "api_type": "responses",
        "base_url": "https://qwen.example.test/v1",
        "api_key": "sk-new",
    }

    response = _run(put_provider(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["providers"]["Qwen"]["api_type"] == "responses"
    assert app.gateway_config.provider_types["Qwen"] == "openai_responses"
    assert app.gateway_config.providers["Qwen"].allow_redirects is False


def test_put_provider_masked_key_preserves_existing_key_with_api_type(tmp_path):
    """Editing a new-style provider with a masked key keeps the old secret."""
    config = _config_data()
    config["providers"]["DeepSeek"] = {
        "api_key": "sk-1234567890",
        "base_url": "https://api.deepseek.com",
        "provider": "deepseek",
        "api_type": "chat",
    }
    config["model_groups"]["DeepSeek"] = {
        "provider": "DeepSeek",
        "type": "llm",
        "models": {"deepseek-test": {"upstream_model": "deepseek-v4-flash"}},
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "DeepSeek"})
    request.json = lambda: {
        "provider": "deepseek",
        "api_type": "chat",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-1***7890",
    }

    response = _run(put_provider(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["providers"]["DeepSeek"]["api_key"] == "sk-1234567890"
    assert saved["providers"]["DeepSeek"]["provider"] == "deepseek"
    assert saved["providers"]["DeepSeek"]["api_type"] == "chat"
    assert "type" not in saved["providers"]["DeepSeek"]


def test_get_config_returns_model_groups_and_effective_models(tmp_path):
    """Admin config exposes grouped management data and expanded runtime models."""
    config = _config_data()
    config["providers"]["openai"]["provider"] = "openai"
    config["models"] = {"standalone": "openai"}
    config["model_groups"] = {
        "OpenAI": {
            "provider": "openai",
            "type": "llm",
            "models": {"grouped": {"upstream_model": "gpt-5.6-terra"}},
        }
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=GatewayConfig(config),
    )
    request = SimpleNamespace(app=app)

    response = _run(get_config(request))

    assert response.status_code == 200
    body = json.loads(response.body.decode("utf-8"))
    assert set(body["models"]) == {"grouped"}
    assert "standalone_models" not in body
    assert body["model_groups"]["OpenAI"]["provider"] == "openai"
    assert body["model_groups"]["OpenAI"]["type"] == "llm"
    assert body["model_groups"]["OpenAI"]["tool_profile"] == "builtin"
    assert body["providers"]["openai"]["default_tool_profile"] == "builtin"
    assert body["providers"]["openai"]["provider"] == "openai"
    assert "validation_error" not in body["providers"]["openai"]
    assert body["known_api_types"] == ["responses", "chat", "anthropic", "google"]
    assert "known_provider_types" not in body
    assert body["tool_profile_presets"] == [
        {
            "id": "builtin",
            "name": "Chat Default（适用于第三方仅提供chat api的模型）",
            "api_types": ["chat"],
        },
        {
            "id": "web-run-injection",
            "name": "web.run 注入（适用于尚未支持/alpha/search端点的中转站）",
            "api_types": ["responses"],
        },
        {
            "id": "responses-tool-mapping",
            "name": "工具映射（适用于第三方模型提供的Responses接口）",
            "api_types": ["responses"],
        },
    ]
    assert body["tool_profile_passthrough_option"] == {
        "id": "passthrough",
        "api_types": ["responses"],
    }
    assert any(
        preset["slug"] == "gpt-5.6-terra" and preset["display_name"] == "GPT-5.6-Terra"
        for preset in body["model_presets"]
    )
    assert any(
        preset["slug"] == "deepseek-v4-pro"
        and preset["identity"] == "DeepSeek V4 Pro Preview"
        for preset in body["model_presets"]
    )
    glm_preset = next(
        preset for preset in body["model_presets"] if preset["slug"] == "glm-5.2"
    )
    assert glm_preset["supported_reasoning_levels"] == ["high", "max"]
    assert body["codex"] == {}
    assert body["model_groups"]["OpenAI"]["models"]["grouped"]["upstream_model"] == (
        "gpt-5.6-terra"
    )
    assert body["model_groups"]["OpenAI"]["models"]["grouped"]["has_overrides"] is False
    assert (
        body["model_groups"]["OpenAI"]["models"]["grouped"]["model_info"][
            "context_window"
        ]
        > 0
    )
    assert all(
        isinstance(level, str)
        for level in body["model_groups"]["OpenAI"]["models"]["grouped"]["model_info"][
            "supported_reasoning_levels"
        ]
    )
    assert (
        body["model_groups"]["OpenAI"]["models"]["grouped"]["model_info"]["identity"]
        == "GPT-5.6-Terra"
    )
    assert body["models"]["grouped"]["provider"] == "openai"


def test_get_config_marks_missing_provider_api_type_invalid(tmp_path):
    valid_config = _config_data()
    runtime_config = GatewayConfig(valid_config)
    invalid_config = json.loads(json.dumps(valid_config))
    invalid_config["providers"]["openai"].pop("api_type")
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(invalid_config), encoding="utf-8")
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path),
            gateway_config=runtime_config,
        )
    )

    response = _run(get_config(request))

    assert response.status_code == 200
    body = json.loads(response.body.decode("utf-8"))
    assert "api_type" not in body["providers"]["openai"]
    assert "default_tool_profile" not in body["providers"]["openai"]
    assert (
        "requires api_type to be one of"
        in body["providers"]["openai"]["validation_error"]
    )
    assert "validation_error" in body["model_groups"]["OpenAI"]
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert "api_type" not in persisted["providers"]["openai"]


def test_get_config_marks_unrecognized_provider_api_type_invalid(tmp_path):
    config = _config_data()
    config["providers"]["openai"]["api_type"] = "removed-protocol"
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path),
            gateway_config=GatewayConfig(_config_data()),
        )
    )

    response = _run(get_config(request))

    assert response.status_code == 200
    body = json.loads(response.body.decode("utf-8"))
    assert body["providers"]["openai"]["api_type"] == "removed-protocol"
    assert (
        "requires api_type to be one of"
        in body["providers"]["openai"]["validation_error"]
    )
    assert "validation_error" in body["model_groups"]["OpenAI"]
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["providers"]["openai"]["api_type"] == "removed-protocol"


@pytest.mark.parametrize(
    ("base_url", "expected_profile"),
    [
        (
            "https://api.openai.com/v1/",
            "passthrough",
        ),
        ("https://relay.example/v1", "passthrough"),
    ],
)
def test_get_config_derives_responses_default_profile_from_authoritative_url(
    tmp_path, base_url, expected_profile
):
    config = _config_data()
    config["providers"]["openai"].update(
        {"api_type": "responses", "base_url": base_url}
    )
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path),
            gateway_config=GatewayConfig(config),
        )
    )

    response = _run(get_config(request))

    body = json.loads(response.body.decode("utf-8"))
    assert body["providers"]["openai"]["default_tool_profile"] == expected_profile


def test_put_model_group_persists_and_reloads_runtime_config(tmp_path):
    """Saving a model group persists grouped config and expands runtime routes."""
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(_config_data()), encoding="utf-8")

    initial_config = GatewayConfig(_config_data())
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "OpenAI"})
    request.json = lambda: {
        "provider": "openai",
        "type": "llm",
        "tool_profile": "builtin",
        "models": {
            "gpt-grouped": {
                "upstream_model": "gpt-5.6-terra",
            }
        },
    }

    response = _run(put_model_group(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["model_groups"]["OpenAI"] == {
        "provider": "openai",
        "type": "llm",
        "tool_profile": "builtin",
        "models": {
            "gpt-grouped": {
                "upstream_model": "gpt-5.6-terra",
            }
        },
    }
    route, _provider = app.gateway_config.resolve("openai_responses", "gpt-grouped")
    assert route.provider_name == "openai"
    assert route.upstream_model == "gpt-5.6-terra"
    assert route.input_modalities == ["text", "image"]
    assert route.tool_profile_name == "builtin"


def test_put_model_group_persists_opencode_sampling_limits(tmp_path):
    """OpenCode model rows persist only declared sampling overrides."""
    config = _config_data()
    config["providers"]["opencode"] = {
        "provider": "opencode_go",
        "api_type": "chat",
        "base_url": "https://opencode.ai/zen/go/v1",
        "api_key": "test-opencode-key",
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "OpenCode"})
    request.json = lambda: {
        "provider": "opencode",
        "type": "llm",
        "models": {
            "qwen3.7-plus": {"runtime_capabilities": {"temperature": 0.4, "top_p": 1.0}}
        },
    }

    response = _run(put_model_group(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["model_groups"]["OpenCode"]["models"]["qwen3.7-plus"] == {
        "runtime_capabilities": {"temperature": 0.4}
    }
    route, _provider = app.gateway_config.resolve("openai_responses", "qwen3.7-plus")
    assert route.resolved_model_profile is not None
    assert route.resolved_model_profile.runtime_capabilities == {
        "temperature": 0.4,
        "top_p": 1.0,
    }


def test_put_model_group_rejects_sampling_limits_for_other_providers(tmp_path):
    config = _config_data()
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(config)
    config_path.write_text(original, encoding="utf-8")
    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "OpenAI"})
    request.json = lambda: {
        "provider": "openai",
        "type": "llm",
        "models": {"gpt-5.6-terra": {"runtime_capabilities": {"temperature": 0.4}}},
    }

    response = _run(put_model_group(request))

    assert response.status_code == 400
    assert "unsupported fields" in response.body.decode("utf-8")
    assert config_path.read_text(encoding="utf-8") == original


def test_put_model_group_rejects_tool_profile_for_other_protocol(tmp_path):
    config = _config_data()
    config["providers"]["openai"]["api_type"] = "responses"
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(config)
    config_path.write_text(original, encoding="utf-8")
    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "OpenAI"})
    request.json = lambda: {
        "provider": "openai",
        "type": "llm",
        "tool_profile": "builtin",
        "models": {"gpt-grouped": {"upstream_model": "gpt-5.6-terra"}},
    }

    response = _run(put_model_group(request))

    assert response.status_code == 400
    assert "not provider api_type 'responses'" in json.loads(response.body)["error"]
    assert config_path.read_text(encoding="utf-8") == original


def test_put_model_group_persists_responses_passthrough_without_runtime_profile(
    tmp_path,
):
    config = _config_data()
    config["providers"]["openai"].update(
        {
            "api_type": "responses",
            "base_url": "https://api.openai.com/v1",
        }
    )
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "OpenAI"})
    request.json = lambda: {
        "provider": "openai",
        "type": "llm",
        "tool_profile": "passthrough",
        "models": {"gpt-grouped": {"upstream_model": "gpt-5.6-terra"}},
    }

    response = _run(put_model_group(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["model_groups"]["OpenAI"]["tool_profile"] == "passthrough"
    route, _provider = app.gateway_config.resolve("openai_responses", "gpt-grouped")
    assert route.tool_profile_name is None
    assert route.tool_profile == {}
    assert route.tool_profile_inputs == {}


@pytest.mark.parametrize("api_type", ["anthropic", "google"])
def test_put_model_group_persists_no_implicit_profile_for_anthropic_or_google(
    tmp_path, api_type
):
    config = _config_data()
    config["providers"]["openai"]["api_type"] = api_type
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "OpenAI"})
    request.json = lambda: {
        "provider": "openai",
        "type": "llm",
        "models": {"gpt-grouped": {"upstream_model": "gpt-5.6-terra"}},
    }

    response = _run(put_model_group(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert "tool_profile" not in saved["model_groups"]["OpenAI"]
    route, _provider = app.gateway_config.resolve("openai_responses", "gpt-grouped")
    assert route.tool_profile_name is None


def test_put_model_group_persists_model_info_without_runtime_modality_override(
    tmp_path,
):
    config = _config_data()
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    model_info = {
        "slug": "vision-alias",
        "display_name": "Vision Alias",
        "description": "Custom model metadata",
        "identity": "Vision Alias by Example",
        "priority": 10,
        "context_window": 262_144,
        "input_modalities": ["text", "image"],
        "supported_reasoning_levels": ["high"],
    }
    request = SimpleNamespace(app=app, path_params={"name": "Vision"})
    request.json = lambda: {
        "provider": "openai",
        "type": "llm",
        "tool_profile": "builtin",
        "models": {"vision-alias": {"model_info": model_info}},
    }

    response = _run(put_model_group(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    saved_info = saved["model_groups"]["Vision"]["models"]["vision-alias"]["model_info"]
    assert saved_info["slug"] == "vision-alias"
    assert saved_info["display_name"] == "Vision Alias"
    assert saved_info["context_window"] == 262_144
    route, _provider = app.gateway_config.resolve("openai_responses", "vision-alias")
    assert route.input_modalities == ["text", "image"]
    assert route.tool_profile


def test_put_model_group_rejects_embedding_type(tmp_path):
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(_config_data())
    config_path.write_text(original, encoding="utf-8")
    initial_config = GatewayConfig(_config_data())
    app = SimpleNamespace(config_path=str(config_path), gateway_config=initial_config)
    request = SimpleNamespace(app=app, path_params={"name": "Embeddings"})
    request.json = lambda: {
        "provider": "openai",
        "type": "embedding",
        "models": {"text-embedding": {}},
    }

    response = _run(put_model_group(request))

    assert response.status_code == 400
    assert json.loads(response.body) == {"error": "'type' must be 'llm'"}
    assert config_path.read_text(encoding="utf-8") == original


def test_local_mode_model_save_syncs_catalog_and_disable_clears_it(tmp_path):
    config = _config_data()
    config["server"].update({"local_mode": True, "local_mode_confirmed": True})
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        codex_home=str(codex_home),
        gateway_port=45678,
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "OpenAI"})
    request.json = lambda: {
        "provider": "openai",
        "type": "llm",
        "tool_profile": "builtin",
        "models": {"third-party-model": {"upstream_model": "gpt-5.6-terra"}},
    }

    response = _run(put_model_group(request))

    assert response.status_code == 200
    catalog = json.loads(
        (codex_home / "model_catalog.json").read_text(encoding="utf-8")
    )
    custom = next(
        model for model in catalog["models"] if model["slug"] == "third-party-model"
    )
    assert custom["display_name"] == "GPT-5.6-Terra"
    config_toml = (codex_home / "config.toml").read_text(encoding="utf-8")
    assert str(codex_home / "model_catalog.json") in config_toml
    assert 'model_provider = "codex_rosetta"' in config_toml
    assert 'base_url = "http://127.0.0.1:45678/v1"' in config_toml
    saved_after_sync = json.loads(config_path.read_text(encoding="utf-8"))
    codex_key = next(
        entry
        for entry in saved_after_sync["server"]["api_keys"]
        if entry["id"] == "codex"
    )
    assert f'experimental_bearer_token = "{codex_key["key"]}"' in config_toml

    delete_request = SimpleNamespace(app=app, path_params={"name": "OpenAI"})
    delete_response = _run(delete_model_group(delete_request))
    assert delete_response.status_code == 200
    catalog_after_delete = json.loads(
        (codex_home / "model_catalog.json").read_text(encoding="utf-8")
    )
    assert "third-party-model" not in {
        model["slug"] for model in catalog_after_delete["models"]
    }
    assert len(catalog_after_delete["models"]) == 8

    disable_request = SimpleNamespace(app=app)
    disable_request.json = lambda: {"local_mode": False}
    disable_response = _run(put_server_settings(disable_request))

    assert disable_response.status_code == 200
    assert not (codex_home / "model_catalog.json").exists()
    assert "model_catalog_json" not in (codex_home / "config.toml").read_text(
        encoding="utf-8"
    )
    assert "model_providers.codex_rosetta" not in (
        codex_home / "config.toml"
    ).read_text(encoding="utf-8")
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["server"]["local_mode"] is False


def test_put_codex_settings_syncs_task_models_to_catalog_and_memories(tmp_path):
    config = _config_data()
    config["server"].update({"local_mode": True, "local_mode_confirmed": True})
    config["model_groups"]["OpenAI"]["models"] = {
        "review-alias": {"upstream_model": "gpt-5.6-terra"},
        "consolidation-alias": {"upstream_model": "gpt-5.4"},
        "extract-alias": {"upstream_model": "gpt-5.4-mini"},
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    codex_home = tmp_path / "codex"
    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        codex_home=str(codex_home),
        gateway_port=45678,
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app)
    request.json = lambda: {
        "auto_review_model_override": "review-alias",
        "memories": {
            "consolidation_model": "consolidation-alias",
            "extract_model": "extract-alias",
        },
    }

    response = _run(put_codex_settings(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["codex"] == request.json()
    catalog = json.loads(
        (codex_home / "model_catalog.json").read_text(encoding="utf-8")
    )
    assert all(
        model["auto_review_model_override"] == "review-alias"
        for model in catalog["models"]
    )
    codex_config = tomllib.loads(
        (codex_home / "config.toml").read_text(encoding="utf-8")
    )
    assert codex_config["memories"]["consolidation_model"] == ("consolidation-alias")
    assert codex_config["memories"]["extract_model"] == "extract-alias"

    request.json = lambda: {
        "auto_review_model_override": None,
        "memories": {"consolidation_model": None, "extract_model": None},
    }
    clear_response = _run(put_codex_settings(request))

    assert clear_response.status_code == 200
    cleared = json.loads(config_path.read_text(encoding="utf-8"))
    assert "codex" not in cleared
    cleared_codex_config = tomllib.loads(
        (codex_home / "config.toml").read_text(encoding="utf-8")
    )
    assert cleared_codex_config.get("memories", {}) == {}


@pytest.mark.parametrize(
    ("local_mode", "confirmed"),
    [(False, True), (True, False)],
)
def test_put_codex_settings_requires_confirmed_local_mode(
    tmp_path, local_mode, confirmed
):
    config = _config_data()
    config["server"].update(
        {"local_mode": local_mode, "local_mode_confirmed": confirmed}
    )
    config_path = tmp_path / "config.jsonc"
    original = json.dumps(config)
    config_path.write_text(original, encoding="utf-8")
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=GatewayConfig(config),
    )
    request = SimpleNamespace(
        app=app,
        json=lambda: {"auto_review_model_override": "gpt-test"},
    )

    response = _run(put_codex_settings(request))

    assert response.status_code == 409
    assert config_path.read_text(encoding="utf-8") == original


def test_enabling_local_mode_through_admin_requires_explicit_confirmation(tmp_path):
    config = _config_data()
    config["server"].update({"local_mode": False, "local_mode_confirmed": False})
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    codex_home = tmp_path / "codex"
    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        codex_home=str(codex_home),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app)
    request.json = lambda: {"local_mode": True}

    rejected = _run(put_server_settings(request))

    assert rejected.status_code == 400
    assert (
        json.loads(config_path.read_text(encoding="utf-8"))["server"]["local_mode"]
        is False
    )

    request.json = lambda: {
        "local_mode": True,
        "local_mode_confirmed": True,
    }
    accepted = _run(put_server_settings(request))

    assert accepted.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["server"]["local_mode"] is True
    assert saved["server"]["local_mode_confirmed"] is True
    assert any(entry["id"] == "codex" for entry in saved["server"]["api_keys"])
    assert (codex_home / "model_catalog.json").is_file()


def test_local_mode_sync_failure_rolls_back_admin_config_and_codex_files(
    tmp_path, monkeypatch
):
    from codex_rosetta.gateway import local_mode

    config = _config_data()
    config["server"].update({"local_mode": True, "local_mode_confirmed": True})
    config_path = tmp_path / "config.jsonc"
    original_config = json.dumps(config)
    config_path.write_text(original_config, encoding="utf-8")
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    config_toml = codex_home / "config.toml"
    config_toml.write_text('model = "original"\n', encoding="utf-8")
    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        codex_home=str(codex_home),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "OpenAI"})
    request.json = lambda: {
        "provider": "openai",
        "type": "llm",
        "tool_profile": "builtin",
        "models": {"new-model": {"upstream_model": "gpt-5.6-terra"}},
    }
    real_atomic_write = local_mode._atomic_write_bytes
    failed = False

    def fail_once(path: str, content: bytes) -> None:
        nonlocal failed
        if path == str(config_toml) and not failed:
            failed = True
            raise OSError("simulated Codex config failure")
        real_atomic_write(path, content)

    monkeypatch.setattr(local_mode, "_atomic_write_bytes", fail_once)

    response = _run(put_model_group(request))

    assert response.status_code == 500
    assert json.loads(config_path.read_text(encoding="utf-8")) == config
    assert config_toml.read_text(encoding="utf-8") == 'model = "original"\n'
    assert not (codex_home / "model_catalog.json").exists()
    assert "new-model" not in app.gateway_config.models


def test_delete_model_group_removes_group_and_runtime_models(tmp_path):
    """Deleting a model group removes its expanded model routes."""
    config = _config_data()
    config["model_groups"] = {
        "OpenAI": {
            "provider": "openai",
            "type": "llm",
            "models": {"gpt-grouped": "gpt-5.6-terra"},
        }
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    initial_config = GatewayConfig(config)
    app = SimpleNamespace(
        config_path=str(config_path),
        gateway_config=initial_config,
        stream_trace_state=StreamTraceState(initial_config.stream_trace),
        auth_state=None,
    )
    request = SimpleNamespace(app=app, path_params={"name": "OpenAI"})

    response = _run(delete_model_group(request))

    assert response.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["model_groups"] == {}
    assert "gpt-grouped" not in app.gateway_config.models
