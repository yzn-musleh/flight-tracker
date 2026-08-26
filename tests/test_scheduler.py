"""Characterizes scheduler.py's polling-window and tiering decisions."""

from datetime import datetime

import pytest

import scheduler


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


@pytest.mark.parametrize(
    "summary,expected",
    [
        (None, False),
        ({}, False),
        ({"status": "scheduled"}, False),
        ({"status": "active"}, False),
        ({"status": "landed"}, True),
        ({"status": "LANDED"}, True),
        ({"status": "cancelled"}, True),
        ({"status": "active", "arr_actual": "2026-08-05T14:10:00+00:00"}, True),
    ],
)
def test_mark_done(summary, expected):
    assert scheduler.mark_done(summary) is expected


def test_active_window_same_day_fallback_when_no_scheduled_time_known():
    flight = {"date": "2026-08-05"}
    sched = {}
    assert (
        scheduler.is_active_window(flight, sched, _dt("2026-08-05T00:00:00+00:00"))
        is True
    )
    assert (
        scheduler.is_active_window(flight, sched, _dt("2026-08-05T23:59:00+00:00"))
        is True
    )
    assert (
        scheduler.is_active_window(flight, sched, _dt("2026-08-06T00:01:00+00:00"))
        is False
    )
    assert (
        scheduler.is_active_window(flight, sched, _dt("2026-08-04T23:59:00+00:00"))
        is False
    )


def test_active_window_respects_pre_and_post_window_around_scheduled_times(monkeypatch):
    monkeypatch.setenv("PRE_WINDOW_HOURS", "6")
    monkeypatch.setenv("POST_WINDOW_HOURS", "3")
    flight = {"date": "2026-08-05"}
    sched = {
        "dep_scheduled": "2026-08-05T10:00:00+00:00",
        "arr_scheduled": "2026-08-05T14:00:00+00:00",
    }
    # window is [10:00 - 6h, 14:00 + 3h] = [04:00, 17:00]
    assert (
        scheduler.is_active_window(flight, sched, _dt("2026-08-05T03:59:00+00:00"))
        is False
    )
    assert (
        scheduler.is_active_window(flight, sched, _dt("2026-08-05T04:00:00+00:00"))
        is True
    )
    assert (
        scheduler.is_active_window(flight, sched, _dt("2026-08-05T17:00:00+00:00"))
        is True
    )
    assert (
        scheduler.is_active_window(flight, sched, _dt("2026-08-05T17:01:00+00:00"))
        is False
    )


def test_active_window_assumes_24h_flight_when_arrival_unknown(monkeypatch):
    monkeypatch.setenv("PRE_WINDOW_HOURS", "6")
    monkeypatch.setenv("POST_WINDOW_HOURS", "3")
    flight = {"date": "2026-08-05"}
    sched = {"dep_scheduled": "2026-08-05T10:00:00+00:00"}
    # window end = dep + 24h + 3h post = 2026-08-06T13:00:00
    assert (
        scheduler.is_active_window(flight, sched, _dt("2026-08-06T12:59:00+00:00"))
        is True
    )
    assert (
        scheduler.is_active_window(flight, sched, _dt("2026-08-06T13:01:00+00:00"))
        is False
    )


def test_active_window_false_once_marked_done():
    flight = {"date": "2026-08-05"}
    sched = {"done": True, "dep_scheduled": "2026-08-05T10:00:00+00:00"}
    assert (
        scheduler.is_active_window(flight, sched, _dt("2026-08-05T10:00:00+00:00"))
        is False
    )


def test_tier_interval_urgent_when_no_scheduled_times_known(monkeypatch):
    monkeypatch.setenv("CHECK_INTERVAL_MINUTES", "30")
    flight = {"date": "2026-08-05"}
    assert (
        scheduler.tier_interval_minutes(flight, {}, _dt("2026-08-05T12:00:00+00:00"))
        == 30
    )


def test_tier_interval_close_vs_far(monkeypatch):
    monkeypatch.setenv("CLOSE_EVENT_HOURS", "3")
    monkeypatch.setenv("CHECK_INTERVAL_MINUTES", "30")
    monkeypatch.setenv("FAR_TIER_MINUTES", "120")
    flight = {"date": "2026-08-05"}
    sched = {"dep_scheduled": "2026-08-05T10:00:00+00:00"}

    far = scheduler.tier_interval_minutes(
        flight, sched, _dt("2026-08-05T05:00:00+00:00")
    )
    close = scheduler.tier_interval_minutes(
        flight, sched, _dt("2026-08-05T08:00:00+00:00")
    )
    assert far == 120
    assert close == 30


def test_is_due_true_on_first_ever_check():
    flight = {"date": "2026-08-05"}
    sched = {}
    assert scheduler.is_due(flight, sched, _dt("2026-08-05T12:00:00+00:00")) is True


def test_is_due_false_outside_active_window():
    flight = {"date": "2026-08-05"}
    sched = {}
    assert scheduler.is_due(flight, sched, _dt("2026-09-01T12:00:00+00:00")) is False


def test_is_due_respects_tier_interval_since_last_check(monkeypatch):
    monkeypatch.setenv("CHECK_INTERVAL_MINUTES", "30")
    monkeypatch.setenv("FAR_TIER_MINUTES", "120")
    monkeypatch.setenv("CLOSE_EVENT_HOURS", "3")
    flight = {"date": "2026-08-05"}
    sched = {
        "dep_scheduled": "2026-08-05T10:00:00+00:00",
        "last_checked": "2026-08-05T05:00:00+00:00",
    }
    # far tier (120 min) at 05:00, next due at 07:00
    assert scheduler.is_due(flight, sched, _dt("2026-08-05T06:59:00+00:00")) is False
    assert scheduler.is_due(flight, sched, _dt("2026-08-05T07:00:00+00:00")) is True
