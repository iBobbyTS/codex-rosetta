"""Focused tests for Admin automatic model-group switch delivery."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from codex_rosetta.gateway.admin.events import (
    AutomaticSwitchEventStore,
    get_model_group_switch_events,
)
from codex_rosetta.gateway.config import GatewayConfig


def _config() -> GatewayConfig:
    return GatewayConfig(
        {
            "providers": {
                "old": {
                    "provider": "openai",
                    "api_type": "responses",
                    "request_encoding": "passthrough",
                    "base_urls": ["https://old.example/v1"],
                    "api_keys": [
                        {
                            "uuid": "00000000-0000-4000-8000-000000000001",
                            "id": "old",
                            "key": "sk-old",
                            "rate_multiplier": 0.4,
                        }
                    ],
                    "auto_rotate_credentials": False,
                },
                "new": {
                    "provider": "openai",
                    "api_type": "responses",
                    "request_encoding": "passthrough",
                    "base_urls": ["https://new.example/v1"],
                    "api_keys": [
                        {
                            "uuid": "00000000-0000-4000-8000-000000000002",
                            "id": "new",
                            "key": "sk-new",
                            "rate_multiplier": 0.2,
                        }
                    ],
                    "auto_rotate_credentials": False,
                },
            },
            "model_groups": {
                "fast": {
                    "provider": [
                        {
                            "provider": "old",
                            "credential_uuid": "00000000-0000-4000-8000-000000000001",
                        },
                        {
                            "provider": "new",
                            "credential_uuid": "00000000-0000-4000-8000-000000000002",
                        },
                    ],
                    "type": "llm",
                    "models": {"gpt-5.6-terra": {}},
                }
            },
            "server": {"admin_password": "test", "api_keys": [{"id": "client", "key": "client-key"}]},
        }
    )


def test_automatic_switch_store_exposes_only_events_after_cursor() -> None:
    config = _config()
    ring = config.model_group_rings["fast"]
    store = AutomaticSwitchEventStore(config)
    ring.bind_automatic_switch_recorder(store.record)

    asyncio.run(ring.select_automatically(ring.candidates[1]))

    request = SimpleNamespace(
        app=SimpleNamespace(automatic_switch_events=store),
        query_params={"cursor": ["0"]},
    )
    response = asyncio.run(get_model_group_switch_events(request))
    payload = json.loads(response.body)
    assert payload["cursor"] == 1
    assert payload["events"] == [
        {
            "id": 1,
            "group": "fast",
            "old_candidate": {
                "provider": "old",
                "credential_id": "old",
            },
            "new_candidate": {
                "provider": "new",
                "credential_id": "new",
            },
            "old_rate": 0.4,
            "new_rate": 0.2,
        }
    ]
    request.query_params = {"cursor": ["1"]}
    assert json.loads(asyncio.run(get_model_group_switch_events(request)).body)["events"] == []


def test_initial_cursor_does_not_replay_existing_switches() -> None:
    config = _config()
    ring = config.model_group_rings["fast"]
    store = AutomaticSwitchEventStore(config)
    ring.bind_automatic_switch_recorder(store.record)
    asyncio.run(ring.select_automatically(ring.candidates[1]))
    request = SimpleNamespace(
        app=SimpleNamespace(automatic_switch_events=store), query_params={}
    )
    assert json.loads(asyncio.run(get_model_group_switch_events(request)).body) == {
        "cursor": 1,
        "events": [],
    }
