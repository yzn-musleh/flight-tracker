"""Characterizes airports.py's country-resolution cache (superseded in Phase 2
by bundled offline data, but this documents today's behavior first)."""

import json

import airports


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_get_country_returns_unknown_for_empty_code():
    assert airports.get_country("") == "Unknown"
    assert airports.get_country(None) == "Unknown"


def test_get_country_returns_unknown_without_api_key_and_makes_no_call(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AVIATIONSTACK_API_KEY", raising=False)
    assert airports.get_country("AMM") == "Unknown"


def test_get_country_caches_successful_lookup_to_disk(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        airports, "CACHE_FILE", str(tmp_path / "airport_countries.json")
    )
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "fake-key")
    monkeypatch.setattr(
        airports.requests,
        "get",
        lambda *a, **k: _FakeResponse({"data": [{"country_name": "Jordan"}]}),
    )

    result = airports.get_country("amm")
    assert result == "Jordan"

    with open(airports.CACHE_FILE, encoding="utf-8") as f:
        cache = json.load(f)
    assert cache == {"AMM": "Jordan"}


def test_get_country_uses_cache_without_calling_network_again(monkeypatch, tmp_path):
    monkeypatch.setattr(
        airports, "CACHE_FILE", str(tmp_path / "airport_countries.json")
    )
    with open(airports.CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"AMM": "Jordan"}, f)

    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "fake-key")

    def _unexpected_get(*a, **k):
        raise AssertionError("cache hit should not call the network")

    monkeypatch.setattr(airports.requests, "get", _unexpected_get)

    assert airports.get_country("AMM") == "Jordan"


def test_get_country_does_not_cache_unresolved_lookup(monkeypatch, tmp_path):
    monkeypatch.setattr(
        airports, "CACHE_FILE", str(tmp_path / "airport_countries.json")
    )
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "fake-key")
    monkeypatch.setattr(
        airports.requests, "get", lambda *a, **k: _FakeResponse({"data": []})
    )

    assert airports.get_country("ZZZ") == "Unknown"
    assert not __import__("os").path.exists(airports.CACHE_FILE)


def test_get_country_swallows_network_errors_as_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(
        airports, "CACHE_FILE", str(tmp_path / "airport_countries.json")
    )
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "fake-key")

    def _boom(*a, **k):
        raise ConnectionError("network is down")

    monkeypatch.setattr(airports.requests, "get", _boom)

    assert airports.get_country("AMM") == "Unknown"
