"""Focused tests for persisted special-provider refresh coordination."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from codex_rosetta.gateway.admin.provider_refresh import (
    ProviderRefreshCoordinator,
    _bucket_start,
    _new_api_points,
)
from codex_rosetta.gateway import app as gateway_app


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
    config: Any = SimpleNamespace(
        _all_raw_providers={"new": provider}, model_group_candidates={}
    )
    coordinator = ProviderRefreshCoordinator(SimpleNamespace(), config, None)
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def refresh(_name: str, *, deadline: float) -> bool:
        nonlocal calls
        assert deadline > 0
        calls += 1
        started.set()
        await release.wait()
        return True

    coordinator._refresh = refresh  # ty: ignore[invalid-assignment]
    first = asyncio.create_task(coordinator.refresh_provider("new"))
    await started.wait()
    second = asyncio.create_task(coordinator.refresh_provider("new"))
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(first, second) == [True, True]
    assert calls == 1


@pytest.mark.asyncio
async def test_cancelling_one_waiter_does_not_cancel_shared_refresh() -> None:
    provider = {"openai_variant": "new_api"}
    config: Any = SimpleNamespace(
        _all_raw_providers={"new": provider}, model_group_candidates={}
    )
    coordinator = ProviderRefreshCoordinator(SimpleNamespace(), config, None)
    started = asyncio.Event()
    release = asyncio.Event()

    async def refresh(_name: str, *, deadline: float) -> bool:
        assert deadline > 0
        started.set()
        await release.wait()
        return True

    coordinator._refresh = refresh  # ty: ignore[invalid-assignment]
    cancelled_waiter = asyncio.create_task(coordinator.refresh_provider("new"))
    await started.wait()
    surviving_waiter = asyncio.create_task(coordinator.refresh_provider("new"))
    cancelled_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_waiter
    release.set()
    assert await surviving_waiter is True


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
    config: Any = SimpleNamespace(
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
    assert cast(dict[str, Any], coordinator.snapshot_for("new", "u1"))["value"] == 88
    assert (
        cast(dict[str, Any], coordinator.snapshot_for("new", "u1"))["timestamp"] == 3660
    )

    provider["new_api_aggregation_bin"] = "5m"
    coordinator._snapshots["new"]["credentials"]["u1"]["value"] = 77
    assert not await coordinator._refresh_new_api("new", provider)
    assert cast(dict[str, Any], coordinator.snapshot_for("new", "u1"))["value"] == 77


@pytest.mark.asyncio
@pytest.mark.parametrize("bin_name,retries", [("1m", 5), ("5m", 7), ("1h", 10)])
async def test_new_api_retry_count_is_after_initial_attempt(
    bin_name: str, retries: int
) -> None:
    calls = 0
    provider = {
        "openai_variant": "new_api",
        "new_api_aggregation_bin": bin_name,
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

    class Transport:
        async def send_passthrough(self, _info, _url, _body, *, method="POST"):
            nonlocal calls
            calls += 1
            return SimpleNamespace(status_code=200, body={"data": {"groups": []}})

    config: Any = SimpleNamespace(
        _all_raw_providers={"new": provider}, model_group_candidates={}
    )
    coordinator = ProviderRefreshCoordinator(
        SimpleNamespace(transport=Transport()),
        config,
        None,
        clock=lambda: 3665.0,
        monotonic=lambda: 0.0,
        sleep=lambda _delay: asyncio.sleep(0),
    )
    assert not await coordinator._refresh_new_api("new", provider, deadline=10_000.0)
    assert calls == retries + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("bin_name,retries", [("1m", 5), ("5m", 7), ("1h", 10)])
async def test_new_api_can_succeed_on_final_retry(bin_name: str, retries: int) -> None:
    calls = 0
    interval = {"1m": 60, "5m": 300, "1h": 3600}[bin_name]
    target = _bucket_start(3665.0, interval)
    provider = {
        "openai_variant": "new_api",
        "new_api_aggregation_bin": bin_name,
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

    class Transport:
        async def send_passthrough(self, _info, _url, _body, *, method="POST"):
            nonlocal calls
            calls += 1
            series = (
                [{"ts": target, "success_rate": 91}] if calls == retries + 1 else []
            )
            return SimpleNamespace(
                status_code=200,
                body={"data": {"groups": [{"group": "cheap", "series": series}]}},
            )

    config: Any = SimpleNamespace(
        _all_raw_providers={"new": provider}, model_group_candidates={}
    )
    coordinator = ProviderRefreshCoordinator(
        SimpleNamespace(transport=Transport()),
        config,
        None,
        clock=lambda: 3665.0,
        monotonic=lambda: 0.0,
        sleep=lambda _delay: asyncio.sleep(0),
    )
    assert await coordinator._refresh_new_api("new", provider, deadline=10_000.0)
    assert calls == retries + 1


@pytest.mark.asyncio
async def test_scheduler_cancels_previous_round_at_next_monotonic_deadline() -> None:
    now = 0.0
    provider = {
        "openai_variant": "sub2api",
        "new_api_aggregation_bin": "30s",
    }
    candidate = SimpleNamespace(provider_name="sub")
    config: Any = SimpleNamespace(
        _all_raw_providers={"sub": provider},
        model_group_candidates={"group": (candidate,)},
    )
    first_started = asyncio.Event()
    first_cancelled = asyncio.Event()
    third_sleep = asyncio.Event()
    attempts = 0

    async def sleep(delay: float) -> None:
        nonlocal now
        if delay:
            now += delay
        if now >= 90:
            await third_sleep.wait()
        await asyncio.sleep(0)

    async def refresh(_name: str, *, deadline: float) -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            first_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                first_cancelled.set()
        await asyncio.Event().wait()
        return False

    coordinator = ProviderRefreshCoordinator(
        SimpleNamespace(),
        config,
        None,
        clock=lambda: now,
        monotonic=lambda: now,
        sleep=sleep,
    )
    coordinator._activity["group"] = 0.0
    coordinator._refresh = refresh  # ty: ignore[invalid-assignment]
    loop = asyncio.create_task(coordinator._provider_loop("sub"))
    await first_started.wait()
    await first_cancelled.wait()
    while attempts < 2:
        await asyncio.sleep(0)
    assert attempts == 2
    loop.cancel()
    await asyncio.gather(loop, return_exceptions=True)
    await coordinator.close()


@pytest.mark.asyncio
async def test_request_catches_up_a_refresh_skipped_for_inactivity() -> None:
    provider = {
        "openai_variant": "sub2api",
        "new_api_aggregation_bin": "5m",
    }
    candidate = SimpleNamespace(provider_name="sub")
    config: Any = SimpleNamespace(
        _all_raw_providers={"sub": provider},
        model_group_candidates={"group": (candidate,)},
    )
    block_scheduler = asyncio.Event()
    sleep_calls = 0

    async def sleep(_delay: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls > 1:
            await block_scheduler.wait()

    coordinator = ProviderRefreshCoordinator(
        SimpleNamespace(), config, None, sleep=sleep
    )
    refreshed = 0

    async def refresh(_name: str, *, deadline: float) -> bool:
        nonlocal refreshed
        refreshed += 1
        return True

    coordinator._refresh = refresh  # ty: ignore[invalid-assignment]
    loop = asyncio.create_task(coordinator._provider_loop("sub"))
    while "sub" not in coordinator._overdue:
        await asyncio.sleep(0)
    await coordinator.before_request("group")
    assert refreshed == 1
    loop.cancel()
    await asyncio.gather(loop, return_exceptions=True)


@pytest.mark.asyncio
async def test_sync_config_reconciles_scheduler_and_snapshots() -> None:
    old_provider = {
        "openai_variant": "new_api",
        "new_api_aggregation_bin": "1m",
        "availability_snapshot": {"updated_at": 1, "credentials": {}},
    }
    old_config: Any = SimpleNamespace(
        _all_raw_providers={"old": old_provider}, model_group_candidates={}
    )
    coordinator = ProviderRefreshCoordinator(SimpleNamespace(), old_config, None)
    blocker = asyncio.Event()

    async def provider_loop(_name: str) -> None:
        await blocker.wait()

    coordinator._provider_loop = provider_loop  # ty: ignore[invalid-assignment]
    await coordinator.start()
    old_task = coordinator._tasks["old"]
    new_snapshot = {"updated_at": 2, "credentials": {"u1": {"value": 9}}}
    new_config: Any = SimpleNamespace(
        _all_raw_providers={
            "old": {
                "openai_variant": "new_api",
                "new_api_aggregation_bin": "5m",
                "availability_snapshot": new_snapshot,
            },
            "added": {
                "openai_variant": "sub2api",
                "new_api_aggregation_bin": "5m",
            },
        },
        model_group_candidates={},
    )
    coordinator.sync_config(new_config)
    assert old_task.cancelled() or old_task.cancelling()
    assert set(coordinator._tasks) == {"old", "added"}
    assert coordinator.snapshots == {"old": new_snapshot}

    removed_config: Any = SimpleNamespace(
        _all_raw_providers={"added": new_config._all_raw_providers["added"]},
        model_group_candidates={},
    )
    coordinator.sync_config(removed_config)
    assert "old" not in coordinator._tasks
    assert "old" not in coordinator.snapshots
    await coordinator.close()


@pytest.mark.asyncio
async def test_persistence_failure_is_nonblocking_and_retains_old_snapshot(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_snapshot = {
        "updated_at": 1,
        "credentials": {"u1": {"value": 40, "timestamp": 0}},
    }
    provider = {
        "openai_variant": "new_api",
        "new_api_aggregation_bin": "1m",
        "availability_snapshot": old_snapshot,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"providers": {"new": provider}}))
    candidate = SimpleNamespace(provider_name="new")
    config: Any = SimpleNamespace(
        _all_raw_providers={"new": provider},
        model_group_candidates={"group": (candidate,)},
    )
    app = SimpleNamespace(gateway_config=config)
    coordinator = ProviderRefreshCoordinator(app, config, str(config_path))

    def fail_write(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(
        "codex_rosetta.gateway.admin.provider_refresh.write_config", fail_write
    )

    async def refresh(_name: str, *, deadline: float) -> bool:
        await coordinator._persist("new", {"u1": {"value": 99, "timestamp": 60}})
        return True

    coordinator._refresh = refresh  # ty: ignore[invalid-assignment]
    await coordinator.before_request("group")
    assert cast(dict[str, Any], coordinator.snapshot_for("new", "u1"))["value"] == 40


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler",
    [
        gateway_app.handle_codex_search,
        gateway_app.handle_image_generation,
        gateway_app.handle_image_edit,
    ],
)
async def test_auxiliary_ingress_awaits_refresh_before_resolution(
    handler, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    class Coordinator:
        async def before_request(self, group_name: str | None) -> None:
            events.append(f"refresh:{group_name}")

    async def auxiliary(_request, _config, _path):
        events.append("resolve")
        return "ok"

    monkeypatch.setattr(gateway_app, "_handle_codex_auxiliary", auxiliary)
    config = SimpleNamespace(model_group_names_by_model={"gpt-test": "group"})
    request = SimpleNamespace(
        app=SimpleNamespace(
            gateway_config=config,
            provider_refresh_coordinator=Coordinator(),
        ),
        json=lambda: {"model": "gpt-test"},
    )
    assert await handler(request) == "ok"
    assert events == ["refresh:group", "resolve"]
