"""New in Phase 1: characterizes the SQLite-backed storage layer specifically
-- composite (flight_iata, date) keying, the ambiguity-detection error path,
the query-based usage counter, and the airports cache table. See
FINDINGS.md for why this supersedes part of tests/test_airports.py and
tests/test_storage.py rather than editing them."""

import sqlite3

import pytest
import time_machine

import storage


def test_migrations_create_expected_tables():
    with storage._db() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {
        "subscriptions",
        "flights",
        "change_events",
        "api_usage",
        "usage_warnings",
        "schema_version",
    } <= tables
    # migration 2 drops the Phase 1 airports cache table -- Phase 2 resolves
    # country/timezone from the bundled static/airports.csv dataset instead.
    assert "airports" not in tables


def test_migrations_are_idempotent_across_connections():
    with storage._db():
        pass
    with storage._db() as conn:
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert version == 2


def test_wal_mode_is_enabled():
    with storage._db() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_schedule_and_state_are_scoped_by_date_not_just_flight_number():
    """The bug documented in ARCHITECTURE.md: two people on the same flight
    number on different dates must not collide."""
    storage.update_flight_schedule(
        "RJ264", "2026-08-05", last_checked="2026-08-05T09:00:00+00:00"
    )
    storage.update_flight_schedule(
        "RJ264", "2026-09-01", last_checked="2026-09-01T09:00:00+00:00"
    )

    assert storage.get_flight_schedule("RJ264", "2026-08-05")["last_checked"] == (
        "2026-08-05T09:00:00+00:00"
    )
    assert storage.get_flight_schedule("RJ264", "2026-09-01")["last_checked"] == (
        "2026-09-01T09:00:00+00:00"
    )

    storage.save_flight_state("RJ264", "2026-08-05", {"status": "scheduled"})
    storage.save_flight_state("RJ264", "2026-09-01", {"status": "landed"})
    assert storage.get_flight_state("RJ264", "2026-08-05")["status"] == "scheduled"
    assert storage.get_flight_state("RJ264", "2026-09-01")["status"] == "landed"


def test_get_flight_schedule_without_date_raises_on_genuine_ambiguity():
    storage.update_flight_schedule("RJ264", "2026-08-05", last_checked="x")
    storage.update_flight_schedule("RJ264", "2026-09-01", last_checked="y")
    with pytest.raises(ValueError, match="Multiple tracked dates"):
        storage.get_flight_schedule("RJ264")


def test_get_flight_schedule_without_date_resolves_unambiguous_single_match():
    storage.update_flight_schedule("RJ264", "2026-08-05", last_checked="x")
    assert storage.get_flight_schedule("RJ264")["last_checked"] == "x"


def test_get_flight_state_returns_none_before_first_snapshot():
    assert storage.get_flight_state("RJ264", "2026-08-05") is None


def test_usage_count_is_computed_from_the_event_log_not_a_cached_value():
    """Unlike the old JSON counter (see FINDINGS.md #1), nothing needs to be
    written to "reset" the count after a month rolls over -- it's always
    freshly computed from rows actually in this month."""
    with time_machine.travel("2026-07-15T00:00:00+00:00"):
        storage.increment_usage()
        storage.increment_usage()

    with time_machine.travel("2026-08-01T00:00:01+00:00"):
        assert storage.load_usage() == {"month": "2026-08", "count": 0, "warned": False}


def test_increment_usage_records_provider_and_endpoint():
    storage.increment_usage(
        provider="aviationstack", endpoint="flights", http_status=200
    )
    with storage._db() as conn:
        row = conn.execute(
            "SELECT provider, endpoint, http_status FROM api_usage"
        ).fetchone()
    assert row["provider"] == "aviationstack"
    assert row["endpoint"] == "flights"
    assert row["http_status"] == 200


def test_db_file_is_actually_sqlite(tmp_path):
    storage.add_flight("Mom", "RJ264", "2026-08-05")  # forces DB creation
    conn = sqlite3.connect(storage.DB_PATH)
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    assert "subscriptions" in tables
