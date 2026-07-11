"""Tests for Admin gateway access-key management invariants."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from codex_rosetta.gateway.admin.routes import _shared
from codex_rosetta.gateway.admin.routes.keys import (
    create_api_key,
    delete_api_key,
    update_api_key,
)
from codex_rosetta.gateway.config import GatewayConfig


def _config() -> dict:
    return {
        "providers": {},
        "models": {},
        "server": {
            "admin_password": "test-admin-password",
            "api_keys": [
                {
                    "id": "only-client",
                    "label": "Only client",
                    "key": "test-gateway-key",
                }
            ],
        },
    }


def _create_request(config_path, key: object, *, label: object = "New client"):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    request = SimpleNamespace(
        app=SimpleNamespace(
            config_path=str(config_path),
            gateway_config=GatewayConfig(config),
        )
    )
    request.json = lambda: {"label": label, "key": key}
    return request


def test_delete_last_access_key_is_rejected_without_modifying_config(tmp_path):
    config_path = tmp_path / "config.jsonc"
    config = _config()
    config_path.write_text(json.dumps(config), encoding="utf-8")
    request = SimpleNamespace(
        app=SimpleNamespace(config_path=str(config_path)),
        path_params={"key_id": "only-client"},
    )

    response = asyncio.run(delete_api_key(request))

    assert response.status_code == 409
    assert json.loads(response.body.decode("utf-8")) == {
        "error": "Cannot delete the last gateway access key"
    }
    assert json.loads(config_path.read_text(encoding="utf-8")) == config


@pytest.mark.parametrize(
    ("key", "expected_status"),
    [
        ("test-gateway-key", 409),
        (["not", "a", "string"], 400),
        ("${MISSING_GATEWAY_KEY}", 400),
    ],
)
def test_create_key_rejects_invalid_candidate_without_modifying_config(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    key: object,
    expected_status: int,
):
    monkeypatch.delenv("MISSING_GATEWAY_KEY", raising=False)
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    original = config_path.read_bytes()

    response = asyncio.run(create_api_key(_create_request(config_path, key)))

    assert response.status_code == expected_status
    assert config_path.read_bytes() == original


def test_create_key_activation_failure_rolls_back_exact_file(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = tmp_path / "config.jsonc"
    original = b'{\n  "providers": {},\n  "models": {},\n  "server": {\n    "admin_password": "test-admin-password",\n    "api_keys": [{"id": "only-client", "label": "Only client", "key": "test-gateway-key"}]\n  }\n}\n'
    config_path.write_bytes(original)

    def _fail_activation(*args, **kwargs):
        raise RuntimeError("simulated activation failure")

    monkeypatch.setattr(_shared, "_activate_gateway_config", _fail_activation)

    response = asyncio.run(
        create_api_key(_create_request(config_path, "new-gateway-key"))
    )

    assert response.status_code == 500
    assert "simulated activation failure" in response.body.decode("utf-8")
    assert config_path.read_bytes() == original


@pytest.mark.parametrize("label", [{"nested": True}, ["label"], "x" * 129])
def test_create_key_rejects_invalid_label_without_modifying_config(tmp_path, label):
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    original = config_path.read_bytes()

    response = asyncio.run(
        create_api_key(_create_request(config_path, "new-gateway-key", label=label))
    )

    assert response.status_code == 400
    assert "label" in response.body.decode("utf-8")
    assert config_path.read_bytes() == original


@pytest.mark.parametrize("label", [{"nested": True}, ["label"], "x" * 129])
def test_update_key_rejects_invalid_label_without_modifying_config(tmp_path, label):
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    original = config_path.read_bytes()
    request = _create_request(config_path, "unused", label=label)
    request.path_params = {"key_id": "only-client"}
    request.json = lambda: {"label": label}

    response = asyncio.run(update_api_key(request))

    assert response.status_code == 400
    assert "label" in response.body.decode("utf-8")
    assert config_path.read_bytes() == original
