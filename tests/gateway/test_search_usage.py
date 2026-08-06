from __future__ import annotations

import asyncio
from datetime import date

import pytest

from codex_rosetta.gateway import search_usage
from codex_rosetta.gateway.web_search import TavilyCredentialCollisionError
from codex_rosetta.gateway.search_usage import TavilyUsageState


@pytest.mark.asyncio
async def test_usage_reads_only_account_plan_and_calculates_next_month() -> None:
    state = TavilyUsageState(today=lambda: date(2026, 12, 31))

    async def fetch() -> dict[str, object]:
        return {
            "account": {
                "plan_usage": 156,
                "plan_limit": 1000,
                "paygo_usage": 99,
                "paygo_limit": 100,
            },
            "key": {"usage": 7, "limit": 10},
        }

    usage = await state.get("secret", fetcher=fetch)

    assert usage.status == "ok"
    assert (usage.used, usage.limit, usage.reset_date) == (156, 1000, "2027-01-01")
    assert usage.available_credits == 3
    assert not usage.proves_search_quota_recovery


@pytest.mark.asyncio
async def test_usage_recovery_requires_capacity_for_a_complete_request() -> None:
    now = 100.0
    state = TavilyUsageState(monotonic=lambda: now)

    async def fetch() -> dict[str, object]:
        return {"account": {"plan_usage": 992, "plan_limit": 1000}}

    usage = await state.get("secret", fetcher=fetch)

    assert usage.sample_started_at == 100.0
    assert usage.available_credits == 8
    assert usage.proves_search_quota_recovery


@pytest.mark.asyncio
async def test_usage_near_limit_does_not_prove_recovery() -> None:
    state = TavilyUsageState()

    async def fetch() -> dict[str, object]:
        return {"account": {"plan_usage": 999, "plan_limit": 1000}}

    usage = await state.get("secret", fetcher=fetch)

    assert usage.available_credits == 1
    assert not usage.proves_search_quota_recovery


@pytest.mark.asyncio
async def test_usage_missing_or_invalid_fields_is_unavailable() -> None:
    state = TavilyUsageState()

    async def fetch() -> dict[str, object]:
        return {"account": {"plan_usage": "156", "plan_limit": 1000}}

    usage = await state.get("secret", fetcher=fetch)

    assert usage.status == "unavailable"
    assert usage.used is usage.limit is usage.reset_date is None


@pytest.mark.parametrize(
    "payload",
    [
        {"account": {"plan_usage": float("nan"), "plan_limit": 1000}},
        {"account": {"plan_usage": float("inf"), "plan_limit": 1000}},
        {"account": {"plan_usage": 12.9, "plan_limit": 20.9}},
    ],
)
@pytest.mark.asyncio
async def test_usage_normalizes_finite_numbers_and_rejects_nonfinite(
    payload: dict[str, object],
) -> None:
    state = TavilyUsageState()

    async def fetch() -> dict[str, object]:
        return payload

    usage = await state.get("numeric-key", fetcher=fetch)

    if any(
        isinstance(value, float)
        and value != value
        or isinstance(value, float)
        and value == float("inf")
        for value in payload["account"].values()  # type: ignore[union-attr]
    ):
        assert usage.status == "unavailable"
    else:
        assert usage.status == "ok"
        assert (usage.used, usage.limit) == (12, 20)


@pytest.mark.asyncio
async def test_usage_propagates_safety_policy_failures() -> None:
    state = TavilyUsageState()

    async def fetch() -> dict[str, object]:
        raise TavilyCredentialCollisionError("credential collision")

    with pytest.raises(TavilyCredentialCollisionError):
        await state.get("collision-key", fetcher=fetch)


@pytest.mark.asyncio
async def test_usage_coalesces_concurrent_calls_and_caches_five_minutes() -> None:
    now = 100.0
    state = TavilyUsageState(monotonic=lambda: now)
    calls = 0

    async def fetch() -> dict[str, object]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {"account": {"plan_usage": 1, "plan_limit": 2}}

    first, second = await asyncio.gather(
        state.get("same-key", fetcher=fetch),
        state.get("same-key", fetcher=fetch),
    )
    third = await state.get("same-key", fetcher=fetch)

    assert first == second == third
    assert calls == 1


