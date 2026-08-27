"""New in Phase 5: characterizes the persisted next_poll_at scheduling
model that replaced recomputing the tier interval from last_checked on
every call -- including the "restart resumes exactly where it left off"
scenario HARDENING_PLAN.md names this phase for. See FINDINGS.md #7 for
why this supersedes part of test_scheduler.py/test_storage.py rather than
editing them.
"""

from datetime import datetime

import storage
from scheduler import compute_next_poll_at, is_due


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def test_never_scheduled_is_always_due():
    flight = {"date": "2026-08-05"}
    assert is_due(flight, {}, _dt("2026-08-05T12:00:00+00:00")) is True


def test_not_due_before_next_poll_at():
    flight = {"date": "2026-08-05"}
    sched = {
        "dep_scheduled": "2026-08-05T10:00:00+00:00",
        "next_poll_at": "2026-08-05T07:00:00+00:00",
    }
    assert is_due(flight, sched, _dt("2026-08-05T06:59:00+00:00")) is False
    assert is_due(flight, sched, _dt("2026-08-05T07:00:00+00:00")) is True


def test_compute_next_poll_at_uses_the_tier_interval_at_computation_time(monkeypatch):
    monkeypatch.setenv("FAR_TIER_MINUTES", "120")
    monkeypatch.setenv("CLOSE_EVENT_HOURS", "3")
    flight = {"date": "2026-08-05"}
    sched = {"dep_scheduled": "2026-08-05T10:00:00+00:00"}  # far tier at 05:00
    now = _dt("2026-08-05T05:00:00+00:00")

    next_poll_at = compute_next_poll_at(flight, sched, now)

    assert next_poll_at == "2026-08-05T07:00:00+00:00"


def test_next_poll_at_is_fixed_even_if_tier_would_later_change(monkeypatch):
    """The core difference from the old recompute-on-every-call design: once
    computed, next_poll_at doesn't silently shift just because a later call
    happens to compute a different tier for the same interval."""
    monkeypatch.setenv("FAR_TIER_MINUTES", "120")
    monkeypatch.setenv("CHECK_INTERVAL_MINUTES", "30")
    monkeypatch.setenv("CLOSE_EVENT_HOURS", "3")
    flight = {"date": "2026-08-05"}
    sched = {
        "dep_scheduled": "2026-08-05T10:00:00+00:00",
        "next_poll_at": "2026-08-05T07:00:00+00:00",  # computed at far tier, 05:00
    }
    # At 06:50 the flight has entered the close tier (within 3h of departure),
    # but next_poll_at was already fixed at 07:00 and must not move earlier.
    assert is_due(flight, sched, _dt("2026-08-05T06:50:00+00:00")) is False
    assert is_due(flight, sched, _dt("2026-08-05T07:00:00+00:00")) is True


def test_restart_resumes_from_persisted_next_poll_at_not_lost_or_reset():
    """The scenario the phase is named for: storage.update_flight_schedule
    persists next_poll_at; a brand new read (simulating a fresh process
    after a restart) sees exactly the same due-time, not a recomputed or
    reset one."""
    storage.update_flight_schedule(
        "RJ264",
        "2026-08-05",
        last_checked="2026-08-05T05:00:00+00:00",
        next_poll_at="2026-08-05T07:00:00+00:00",
    )

    # "Restart": a fresh read of the same row.
    sched_after_restart = storage.get_flight_schedule("RJ264", "2026-08-05")

    assert sched_after_restart["next_poll_at"] == "2026-08-05T07:00:00+00:00"
    assert (
        is_due(
            {"date": "2026-08-05"},
            sched_after_restart,
            _dt("2026-08-05T06:59:00+00:00"),
        )
        is False
    )
    assert (
        is_due(
            {"date": "2026-08-05"},
            sched_after_restart,
            _dt("2026-08-05T07:00:00+00:00"),
        )
        is True
    )


def test_get_flight_schedule_includes_next_poll_at_key():
    entry = storage.get_flight_schedule("RJ264")
    assert "next_poll_at" in entry
    assert entry["next_poll_at"] is None
