"""Simple JSON-backed storage for tracked flights and their last known state."""
import json
import os
from datetime import datetime, timezone
from threading import Lock

FLIGHTS_FILE = "flights.json"
STATE_FILE = "state.json"
SCHEDULE_FILE = "schedule.json"
USAGE_FILE = "usage.json"
_lock = Lock()


def _load(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_flights() -> list:
    return _load(FLIGHTS_FILE, [])


def save_flights(flights: list) -> None:
    with _lock:
        _save(FLIGHTS_FILE, flights)


def add_flight(
    name: str,
    flight_iata: str,
    date: str,
    dep_country: str = "Unknown",
    arr_country: str = "Unknown",
) -> None:
    flights = load_flights()
    flights.append(
        {
            "name": name,
            "flight_iata": flight_iata.upper(),
            "date": date,
            "dep_country": dep_country,
            "arr_country": arr_country,
        }
    )
    save_flights(flights)


def remove_flight(flight_iata: str) -> bool:
    flights = load_flights()
    new_flights = [f for f in flights if f["flight_iata"].upper() != flight_iata.upper()]
    changed = len(new_flights) != len(flights)
    if changed:
        save_flights(new_flights)
    return changed


def update_flight_countries(flight_iata: str, dep_country: str, arr_country: str) -> None:
    """Backfill dep/arr country once they've been resolved (e.g. via a later API lookup)."""
    flights = load_flights()
    changed = False
    for f in flights:
        if f["flight_iata"].upper() != flight_iata.upper():
            continue
        if f.get("dep_country", "Unknown") == "Unknown" and dep_country != "Unknown":
            f["dep_country"] = dep_country
            changed = True
        if f.get("arr_country", "Unknown") == "Unknown" and arr_country != "Unknown":
            f["arr_country"] = arr_country
            changed = True
    if changed:
        save_flights(flights)


def load_state() -> dict:
    return _load(STATE_FILE, {})


def save_state(state: dict) -> None:
    with _lock:
        _save(STATE_FILE, state)


_DEFAULT_SCHEDULE_ENTRY = {
    "last_checked": None,
    "done": False,
    "dep_scheduled": None,
    "arr_scheduled": None,
}


def load_schedule() -> dict:
    return _load(SCHEDULE_FILE, {})


def save_schedule(schedule: dict) -> None:
    with _lock:
        _save(SCHEDULE_FILE, schedule)


def get_flight_schedule(flight_iata: str) -> dict:
    """Per-flight polling bookkeeping: when it was last checked, whether it's
    done (landed/cancelled), and its known scheduled times."""
    entry = load_schedule().get(flight_iata.upper())
    return {**_DEFAULT_SCHEDULE_ENTRY, **entry} if entry else dict(_DEFAULT_SCHEDULE_ENTRY)


def update_flight_schedule(flight_iata: str, **fields) -> None:
    schedule = load_schedule()
    key = flight_iata.upper()
    entry = {**_DEFAULT_SCHEDULE_ENTRY, **schedule.get(key, {}), **fields}
    schedule[key] = entry
    save_schedule(schedule)


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def load_usage() -> dict:
    """Monthly Aviationstack request counter. Auto-resets when the calendar
    month rolls over."""
    usage = _load(USAGE_FILE, {})
    month = _current_month()
    if usage.get("month") != month:
        usage = {"month": month, "count": 0, "warned": False}
    return usage


def save_usage(usage: dict) -> None:
    with _lock:
        _save(USAGE_FILE, usage)


def increment_usage() -> int:
    usage = load_usage()
    usage["count"] += 1
    save_usage(usage)
    return usage["count"]


def usage_remaining(cap: int) -> int:
    return max(0, cap - load_usage()["count"])


def mark_usage_warned() -> None:
    usage = load_usage()
    usage["warned"] = True
    save_usage(usage)
