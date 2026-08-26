"""New in Phase 3: characterizes flight_api.format_message()'s dual-timezone
rendering of estimated times (CLAUDE.md invariant #4: stored UTC, rendered
in the airport's local timezone and the subscriber's). format_message()'s
other behavior (delay/gate lines, missing fields) is still covered,
unmodified, by Phase 0's frozen tests/test_flight_api.py."""

import flight_api


def test_format_message_renders_estimated_departure_in_airport_local_time():
    summary = {
        "airline": "Royal Jordanian",
        "status": "active",
        "dep_airport": "Queen Alia International",
        "dep_iata": "AMM",
        "dep_estimated": "2026-08-05T10:05:00+00:00",
        "arr_airport": "JFK",
        "arr_iata": "JFK",
    }
    text = flight_api.format_message("Mom", "RJ264", summary)
    assert "Asia/Amman" in text
    assert "13:05" in text  # UTC+3 in August


def test_format_message_renders_estimated_arrival_in_its_own_airport_timezone():
    summary = {
        "dep_airport": "AMM",
        "arr_airport": "JFK",
        "arr_iata": "JFK",
        "arr_estimated": "2026-08-05T22:10:00+00:00",
    }
    text = flight_api.format_message("Mom", "RJ264", summary)
    assert "America/New_York" in text
    assert "18:10" in text  # UTC-4 (Eastern DST) in August


def test_format_message_falls_back_to_utc_when_airport_unknown():
    summary = {
        "dep_airport": "Somewhere",
        "dep_iata": "ZZZ99",
        "dep_estimated": "2026-08-05T10:05:00+00:00",
        "arr_airport": None,
    }
    text = flight_api.format_message("Mom", "RJ264", summary)
    assert "UTC" in text
