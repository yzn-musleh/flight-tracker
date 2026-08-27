"""New in Phase 5: characterizes flight_api.get_flight_status()'s retry,
backoff, and circuit-breaker behavior for 429/5xx responses, and that a
non-429 4xx fails fast without retrying. No real sleeping (resilience's
retry_with_backoff is exercised through its real, injectable sleep -- here
monkeypatched to a no-op so the test suite stays fast)."""

import pytest

import flight_api
import resilience


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {"data": [{"flight_status": "active"}]}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _fresh_breaker(monkeypatch):
    """Each test gets an independent circuit breaker -- the real module-level
    one is process-lifetime, which would leak open/closed state across tests."""
    monkeypatch.setattr(flight_api, "_breaker", resilience.CircuitBreaker(name="test"))


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(resilience.time, "sleep", lambda seconds: None)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("AVIATIONSTACK_API_KEY", "fake-key")


def test_succeeds_immediately_with_no_retry_on_200(monkeypatch):
    calls = []

    def _get(*a, **k):
        calls.append(1)
        return _FakeResponse(200)

    monkeypatch.setattr(flight_api.requests, "get", _get)

    result = flight_api.get_flight_status("RJ264")

    assert result["flight_status"] == "active"
    assert len(calls) == 1


def test_retries_on_429_then_succeeds(monkeypatch):
    responses = iter([_FakeResponse(429), _FakeResponse(200)])
    monkeypatch.setattr(flight_api.requests, "get", lambda *a, **k: next(responses))

    result = flight_api.get_flight_status("RJ264")

    assert result["flight_status"] == "active"


def test_persistent_5xx_opens_the_circuit_breaker(monkeypatch):
    monkeypatch.setattr(flight_api.requests, "get", lambda *a, **k: _FakeResponse(503))
    flight_api._breaker.failure_threshold = 1

    with pytest.raises(flight_api.FlightLookupError):
        flight_api.get_flight_status("RJ264")

    assert flight_api._breaker.is_open is True


def test_open_circuit_breaker_short_circuits_without_a_network_call(monkeypatch):
    def _unexpected(*a, **k):
        raise AssertionError("should not call the network while the circuit is open")

    monkeypatch.setattr(flight_api.requests, "get", _unexpected)
    flight_api._breaker.record_failure()
    flight_api._breaker.failure_threshold = 1
    flight_api._breaker.record_failure()  # opens it

    with pytest.raises(flight_api.FlightLookupError, match="Circuit breaker"):
        flight_api.get_flight_status("RJ264")


def test_non_429_4xx_fails_fast_without_retrying(monkeypatch):
    calls = []

    def _get(*a, **k):
        calls.append(1)
        return _FakeResponse(404)

    monkeypatch.setattr(flight_api.requests, "get", _get)

    with pytest.raises(flight_api.FlightLookupError, match="HTTP 404"):
        flight_api.get_flight_status("RJ264")

    assert len(calls) == 1  # not retried


def test_each_retry_attempt_increments_usage_separately(monkeypatch):
    responses = iter([_FakeResponse(429), _FakeResponse(429), _FakeResponse(200)])
    monkeypatch.setattr(flight_api.requests, "get", lambda *a, **k: next(responses))

    flight_api.get_flight_status("RJ264")

    import storage

    assert storage.load_usage()["count"] == 3  # one per real HTTP attempt


def test_network_error_records_a_circuit_failure_and_raises_lookup_error(monkeypatch):
    import requests

    def _boom(*a, **k):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(flight_api.requests, "get", _boom)

    with pytest.raises(flight_api.FlightLookupError, match="Network error"):
        flight_api.get_flight_status("RJ264")

    assert flight_api._breaker._consecutive_failures == 1
