"""Tests for the shared ordered failover coordinator."""

from codex_rosetta.gateway._ordered_failover import OrderedFailoverCoordinator


def test_cooldown_detail_follows_deadline_prune_and_clear_lifecycle() -> None:
    now = 100.0
    coordinator = OrderedFailoverCoordinator(
        ("first", "second"),
        "first",
        cooldown_seconds=10,
        clock=lambda: now,
    )

    coordinator.mark_failed("second", "first failure")

    assert coordinator.status_snapshot() == (
        ("first", "available"),
        ("second", "cooling"),
    )
    assert coordinator.cooldown_detail("second") == ("first failure", 10.0)

    now = 104.0
    coordinator.mark_failed("second", "latest failure")
    assert coordinator.cooldown_detail("second") == ("latest failure", 10.0)

    coordinator.clear_cooldown("second")
    assert coordinator.cooldown_detail("second") is None
    assert coordinator.status_snapshot()[1] == ("second", "available")

    coordinator.mark_failed("second", "expired failure")
    now = 115.0
    assert coordinator.status_snapshot()[1] == ("second", "available")
    assert coordinator.cooldown_detail("second") is None


def test_fresh_evidence_clears_only_strictly_older_cooldown() -> None:
    now = 100.0
    coordinator = OrderedFailoverCoordinator(
        ("first", "second"),
        "first",
        cooldown_seconds=10,
        clock=lambda: now,
    )

    coordinator.mark_failed("second", "failure")

    assert coordinator.clear_cooldown_started_before("second", 100.0) is False
    assert coordinator.clear_cooldown_started_before("second", 99.0) is False
    assert coordinator.status_snapshot()[1] == ("second", "cooling")

    assert coordinator.clear_cooldown_started_before("second", 100.1) is True
    assert coordinator.status_snapshot()[1] == ("second", "available")
    assert coordinator.clear_cooldown_started_before("second", 100.1) is False
