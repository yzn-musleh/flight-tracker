"""Characterizes flight_api.py without ever hitting the real network.

requests.get is stubbed per-test with a canned response shaped like a real
Aviationstack /v1/flights payload.
"""

import pytest

import flight_api
import storage


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise flight_api.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


AVIATIONSTACK_FLIGHT_RECORD = {
    "flight_status": "active",
    "airline": {"name": "Royal Jordanian"},
    "departure": {
        "airport": "Queen Alia International",
        "iata": "AMM",
        "scheduled": "2026-08-05T10:00:00+00:00",
        "estimated": "2026-08-05T10:05:00+00:00",
        "actual": None,
        "delay": 5,
        "terminal": "1",
        "gate": "12",
    },
    "arrival": {
        "airport": "JFK",
        "iata": "JFK",
        "scheduled": "2026-08-05T14:00:00+00:00",
        "estimated": None,
        "actual": None,
        "delay": None,
        "terminal": None,
        "gate": None,
    },
}


def test_get_flight_status_missing_api_key_raises_without_network(monkeypatch):
    monkeypatch.delenv("AVIATIONSTACK_API_KEY", raising=False)
    with pytest.raises(flight_api.FlightLookupError, match="AVIATIONSTACK_API_KEY"):
        flight_api.get_flight_status("RJ264")


def test_get_flight_status_raises_before_any_request_when_budget_exhausted(monkeypatch):
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "fake-key")
    monkeypatch.setenv("MONTHLY_REQUEST_CAP", "1")
    storage.increment_usage()  # usage now at cap

    def _unexpected_get(*a, **k):
        raise AssertionError("should not call requests.get once budget is exhausted")

    monkeypatch.setattr(flight_api.requests, "get", _unexpected_get)

    with pytest.raises(flight_api.BudgetExhaustedError):
        flight_api.get_flight_status("RJ264")


def test_get_flight_status_increments_usage_even_though_it_returns_a_result(
    monkeypatch,
):
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "fake-key")
    monkeypatch.setenv("MONTHLY_REQUEST_CAP", "100")
    monkeypatch.setattr(
        flight_api.requests,
        "get",
        lambda *a, **k: _FakeResponse({"data": [AVIATIONSTACK_FLIGHT_RECORD]}),
    )
    flight_api.get_flight_status("RJ264", "2026-08-05")
    assert storage.load_usage()["count"] == 1


def test_get_flight_status_raises_on_api_error_payload(monkeypatch):
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "fake-key")
    monkeypatch.setattr(
        flight_api.requests,
        "get",
        lambda *a, **k: _FakeResponse({"error": {"message": "invalid_access_key"}}),
    )
    with pytest.raises(flight_api.FlightLookupError, match="invalid_access_key"):
        flight_api.get_flight_status("RJ264")


def test_get_flight_status_raises_when_no_data_returned(monkeypatch):
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "fake-key")
    monkeypatch.setattr(
        flight_api.requests, "get", lambda *a, **k: _FakeResponse({"data": []})
    )
    with pytest.raises(flight_api.FlightLookupError, match="No flight found for RJ264"):
        flight_api.get_flight_status("RJ264")


def test_get_flight_status_returns_first_matching_record(monkeypatch):
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "fake-key")
    second_record = {**AVIATIONSTACK_FLIGHT_RECORD, "flight_status": "landed"}
    monkeypatch.setattr(
        flight_api.requests,
        "get",
        lambda *a, **k: _FakeResponse(
            {"data": [AVIATIONSTACK_FLIGHT_RECORD, second_record]}
        ),
    )
    result = flight_api.get_flight_status("RJ264")
    assert result["flight_status"] == "active"


def test_summarize_extracts_flat_fields():
    summary = flight_api.summarize(AVIATIONSTACK_FLIGHT_RECORD)
    assert summary == {
        "status": "active",
        "airline": "Royal Jordanian",
        "dep_airport": "Queen Alia International",
        "dep_iata": "AMM",
        "dep_scheduled": "2026-08-05T10:00:00+00:00",
        "dep_estimated": "2026-08-05T10:05:00+00:00",
        "dep_actual": None,
        "dep_delay": 5,
        "dep_terminal": "1",
        "dep_gate": "12",
        "arr_airport": "JFK",
        "arr_iata": "JFK",
        "arr_scheduled": "2026-08-05T14:00:00+00:00",
        "arr_estimated": None,
        "arr_actual": None,
        "arr_delay": None,
        "arr_terminal": None,
        "arr_gate": None,
    }


def test_summarize_tolerates_missing_departure_and_arrival_blocks():
    assert flight_api.summarize({}) == {
        "status": None,
        "airline": None,
        "dep_airport": None,
        "dep_iata": None,
        "dep_scheduled": None,
        "dep_estimated": None,
        "dep_actual": None,
        "dep_delay": None,
        "dep_terminal": None,
        "dep_gate": None,
        "arr_airport": None,
        "arr_iata": None,
        "arr_scheduled": None,
        "arr_estimated": None,
        "arr_actual": None,
        "arr_delay": None,
        "arr_terminal": None,
        "arr_gate": None,
    }


def test_format_message_includes_delay_and_gate_only_when_present():
    summary = flight_api.summarize(AVIATIONSTACK_FLIGHT_RECORD)
    text = flight_api.format_message("Mom", "RJ264", summary)
    assert "Mom — RJ264 (Royal Jordanian)" in text
    assert "Status: ACTIVE" in text
    assert "Delay: 5 min" in text
    assert "Gate: 12 (Terminal 1)" in text
    # arrival has no delay/gate in the fixture
    assert "Arrival: JFK" in text
    assert text.count("Delay:") == 1
    assert text.count("Gate:") == 1


def test_format_message_handles_entirely_missing_fields():
    text = flight_api.format_message("Mom", "RJ264", {})
    assert "Status: UNKNOWN" in text
    assert "Departure: None" in text
