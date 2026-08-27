"""Characterizes the one-shot JSON -> SQLite importer added in Phase 1."""

import json
import os

import storage
from storage import importer


def _write(tmp_path, name, data):
    with open(tmp_path / name, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_import_is_a_no_op_when_no_legacy_files_exist(tmp_path):
    importer.run(base_dir=str(tmp_path))
    assert storage.load_flights("legacy") == []


def test_import_migrates_flights_state_schedule_usage_airports(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")  # pre-Phase-4 operator chat
    _write(
        tmp_path,
        "flights.json",
        [
            {
                "name": "Mom",
                "flight_iata": "RJ264",
                "date": "2026-08-05",
                "dep_country": "Jordan",
                "arr_country": "United States",
            }
        ],
    )
    _write(
        tmp_path,
        "state.json",
        {
            "RJ264": {
                "status": "scheduled",
                "dep_delay": None,
                "arr_delay": None,
                "dep_gate": "12",
                "arr_gate": None,
                "dep_estimated": None,
                "arr_estimated": None,
            }
        },
    )
    _write(
        tmp_path,
        "schedule.json",
        {
            "RJ264": {
                "last_checked": "2026-08-05T09:00:00+00:00",
                "done": False,
                "dep_scheduled": "2026-08-05T10:00:00+00:00",
                "arr_scheduled": None,
            }
        },
    )
    _write(tmp_path, "usage.json", {"month": "2026-08", "count": 3, "warned": True})
    _write(tmp_path, "airport_countries.json", {"AMM": "Jordan"})

    importer.run(base_dir=str(tmp_path))

    flights = storage.load_flights("999")
    assert flights == [
        {
            "name": "Mom",
            "flight_iata": "RJ264",
            "date": "2026-08-05",
            "dep_country": "Jordan",
            "arr_country": "United States",
        }
    ]
    assert storage.get_flight_state("RJ264", "2026-08-05")["status"] == "scheduled"
    assert storage.get_flight_schedule("RJ264", "2026-08-05")["last_checked"] == (
        "2026-08-05T09:00:00+00:00"
    )
    assert storage.load_usage()["count"] == 3
    assert storage.load_usage()["warned"] is True
    # airport_countries.json's contents are intentionally discarded (Phase 2
    # resolves country/timezone from the bundled static/airports.csv instead)
    # but the file itself is still renamed like the others.
    assert os.path.exists(tmp_path / "airport_countries.json.imported")
    # The pre-Phase-4 operator chat is auto-approved so upgrading doesn't
    # lock them out of their own already-tracked flights.
    assert storage.get_chat_access_status("999") == "approved"


def test_import_renames_source_files_so_a_second_run_is_a_no_op(tmp_path):
    _write(tmp_path, "flights.json", [])
    importer.run(base_dir=str(tmp_path))

    assert not os.path.exists(tmp_path / "flights.json")
    assert os.path.exists(tmp_path / "flights.json.imported")

    # second run: nothing left to import, must not error or duplicate data
    importer.run(base_dir=str(tmp_path))
    assert storage.load_flights("legacy") == []


def test_import_falls_back_to_unscoped_date_when_flight_number_is_ambiguous(tmp_path):
    """Two people on RJ264 on different dates: the old state.json/schedule.json
    couldn't tell them apart either, so this is a faithful (not worsened)
    migration of already-ambiguous data -- see storage/importer.py docstring."""
    _write(
        tmp_path,
        "flights.json",
        [
            {"name": "Mom", "flight_iata": "RJ264", "date": "2026-08-05"},
            {"name": "Dad", "flight_iata": "RJ264", "date": "2026-09-01"},
        ],
    )
    _write(tmp_path, "state.json", {"RJ264": {"status": "scheduled"}})

    importer.run(base_dir=str(tmp_path))

    assert storage.get_flight_state("RJ264", "") == {
        "status": "scheduled",
        "dep_delay": None,
        "arr_delay": None,
        "dep_gate": None,
        "arr_gate": None,
        "dep_estimated": None,
        "arr_estimated": None,
    }
