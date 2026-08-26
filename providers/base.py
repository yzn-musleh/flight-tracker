"""The FlightProvider Protocol: what any flight-status data source must
implement to be usable by bot.py. Adding a provider means adding one module
implementing this shape and registering it in providers/__init__.py --
nothing in bot.py, scheduler.py, or storage.py should need to change.
"""

from dataclasses import dataclass
from typing import Protocol, TypedDict, runtime_checkable


@dataclass(frozen=True)
class QuotaPolicy:
    """Declares a provider's request budget so the scheduler/bot layer can
    reason about it generically. Enforcement itself still happens inside the
    provider (see CLAUDE.md invariant #3: the quota guard is a hard gate in
    the provider layer, not a courtesy check in the scheduler) -- this is
    just the introspectable declaration of what that gate's limits are.
    """

    monthly_cap: int
    safety_margin: int = 0


class FlightSnapshot(TypedDict, total=False):
    """The normalized, provider-agnostic shape bot.py works with. Field names
    match what flight_api.summarize() has always produced."""

    status: str | None
    airline: str | None
    dep_airport: str | None
    dep_iata: str | None
    dep_scheduled: str | None
    dep_estimated: str | None
    dep_actual: str | None
    dep_delay: int | None
    dep_terminal: str | None
    dep_gate: str | None
    arr_airport: str | None
    arr_iata: str | None
    arr_scheduled: str | None
    arr_estimated: str | None
    arr_actual: str | None
    arr_delay: int | None
    arr_terminal: str | None
    arr_gate: str | None


@runtime_checkable
class FlightProvider(Protocol):
    quota: QuotaPolicy
    supports_push: bool

    def get_flight(self, flight_iata: str, date: str | None = None) -> FlightSnapshot:
        """Return the current snapshot for a flight.

        Raises flight_api.FlightLookupError if the flight can't be found (or
        the response is otherwise unusable), and
        flight_api.BudgetExhaustedError if the provider's monthly quota is
        used up. These live in flight_api.py rather than here since they
        predate the Protocol and every current/planned provider needs the
        exact same two failure modes -- introducing parallel
        provider-specific exception types would just make bot.py's error
        handling provider-aware, which is what this Protocol exists to avoid.
        """
        ...
