"""Characterizes storage.py's current JSON-file behavior, warts included."""

import json

import time_machine

import storage


def test_add_flight_defaults_countries_unknown():
    storage.add_flight("Mom", "rj264", "2026-08-05")
    flights = storage.load_flights()
    assert flights == [
        {
            "name": "Mom",
            "flight_iata": "RJ264",
            "date": "2026-08-05",
            "dep_country": "Unknown",
            "arr_country": "Unknown",
        }
    ]


def test_add_flight_allows_duplicate_flight_number():
    """Documents current behavior: no dedupe against an identical add."""
    storage.add_flight("Mom", "RJ264", "2026-08-05")
    storage.add_flight("Dad", "RJ264", "2026-08-05")
    assert len(storage.load_flights()) == 2


def test_remove_flight_removes_all_matching_codes_regardless_of_date():
    """Documents a known gap: /remove is not date-scoped."""
    storage.add_flight("Mom", "RJ264", "2026-08-05")
    storage.add_flight("Dad", "RJ264", "2026-09-01")
    removed = storage.remove_flight("rj264")
    assert removed is True
    assert storage.load_flights() == []


def test_remove_flight_returns_false_when_not_found():
    assert storage.remove_flight("RJ264") is False


def test_update_flight_countries_only_fills_unknown_fields():
    storage.add_flight("Mom", "RJ264", "2026-08-05", dep_country="Jordan")
    storage.update_flight_countries(
        "RJ264", dep_country="Nowhere", arr_country="United States"
    )
    flights = storage.load_flights()
    assert flights[0]["dep_country"] == "Jordan"  # not overwritten, already known
    assert flights[0]["arr_country"] == "United States"  # filled in from Unknown


def test_flight_schedule_defaults_when_absent():
    entry = storage.get_flight_schedule("RJ264")
    assert entry == {
        "last_checked": None,
        "done": False,
        "dep_scheduled": None,
        "arr_scheduled": None,
    }


def test_update_flight_schedule_merges_partial_fields():
    storage.update_flight_schedule("RJ264", last_checked="2026-08-05T09:00:00+00:00")
    storage.update_flight_schedule("RJ264", done=True)
    entry = storage.get_flight_schedule("rj264")  # case-insensitive key lookup
    assert entry == {
        "last_checked": "2026-08-05T09:00:00+00:00",
        "done": True,
        "dep_scheduled": None,
        "arr_scheduled": None,
    }


def test_usage_starts_at_zero_for_new_month():
    with time_machine.travel("2026-08-15T00:00:00+00:00"):
        usage = storage.load_usage()
    assert usage == {"month": "2026-08", "count": 0, "warned": False}


def test_increment_usage_persists_across_loads():
    with time_machine.travel("2026-08-15T00:00:00+00:00"):
        storage.increment_usage()
        storage.increment_usage()
        assert storage.load_usage()["count"] == 2


def test_usage_resets_in_memory_on_month_rollover_but_not_on_disk_until_next_write():
    """Documents an existing subtlety: the on-disk file can still show last
    month's data until something calls save_usage() again."""
    with time_machine.travel("2026-07-31T23:00:00+00:00"):
        storage.increment_usage()

    with time_machine.travel("2026-08-01T00:30:00+00:00"):
        usage = storage.load_usage()
        assert usage == {"month": "2026-08", "count": 0, "warned": False}

        with open(storage.USAGE_FILE, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["month"] == "2026-07"  # stale until the next save_usage()

        storage.increment_usage()
        with open(storage.USAGE_FILE, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk == {"month": "2026-08", "count": 1, "warned": False}


def test_usage_remaining_never_goes_negative():
    with time_machine.travel("2026-08-01T00:00:00+00:00"):
        for _ in range(5):
            storage.increment_usage()
        assert storage.usage_remaining(3) == 0


def test_mark_usage_warned_is_sticky_within_month():
    with time_machine.travel("2026-08-01T00:00:00+00:00"):
        storage.mark_usage_warned()
        assert storage.load_usage()["warned"] is True
