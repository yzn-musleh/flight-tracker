"""New in Phase 2: characterizes the FlightProvider Protocol, its
Aviationstack adapter, the FakeProvider, and provider selection."""

import pytest

import flight_api
import providers
from providers import AviationstackProvider, FakeProvider, QuotaPolicy, get_provider

AVIATIONSTACK_FLIGHT_RECORD = {
    "flight_status": "active",
    "airline": {"name": "Royal Jordanian"},
    "departure": {"airport": "Queen Alia International", "iata": "AMM"},
    "arrival": {"airport": "JFK", "iata": "JFK"},
}


def test_aviationstack_provider_conforms_to_the_protocol():
    assert isinstance(AviationstackProvider(), providers.FlightProvider)


def test_fake_provider_conforms_to_the_protocol():
    assert isinstance(FakeProvider(), providers.FlightProvider)


def test_aviationstack_provider_declares_quota_from_env(monkeypatch):
    monkeypatch.setenv("MONTHLY_REQUEST_CAP", "250")
    monkeypatch.setenv("REQUEST_SAFETY_MARGIN", "10")
    provider = AviationstackProvider()
    assert provider.quota == QuotaPolicy(monthly_cap=250, safety_margin=10)
    assert provider.supports_push is False


def test_aviationstack_provider_get_flight_returns_normalized_snapshot(monkeypatch):
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "fake-key")
    monkeypatch.setattr(
        flight_api,
        "get_flight_status",
        lambda flight_iata, date=None: AVIATIONSTACK_FLIGHT_RECORD,
    )
    provider = AviationstackProvider()
    snapshot = provider.get_flight("RJ264", "2026-08-05")
    assert snapshot["status"] == "active"
    assert snapshot["dep_iata"] == "AMM"
    assert snapshot["arr_iata"] == "JFK"


def test_aviationstack_provider_propagates_provider_exceptions(monkeypatch):
    def _raise(flight_iata, date=None):
        raise flight_api.BudgetExhaustedError("out of budget")

    monkeypatch.setattr(flight_api, "get_flight_status", _raise)
    provider = AviationstackProvider()
    with pytest.raises(flight_api.BudgetExhaustedError):
        provider.get_flight("RJ264")


def test_fake_provider_returns_queued_snapshots_in_order():
    provider = FakeProvider(
        responses={"RJ264": [{"status": "scheduled"}, {"status": "active"}]}
    )
    assert provider.get_flight("rj264")["status"] == "scheduled"
    assert provider.get_flight("RJ264")["status"] == "active"
    assert provider.calls == [("rj264", None), ("RJ264", None)]


def test_fake_provider_raises_queued_exceptions():
    provider = FakeProvider(
        responses={"RJ264": [flight_api.FlightLookupError("no data yet")]}
    )
    with pytest.raises(flight_api.FlightLookupError, match="no data yet"):
        provider.get_flight("RJ264")


def test_fake_provider_raises_lookup_error_when_queue_exhausted():
    provider = FakeProvider(responses={"RJ264": [{"status": "scheduled"}]})
    provider.get_flight("RJ264")
    with pytest.raises(flight_api.FlightLookupError, match="no queued response"):
        provider.get_flight("RJ264")


def test_get_provider_defaults_to_aviationstack(monkeypatch):
    monkeypatch.delenv("FLIGHT_PROVIDER", raising=False)
    assert isinstance(get_provider(), AviationstackProvider)


def test_get_provider_reads_flight_provider_env(monkeypatch):
    monkeypatch.setenv("FLIGHT_PROVIDER", "fake")
    assert isinstance(get_provider(), FakeProvider)


def test_get_provider_explicit_name_overrides_env(monkeypatch):
    monkeypatch.setenv("FLIGHT_PROVIDER", "aviationstack")
    assert isinstance(get_provider("fake"), FakeProvider)


def test_get_provider_rejects_unknown_name():
    with pytest.raises(ValueError, match="Unknown FLIGHT_PROVIDER"):
        get_provider("not-a-real-provider")
