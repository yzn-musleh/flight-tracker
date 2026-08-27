"""Decides when a tracked flight is worth spending an Aviationstack request on.

A flight only gets polled inside its "active window" — same day, or within
PRE_WINDOW_HOURS of its known scheduled departure — and even then only as
often as its tier interval dictates. This keeps monthly request usage low
since most of a flight's tracked lifetime (weeks/months before departure)
costs nothing at all.
"""

import os
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

TERMINAL_STATUSES = {"landed", "cancelled"}


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def mark_done(summary: Mapping[str, Any]) -> bool:
    """True once a flight has nothing left worth polling for."""
    if not summary:
        return False
    if (summary.get("status") or "").lower() in TERMINAL_STATUSES:
        return True
    if summary.get("arr_actual"):
        return True
    return False


def is_active_window(flight: dict, sched: dict, now: datetime) -> bool:
    if sched.get("done"):
        return False

    pre_window = timedelta(hours=_env_float("PRE_WINDOW_HOURS", 6))
    post_window = timedelta(hours=_env_float("POST_WINDOW_HOURS", 3))

    dep_scheduled = _parse_iso(sched.get("dep_scheduled"))
    if dep_scheduled is None:
        # No scheduled time known yet — fall back to "same calendar day".
        return now.date().isoformat() == flight.get("date")

    arr_scheduled = _parse_iso(sched.get("arr_scheduled"))
    window_start = dep_scheduled - pre_window
    # If we don't know the arrival time yet, keep the window open generously
    # (24h flight-time assumption) rather than closing it prematurely.
    window_end = (arr_scheduled or dep_scheduled + timedelta(hours=24)) + post_window
    return window_start <= now <= window_end


def tier_interval_minutes(flight: dict, sched: dict, now: datetime) -> int:
    """How often (minutes) to poll, given we're already inside the active window."""
    close_hours = _env_float("CLOSE_EVENT_HOURS", 3)
    close_interval = int(os.environ.get("CHECK_INTERVAL_MINUTES", "30"))
    far_interval = int(os.environ.get("FAR_TIER_MINUTES", "120"))

    dep_scheduled = _parse_iso(sched.get("dep_scheduled"))
    arr_scheduled = _parse_iso(sched.get("arr_scheduled"))

    events = [t for t in (dep_scheduled, arr_scheduled) if t is not None]
    if not events:
        # Same-day fallback with no timestamps yet — treat as urgent.
        return close_interval

    nearest_gap_hours = min(abs((t - now).total_seconds()) for t in events) / 3600
    return close_interval if nearest_gap_hours <= close_hours else far_interval


def is_due(flight: dict, sched: dict, now: datetime) -> bool:
    if not is_active_window(flight, sched, now):
        return False

    last_checked = _parse_iso(sched.get("last_checked"))
    if last_checked is None:
        return True

    interval = timedelta(minutes=tier_interval_minutes(flight, sched, now))
    return now - last_checked >= interval
