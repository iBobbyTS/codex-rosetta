"""Focused tests for persisted special-provider refresh coordination."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from codex_rosetta.gateway.admin.provider_refresh import (
    ProviderRefreshCoordinator,
    _bucket_start,
    _new_api_points,
)


def test_new_api_points_are_grouped_by_unix_timestamp() -> None:
    payload = {
        "data": {
            "groups": [
                {
                    "group": "cheap",
                    "series": [
                        {"ts": 600, "success_rate": 91},
                        {"ts": 660, "success_rate": 93.5},
                    ],
                }
            ]
        }
    }
    assert _new_api_points(payload, "cheap") == [(600, 91.0), (660, 93.5)]
    assert _new_api_points(payload, "missing") == []


def test_bucket_alignment_is_utc_unix_based() -> None:
    assert _bucket_start(3661.9, 60) == 3660
    assert _bucket_start(3661.9, 300) == 3600


@pytest.mark.asyncio
async def test_concurrent_provider_refreshes_share_one_task() -> None:
    provider = {"openai_variant": "new_api"}
    config = SimpleNamespace(
        _all_raw_providers={"new": provider}, model_group_candidates={}
    )
    coordinator = ProviderRefreshCoordinator(SimpleNamespace(), config, None)
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def refresh(_name: str) -> bool:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return True

    coordinator._refresh = refresh  # type: ignore[method-assign]
    first = asyncio.create_task(coordinator.refresh_provider("new"))
    await started.wait()
    second = asyncio.create_task(coordinator.refresh_provider("new"))
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(first, second) == [True, True]
    assert calls == 1


@pytest.mark.asyncio
async def test_new_api_refresh_accepts_late_target_bucket_and_retains_stale_on_miss() -> (
    None
):
    now = 3665.0
    provider = {
        "openai_variant": "new_api",
        "new_api_aggregation_bin": "1m",
        "current_base_url": "https://new.example",
        "api_keys": [
            {
                "uuid": "u1",
                "id": "cred",
                "key": "sk-test",
                "new_api_group": "cheap",
                "new_api_model": "gpt-test",
            }
        ],
    }
    config = SimpleNamespace(
        _all_raw_providers={"new": provider}, model_group_candidates={}
    )

    class Transport:
        async def send_passthrough(self, _info, _url, _body, *, method="POST"):
            return SimpleNamespace(
                status_code=200,
                body={
                    "data": {
                        "groups": [
                            {
                                "group": "cheap",
                                "series": [{"ts": 3660, "success_rate": 88}],
                            }
                        ]
                    }
                },
            )

    coordinator = ProviderRefreshCoordinator(
        SimpleNamespace(transport=Transport()),
        config,
        None,
        clock=lambda: now,
        sleep=lambda _delay: asyncio.sleep(0),
    )
    assert await coordinator._refresh_new_api("new", provider)
    assert coordinator.snapshot_for("new", "u1")["value"] == 88
    assert coordinator.snapshot_for("new", "u1")["timestamp"] == 3660

    provider["new_api_aggregation_bin"] = "5m"
    coordinator._snapshots["new"]["credentials"]["u1"]["value"] = 77
    assert not await coordinator._refresh_new_api("new", provider)
    assert coordinator.snapshot_for("new", "u1")["value"] == 77
