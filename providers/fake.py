"""A FlightProvider driven by canned responses, for tests -- per CLAUDE.md's
Testing section: "A FakeProvider driven by recorded JSON fixtures is the
backbone; no test may hit a real API." Not yet wired into the main test
suite (Phase 0/1's tests already achieve "no real API" by stubbing
flight_api.get_flight_status directly); this is the seam future tests can
build on without needing flight_api.py's internals at all.
"""

from providers.base import FlightSnapshot, QuotaPolicy


class FakeProvider:
    supports_push = False

    def __init__(
        self,
        responses: dict[str, list[FlightSnapshot | Exception]] | None = None,
        quota: QuotaPolicy | None = None,
    ) -> None:
        """responses: {flight_iata: [snapshot_or_exception, ...]}. Each call
        to get_flight() for that flight code pops the next queued item --
        return it if it's a FlightSnapshot, raise it if it's an Exception.
        This lets a test simulate a sequence of polls (e.g. baseline, then a
        status change) the same way a recorded fixture would."""
        self._responses = {k.upper(): list(v) for k, v in (responses or {}).items()}
        self.quota = quota or QuotaPolicy(monthly_cap=100, safety_margin=5)
        self.calls: list[tuple[str, str | None]] = []

    def get_flight(self, flight_iata: str, date: str | None = None) -> FlightSnapshot:
        self.calls.append((flight_iata, date))
        queue = self._responses.get(flight_iata.upper())
        if not queue:
            from flight_api import FlightLookupError

            raise FlightLookupError(
                f"FakeProvider has no queued response for {flight_iata}"
            )
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
