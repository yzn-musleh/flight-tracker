"""Renders stored UTC timestamps as human-readable local times.

Per CLAUDE.md invariant #4: "All timestamps are stored in UTC. Local times
are a rendering concern only." This module never stores or compares times --
it only formats an already-UTC ISO string for display, in both the relevant
airport's local timezone and the subscriber's configured timezone.

SUBSCRIBER_TIMEZONE (env var, default UTC) is a placeholder for a real
per-chat setting: Phase 4 introduces chat_id-scoped subscriptions and a
/timezone command, at which point this should become a per-chat value passed
in by the caller rather than one process-wide default. Everything here
already takes subscriber_tz as an explicit parameter for that reason -- only
the *default* is global for now.
"""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_SUBSCRIBER_TIMEZONE = os.environ.get("SUBSCRIBER_TIMEZONE", "UTC")


def _parse_utc(iso_str: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _format_in(dt: datetime, tz_name: str) -> tuple[str, str]:
    """Returns (formatted string, timezone name actually used) -- falls back
    to UTC if tz_name is unknown, and says so via the returned name."""
    try:
        local = dt.astimezone(ZoneInfo(tz_name))
        used = tz_name
    except (ZoneInfoNotFoundError, ValueError):
        local = dt.astimezone(timezone.utc)
        used = "UTC"
    return local.strftime("%Y-%m-%d %H:%M"), used


def render_dual(
    iso_str: str | None,
    airport_tz: str | None,
    subscriber_tz: str | None = None,
) -> str | None:
    """Render a stored UTC timestamp in the airport's local timezone and the
    subscriber's configured timezone. Falls back to UTC for whichever side
    doesn't have a known timezone. Returns None if iso_str is falsy, and the
    original string unchanged if it can't be parsed as a timestamp at all."""
    if not iso_str:
        return None
    dt = _parse_utc(iso_str)
    if dt is None:
        return iso_str

    subscriber_tz = subscriber_tz or DEFAULT_SUBSCRIBER_TIMEZONE
    airport_text, airport_used = _format_in(dt, airport_tz or "UTC")
    subscriber_text, subscriber_used = _format_in(dt, subscriber_tz)

    if airport_used == subscriber_used:
        return f"{airport_text} {airport_used}"
    return (
        f"{airport_text} {airport_used} ({subscriber_text} {subscriber_used} for you)"
    )
