"""Shared fixtures for characterization tests.

Phase 1 replaced storage.py's flat JSON files with a single SQLite database
(storage.DB_PATH). Isolating a test is now a matter of pointing storage.DB_PATH
at a fresh file per test instead of patching four separate JSON path
constants -- the test *intent* (each test starts from empty, isolated state,
never touches a real file, never hits the network) is unchanged from Phase 0.

A handful of Phase 0 tests characterized JSON-file-specific or live-network
implementation details that no longer exist after Phase 1 (SQLite storage)
and Phase 2 (bundled offline airport data) -- see FINDINGS.md for each one.
Per CLAUDE.md's rule against editing a Phase 0 test to make it pass, their
source is untouched; they're marked xfail here instead, in one place, with a
reason that links to FINDINGS.md.
"""

import pytest

import storage

XFAIL_SUPERSEDED = {
    # Characterized a mutable JSON counter blob's on-disk staleness after a
    # month rollover. The SQLite api_usage table is a query-based event log
    # with no such staleness window -- see FINDINGS.md #1.
    "tests/test_storage.py::test_usage_resets_in_memory_on_month_rollover_but_not_on_disk_until_next_write",
    # Both assert the airport-country cache is a JSON file at airports.CACHE_FILE.
    # Phase 1 moved that cache into the SQLite `airports` table -- see
    # FINDINGS.md #2.
    "tests/test_airports.py::test_get_country_caches_successful_lookup_to_disk",
    "tests/test_airports.py::test_get_country_uses_cache_without_calling_network_again",
    # Phase 2 replaced the entire live-lookup-with-cache mechanism with a
    # bundled offline dataset -- these characterized behavior (falls back to
    # "Unknown" without an API key/on a network error; doesn't cache a miss)
    # that no longer applies once there's no network call at all. See
    # FINDINGS.md #4.
    "tests/test_airports.py::test_get_country_returns_unknown_without_api_key_and_makes_no_call",
    "tests/test_airports.py::test_get_country_does_not_cache_unresolved_lookup",
    "tests/test_airports.py::test_get_country_swallows_network_errors_as_unknown",
    # This test's own docstring flagged it as documenting a bug (a field
    # going non-null -> null incorrectly firing an alert) and said Phase 3
    # was expected to fix it. Phase 3 did: change_detection.detect_changes()
    # now enforces the null-guard. See FINDINGS.md #5. New coverage of the
    # correct behavior is in tests/test_change_detection.py.
    "tests/test_bot_alerts.py::test_alert_fires_on_value_to_null_transition",
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.nodeid.replace("\\", "/") in XFAIL_SUPERSEDED:
            item.add_marker(
                pytest.mark.xfail(
                    reason="Superseded by a later phase's intentional behavior change; see FINDINGS.md",
                    strict=False,
                )
            )


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "test.db"))
    yield tmp_path


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """A developer's real .env / shell may export a live API key. Tests must
    behave identically regardless -- delete anything that could make
    get_flight_status/get_country think real credentials are available,
    unless an individual test opts back in via monkeypatch.setenv."""
    for var in ("AVIATIONSTACK_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Belt-and-suspenders: any test that forgets to stub requests.get fails
    loudly instead of silently making a real HTTP call."""

    def _blocked(*args, **kwargs):
        raise AssertionError("test attempted a real network call via requests.get")

    monkeypatch.setattr("requests.get", _blocked)
