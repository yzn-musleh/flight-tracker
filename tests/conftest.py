"""Shared fixtures for characterization tests.

storage.py keeps its JSON file paths as module-level string constants and
re-reads them on every call, so pointing a test at an isolated tmp directory
is just a matter of monkeypatching those constants -- no chdir, no real files
outside pytest's tmp_path, and never any network access.
"""

import pytest

import airports
import storage


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "FLIGHTS_FILE", str(tmp_path / "flights.json"))
    monkeypatch.setattr(storage, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(storage, "SCHEDULE_FILE", str(tmp_path / "schedule.json"))
    monkeypatch.setattr(storage, "USAGE_FILE", str(tmp_path / "usage.json"))
    monkeypatch.setattr(
        airports, "CACHE_FILE", str(tmp_path / "airport_countries.json")
    )
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
