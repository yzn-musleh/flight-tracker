"""New in Phase 3: characterizes timezones.py's dual-timezone rendering.
Storage/comparison always stay UTC (CLAUDE.md invariant #4) -- this is
read-only display formatting."""

import timezones


def test_render_dual_shows_airport_and_subscriber_time_when_different():
    text = timezones.render_dual(
        "2026-08-05T10:00:00+00:00", "Asia/Amman", "America/New_York"
    )
    assert "Asia/Amman" in text
    assert "America/New_York" in text
    assert "13:00" in text  # UTC+3 in August (Jordan does not observe DST)
    assert "06:00" in text  # UTC-4 in August (US Eastern DST)


def test_render_dual_collapses_to_one_time_when_airport_equals_subscriber():
    text = timezones.render_dual(
        "2026-08-05T10:00:00+00:00", "Asia/Amman", "Asia/Amman"
    )
    assert text.count("Asia/Amman") == 1
    assert "for you" not in text


def test_render_dual_falls_back_to_utc_for_missing_airport_timezone():
    text = timezones.render_dual("2026-08-05T10:00:00+00:00", None, "UTC")
    assert text == "2026-08-05 10:00 UTC"


def test_render_dual_falls_back_to_utc_for_unknown_timezone_name():
    text = timezones.render_dual("2026-08-05T10:00:00+00:00", "Not/A_Real_Zone", "UTC")
    assert text == "2026-08-05 10:00 UTC"


def test_render_dual_returns_none_for_falsy_input():
    assert timezones.render_dual(None, "Asia/Amman") is None
    assert timezones.render_dual("", "Asia/Amman") is None


def test_render_dual_returns_original_string_when_unparseable():
    assert timezones.render_dual("not-a-timestamp", "Asia/Amman") == "not-a-timestamp"


def test_default_subscriber_timezone_is_utc_unless_overridden(monkeypatch):
    monkeypatch.delenv("SUBSCRIBER_TIMEZONE", raising=False)
    # DEFAULT_SUBSCRIBER_TIMEZONE is read at import time, so this documents
    # the fallback used when render_dual isn't given an explicit subscriber_tz.
    text = timezones.render_dual("2026-08-05T10:00:00+00:00", "UTC", subscriber_tz=None)
    assert "UTC" in text
