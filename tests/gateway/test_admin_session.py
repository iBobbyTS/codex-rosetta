"""Durable Admin browser-session secret tests."""

from __future__ import annotations

import json
import os
import stat
from typing import Any, cast

import pytest

from codex_rosetta.gateway.admin_session import (
    ADMIN_SESSION_SECRET_FILENAME,
    AdminSessionSecretError,
    load_or_create_admin_session_secret,
)
from codex_rosetta.gateway.app import create_app
from codex_rosetta.gateway.auth import AuthState
from codex_rosetta.gateway.config import GatewayConfig


def _admin_token(
    *, internal_token: str, session_secret: bytes, password: str = "admin-password"
) -> str | None:
    return AuthState(
        {},
        {},
        internal_token,
        admin_password=password,
        admin_session_secret=session_secret,
    ).admin_token


def _gateway_config() -> dict[str, Any]:
    return {
        "providers": {
            "test-provider": {
                "api_key": "sk-test",
                "base_url": "https://api.example.test/v1",
                "api_type": "chat",
            }
        },
        "model_groups": {
            "test": {
                "provider": "test-provider",
                "type": "llm",
                "models": {"gpt-test": {}},
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


def _close_app_persistence(app: Any) -> None:
    persistence = getattr(app, "persistence", None)
    if persistence is not None:
        persistence.close()


def test_persisted_secret_keeps_admin_login_across_process_tokens(tmp_path) -> None:
    config_path = tmp_path / "config.jsonc"
    config_path.write_text("{}\n", encoding="utf-8")

    first_secret = load_or_create_admin_session_secret(str(config_path))
    second_secret = load_or_create_admin_session_secret(str(config_path))

    assert first_secret == second_secret
    assert len(first_secret) == 32
    assert _admin_token(
        internal_token="rsk-internal-first", session_secret=first_secret
    ) == _admin_token(
        internal_token="rsk-internal-second", session_secret=second_secret
    )
    key_path = tmp_path / ADMIN_SESSION_SECRET_FILENAME
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_create_app_reuses_admin_login_after_gateway_restart(tmp_path) -> None:
    raw_config = _gateway_config()
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(raw_config), encoding="utf-8")

    first_app = cast(
        Any,
        create_app(GatewayConfig(raw_config), config_path=str(config_path)),
    )
    first_admin_token = first_app.auth_state.admin_token
    first_internal_token = first_app.internal_token
    _close_app_persistence(first_app)

    second_app = cast(
        Any,
        create_app(GatewayConfig(raw_config), config_path=str(config_path)),
    )
    try:
        assert second_app.auth_state.admin_token == first_admin_token
        assert second_app.internal_token != first_internal_token
    finally:
        _close_app_persistence(second_app)


def test_changing_admin_password_invalidates_existing_token(tmp_path) -> None:
    config_path = tmp_path / "config.jsonc"
    config_path.write_text("{}\n", encoding="utf-8")
    secret = load_or_create_admin_session_secret(str(config_path))

    assert _admin_token(
        internal_token="rsk-internal", session_secret=secret, password="first"
    ) != _admin_token(
        internal_token="rsk-internal", session_secret=secret, password="second"
    )


def test_existing_secret_permissions_are_tightened(tmp_path) -> None:
    config_path = tmp_path / "config.jsonc"
    config_path.write_text("{}\n", encoding="utf-8")
    load_or_create_admin_session_secret(str(config_path))
    key_path = tmp_path / ADMIN_SESSION_SECRET_FILENAME
    os.chmod(key_path, 0o644)

    load_or_create_admin_session_secret(str(config_path))

    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_malformed_secret_fails_closed_without_rotation(tmp_path) -> None:
    config_path = tmp_path / "config.jsonc"
    config_path.write_text("{}\n", encoding="utf-8")
    key_path = tmp_path / ADMIN_SESSION_SECRET_FILENAME
    key_path.write_text("not-a-valid-secret\n", encoding="ascii")

    with pytest.raises(AdminSessionSecretError, match="unknown format"):
        load_or_create_admin_session_secret(str(config_path))

    assert key_path.read_text(encoding="ascii") == "not-a-valid-secret\n"


def test_secret_symlink_is_rejected(tmp_path) -> None:
    config_path = tmp_path / "config.jsonc"
    config_path.write_text("{}\n", encoding="utf-8")
    target = tmp_path / "target.key"
    target.write_text("v1:untrusted\n", encoding="ascii")
    (tmp_path / ADMIN_SESSION_SECRET_FILENAME).symlink_to(target)

    with pytest.raises(AdminSessionSecretError, match="Cannot open"):
        load_or_create_admin_session_secret(str(config_path))


def test_missing_config_path_uses_ephemeral_secret_without_writing() -> None:
    first = load_or_create_admin_session_secret(None)
    second = load_or_create_admin_session_secret(None)

    assert len(first) == 32
    assert len(second) == 32
    assert first != second
