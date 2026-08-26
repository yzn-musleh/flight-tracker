"""New in Phase 2: characterizes airports.py's bundled-offline-dataset
lookups. No network involved at all -- static/airports.csv is read once and
cached in memory. See FINDINGS.md #4 for why this supersedes most of
tests/test_airports.py rather than editing it."""

import airports


def test_get_country_resolves_known_airport():
    assert airports.get_country("amm") == "Jordan"
    assert airports.get_country("JFK") == "United States"


def test_get_country_unknown_code_returns_unknown():
    assert airports.get_country("ZZZ99") == "Unknown"


def test_get_country_empty_input_returns_unknown():
    assert airports.get_country("") == "Unknown"
    assert airports.get_country(None) == "Unknown"


def test_get_timezone_resolves_known_airport():
    assert airports.get_timezone("AMM") == "Asia/Amman"
    assert airports.get_timezone("JFK") == "America/New_York"


def test_get_timezone_unknown_code_returns_none():
    assert airports.get_timezone("ZZZ99") is None


def test_get_timezone_empty_input_returns_none():
    assert airports.get_timezone("") is None
    assert airports.get_timezone(None) is None


def test_get_name_resolves_known_airport():
    assert airports.get_name("AMM") == "Queen Alia International Airport"


def test_get_name_unknown_code_returns_none():
    assert airports.get_name("ZZZ99") is None


def test_resolution_needs_no_api_key_and_no_network(monkeypatch):
    monkeypatch.delenv("AVIATIONSTACK_API_KEY", raising=False)
    # no_network fixture in conftest.py already makes any real requests.get
    # call blow up -- reaching a correct answer here proves no network path
    # exists at all, not just that it's unreached in this particular call.
    assert airports.get_country("AMM") == "Jordan"
