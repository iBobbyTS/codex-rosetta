"""Strict request-log retention validation tests."""

from __future__ import annotations

from typing import Any

import pytest

from codex_rosetta.gateway.config import GatewayConfig
from codex_rosetta.observability.persistence import PersistenceManager
from codex_rosetta.observability.retention import MAX_REQUEST_LOG_RETENTION


@pytest.mark.parametrize("value", [True, "10", -1, MAX_REQUEST_LOG_RETENTION + 1])
@pytest.mark.parametrize("field", ["success_max", "error_max", "max_entries"])
def test_gateway_config_rejects_invalid_retention_caps(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    monkeypatch.delenv("REQUEST_LOG_SUCCESS_MAX", raising=False)
    monkeypatch.delenv("REQUEST_LOG_ERROR_MAX", raising=False)

    with pytest.raises(ValueError, match=field):
        GatewayConfig({"server": {"request_log": {field: value}}})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("REQUEST_LOG_SUCCESS_MAX", "invalid"),
        ("REQUEST_LOG_SUCCESS_MAX", "-1"),
        ("REQUEST_LOG_ERROR_MAX", str(MAX_REQUEST_LOG_RETENTION + 1)),
    ],
)
def test_gateway_config_rejects_invalid_retention_environment(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.delenv("REQUEST_LOG_SUCCESS_MAX", raising=False)
    monkeypatch.delenv("REQUEST_LOG_ERROR_MAX", raising=False)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        GatewayConfig({})


def test_gateway_config_rejects_non_object_request_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REQUEST_LOG_SUCCESS_MAX", raising=False)
    monkeypatch.delenv("REQUEST_LOG_ERROR_MAX", raising=False)
    with pytest.raises(ValueError, match="request_log must be an object"):
        GatewayConfig({"server": {"request_log": False}})


def test_gateway_config_resolves_env_explicit_legacy_zero_and_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUEST_LOG_SUCCESS_MAX", "0")
    monkeypatch.setenv("REQUEST_LOG_ERROR_MAX", str(MAX_REQUEST_LOG_RETENTION))
    config = GatewayConfig(
        {
            "server": {
                "admin_password": "test-admin-password",
                "api_keys": [{"id": "test", "key": "test-key", "label": "test"}],
                "request_log": {
                    "success_max": 10,
                    "error_max": 20,
                    "max_entries": 30,
                },
            }
        }
    )

    assert config.request_log_success_max == 0
    assert config.request_log_error_max == MAX_REQUEST_LOG_RETENTION

    monkeypatch.delenv("REQUEST_LOG_SUCCESS_MAX")
    monkeypatch.delenv("REQUEST_LOG_ERROR_MAX")
    legacy = GatewayConfig(
        {
            "server": {
                "admin_password": "test-admin-password",
                "api_keys": [{"id": "test", "key": "test-key", "label": "test"}],
                "request_log": {"max_entries": 7},
            }
        }
    )
    assert legacy.request_log_success_max == 7
    assert legacy.request_log_error_max == 10_000


@pytest.mark.parametrize("value", [False, "1", -1, MAX_REQUEST_LOG_RETENTION + 1])
def test_persistence_rejects_invalid_direct_caps(tmp_path: Any, value: Any) -> None:
    with pytest.raises(ValueError):
        PersistenceManager(str(tmp_path / "init"), success_max=value)

    manager = PersistenceManager(str(tmp_path / "update"))
    try:
        with pytest.raises(ValueError):
            manager.prepare_update((), success_max=0, error_max=value)
    finally:
        manager.close()
