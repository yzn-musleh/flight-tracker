"""Wrapper around the Aviationstack API for flight status lookups."""
import os
import requests

import storage

AVIATIONSTACK_BASE_URL = "https://api.aviationstack.com/v1/flights"


class FlightLookupError(Exception):
    pass


class BudgetExhaustedError(FlightLookupError):
    """Raised when the monthly Aviationstack request budget is used up."""


def get_flight_status(flight_iata: str, flight_date: str = None) -> dict:
    """Fetch the current status for a flight number.

    flight_iata: e.g. "RJ264"
    flight_date: "YYYY-MM-DD", optional (helps disambiguate recurring flight numbers)
    Returns the first matching flight record from Aviationstack, or raises FlightLookupError.
    """
    api_key = os.environ.get("AVIATIONSTACK_API_KEY")
    if not api_key:
        raise FlightLookupError("AVIATIONSTACK_API_KEY is not set")

    cap = int(os.environ.get("MONTHLY_REQUEST_CAP", "100"))
    if storage.usage_remaining(cap) <= 0:
        raise BudgetExhaustedError(f"Monthly API budget exhausted ({cap} requests/month).")

    params = {"access_key": api_key, "flight_iata": flight_iata}
    if flight_date:
        params["flight_date"] = flight_date

    storage.increment_usage()
    resp = requests.get(AVIATIONSTACK_BASE_URL, params=params, timeout=15)
    resp.raise_for_status()
    payload = resp.json()

    if "error" in payload:
        raise FlightLookupError(payload["error"].get("message", "Unknown API error"))

    data = payload.get("data") or []
    if not data:
        raise FlightLookupError(
            f"No flight found for {flight_iata}" + (f" on {flight_date}" if flight_date else "")
        )

    return data[0]


def summarize(flight: dict) -> dict:
    """Extract the fields we care about for comparison/display."""
    dep = flight.get("departure") or {}
    arr = flight.get("arrival") or {}
    airline = (flight.get("airline") or {}).get("name")
    return {
        "status": flight.get("flight_status"),
        "airline": airline,
        "dep_airport": dep.get("airport"),
        "dep_iata": dep.get("iata"),
        "dep_scheduled": dep.get("scheduled"),
        "dep_estimated": dep.get("estimated"),
        "dep_actual": dep.get("actual"),
        "dep_delay": dep.get("delay"),
        "dep_terminal": dep.get("terminal"),
        "dep_gate": dep.get("gate"),
        "arr_airport": arr.get("airport"),
        "arr_iata": arr.get("iata"),
        "arr_scheduled": arr.get("scheduled"),
        "arr_estimated": arr.get("estimated"),
        "arr_actual": arr.get("actual"),
        "arr_delay": arr.get("delay"),
        "arr_terminal": arr.get("terminal"),
        "arr_gate": arr.get("gate"),
    }


def format_message(name: str, flight_iata: str, s: dict) -> str:
    lines = [f"✈️ {name} — {flight_iata} ({s.get('airline') or 'unknown airline'})"]
    lines.append(f"Status: {(s.get('status') or 'unknown').upper()}")
    lines.append(f"Departure: {s.get('dep_airport')}")
    if s.get("dep_estimated"):
        lines.append(f"  Estimated: {s['dep_estimated']}")
    if s.get("dep_delay"):
        lines.append(f"  Delay: {s['dep_delay']} min")
    if s.get("dep_gate"):
        lines.append(f"  Gate: {s['dep_gate']} (Terminal {s.get('dep_terminal', '-')})")
    lines.append(f"Arrival: {s.get('arr_airport')}")
    if s.get("arr_estimated"):
        lines.append(f"  Estimated: {s['arr_estimated']}")
    if s.get("arr_delay"):
        lines.append(f"  Delay: {s['arr_delay']} min")
    if s.get("arr_gate"):
        lines.append(f"  Gate: {s['arr_gate']} (Terminal {s.get('arr_terminal', '-')})")
    return "\n".join(lines)
