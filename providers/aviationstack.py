"""Adapts flight_api.py's existing Aviationstack client to the FlightProvider
Protocol. flight_api.py itself is untouched -- it's still the single source
of truth for the wire format and the hard quota gate (both predate this
Protocol and are already exactly what CLAUDE.md's invariants require); this
module just wraps it so it satisfies FlightProvider's shape.
"""

import os
from typing import cast

import flight_api
from providers.base import FlightSnapshot, QuotaPolicy


class AviationstackProvider:
    supports_push = False

    def __init__(self) -> None:
        self.quota = QuotaPolicy(
            monthly_cap=int(os.environ.get("MONTHLY_REQUEST_CAP", "100")),
            safety_margin=int(os.environ.get("REQUEST_SAFETY_MARGIN", "5")),
        )

    def get_flight(self, flight_iata: str, date: str | None = None) -> FlightSnapshot:
        # flight_api.get_flight_status's own signature predates this Protocol
        # and has a pre-existing implicit-Optional annotation gap (flagged by
        # ruff's RUF013, left alone per Phase 0/1's "don't touch code outside
        # this phase's scope"); the cast documents that get_flight_status
        # does accept None here even though its type hint says str.
        flight = flight_api.get_flight_status(flight_iata, cast(str, date))
        return cast(FlightSnapshot, flight_api.summarize(flight))