@pytest.mark.asyncio
async def test_cancelling_one_waiter_keeps_shared_fetch_alive() -> None:
    state = TavilyUsageState()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def fetch() -> dict[str, object]:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"account": {"plan_usage": 1, "plan_limit": 2}}

    cancelled_waiter = asyncio.create_task(state.get("same-key", fetcher=fetch))
    await started.wait()
    surviving_waiter = asyncio.create_task(state.get("same-key", fetcher=fetch))
    await asyncio.sleep(0)

    cancelled_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_waiter
    release.set()

    usage = await surviving_waiter
    cached = await state.get("same-key", fetcher=fetch)
    assert usage == cached
    assert usage.status == "ok"
    assert calls == 1


@pytest.mark.asyncio
async def test_usage_client_has_a_server_side_fetch_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, api_key: str, *, timeout: float) -> None:
            captured.update(api_key=api_key, timeout=timeout)

        async def usage(self) -> dict[str, object]:
            return {"account": {"plan_usage": 1, "plan_limit": 2}}

    monkeypatch.setattr(search_usage, "TavilyHTTPClient", FakeClient)

    usage = await TavilyUsageState().get("secret")

    assert usage.status == "ok"
    assert captured == {
        "api_key": "secret",
        "timeout": search_usage.TAVILY_USAGE_FETCH_TIMEOUT_SECONDS,
    }


@pytest.mark.asyncio
async def test_rotated_usage_cache_is_globally_swept_and_capacity_bounded() -> None:
    now = 100.0
    capacity = 4
    state = TavilyUsageState(
        ttl_seconds=10,
        state_capacity=capacity,
        monotonic=lambda: now,
    )
    calls = 0

    async def fetch() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"account": {"plan_usage": 1, "plan_limit": 2}}

    for index in range(capacity * 5):
        usage = await state.get(f"rotated-secret-{index}", fetcher=fetch)
        assert usage.status == "ok"

    assert calls == capacity * 5
    assert len(state._state_keys_locked()) == capacity
    assert len(state._cache) == capacity
    assert "rotated-secret" not in repr(state._state_keys_locked())

    now = 111.0
    await state.get("fresh-secret", fetcher=fetch)
    assert len(state._cache) == 1
    assert len(state._state_keys_locked()) == 1
    assert "fresh-secret" not in repr(state._state_keys_locked())


@pytest.mark.asyncio
async def test_usage_capacity_waits_without_evicting_active_fetches() -> None:
    state = TavilyUsageState(state_capacity=2)
    started: set[str] = set()
    release = {key: asyncio.Event() for key in ("first", "second", "third")}

    def fetch_for(key: str):
        async def fetch() -> dict[str, object]:
            started.add(key)
            await release[key].wait()
            return {"account": {"plan_usage": 1, "plan_limit": 2}}

        return fetch

    first = asyncio.create_task(state.get("first-secret", fetcher=fetch_for("first")))
    second = asyncio.create_task(
        state.get("second-secret", fetcher=fetch_for("second"))
    )
    while started != {"first", "second"}:
        await asyncio.sleep(0)

    third = asyncio.create_task(state.get("third-secret", fetcher=fetch_for("third")))
    await asyncio.sleep(0)
    assert started == {"first", "second"}
    assert len(state._inflight) == 2

    release["first"].set()
    assert (await first).status == "ok"
    while "third" not in started:
        await asyncio.sleep(0)
    assert len(state._inflight) == 2

    release["second"].set()
    release["third"].set()
    second_usage, third_usage = await asyncio.gather(second, third)
    assert second_usage.status == third_usage.status == "ok"
    assert len(state._state_keys_locked()) <= 2
    assert "secret" not in repr(state._state_keys_locked())


@pytest.mark.asyncio
async def test_usage_capacity_waiter_wakes_when_non_first_fetch_completes() -> None:
    started: set[str] = set()
    third_started = asyncio.Event()
    release = {key: asyncio.Event() for key in ("first", "second", "third")}

    def fetch_for(key: str):
        async def fetch() -> dict[str, object]:
            started.add(key)
            if key == "third":
                third_started.set()
            await release[key].wait()
            return {"account": {"plan_usage": 1, "plan_limit": 2}}
