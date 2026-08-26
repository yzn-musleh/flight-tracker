"""One-shot importer: reads the old flat JSON files into the SQLite DB, then
renames each one to `<name>.json.imported` so a second run is a no-op (the
`.json` files won't exist any more) and nothing already in the DB is
overwritten silently.

The old files had no date-scoping for state.json/schedule.json (keyed by
flight_iata alone). Where flights.json has exactly one subscription for that
flight code, we import into that specific (flight_iata, date) row; otherwise
we fall back to the same "" date bucket get_flight_schedule()/
get_flight_state() already treat as "no specific date known" -- this is a
faithful migration of already-ambiguous data, not a new ambiguity.
"""

import json
import logging
import os

from . import (
    add_flight,
    save_airport_country,
    save_flight_state,
    update_flight_schedule,
)

log = logging.getLogger("flight_tracker.storage.importer")

FLIGHTS_FILE = "flights.json"
STATE_FILE = "state.json"
SCHEDULE_FILE = "schedule.json"
USAGE_FILE = "usage.json"
AIRPORT_CACHE_FILE = "airport_countries.json"


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _mark_imported(path: str) -> None:
    if os.path.exists(path):
        os.rename(path, path + ".imported")


def _single_date_for(flight_iata: str, flights: list[dict]) -> str:
    dates = {
        f["date"] for f in flights if f["flight_iata"].upper() == flight_iata.upper()
    }
    return next(iter(dates)) if len(dates) == 1 else ""


def run(base_dir: str = ".") -> None:
    flights_path = os.path.join(base_dir, FLIGHTS_FILE)
    state_path = os.path.join(base_dir, STATE_FILE)
    schedule_path = os.path.join(base_dir, SCHEDULE_FILE)
    usage_path = os.path.join(base_dir, USAGE_FILE)
    airports_path = os.path.join(base_dir, AIRPORT_CACHE_FILE)

    any_found = any(
        os.path.exists(p)
        for p in (flights_path, state_path, schedule_path, usage_path, airports_path)
    )
    if not any_found:
        return

    log.info("Importing legacy JSON state into SQLite (one-shot)...")

    flights = _load_json(flights_path, [])
    for f in flights:
        add_flight(
            f["name"],
            f["flight_iata"],
            f["date"],
            f.get("dep_country", "Unknown"),
            f.get("arr_country", "Unknown"),
        )

    schedule = _load_json(schedule_path, {})
    for flight_iata, entry in schedule.items():
        date = _single_date_for(flight_iata, flights)
        update_flight_schedule(
            flight_iata,
            date,
            last_checked=entry.get("last_checked"),
            done=bool(entry.get("done", False)),
            dep_scheduled=entry.get("dep_scheduled"),
            arr_scheduled=entry.get("arr_scheduled"),
        )

    state = _load_json(state_path, {})
    for flight_iata, key_fields in state.items():
        date = _single_date_for(flight_iata, flights)
        # get_flight_schedule() would collide with the above if a flight has
        # no subscription row at all, but that can't happen for a flight that
        # made it into state.json (it had to be tracked to be checked).
        save_flight_state(flight_iata, date, key_fields)

    usage = _load_json(usage_path, None)
    if usage:
        from . import increment_usage, mark_usage_warned

        for _ in range(usage.get("count", 0)):
            increment_usage()
        if usage.get("warned"):
            mark_usage_warned()

    airports = _load_json(airports_path, {})
    for iata, country in airports.items():
        save_airport_country(iata, country)

    for path in (flights_path, state_path, schedule_path, usage_path, airports_path):
        _mark_imported(path)

    log.info(
        "Import complete: %d flight(s), %d airport(s).", len(flights), len(airports)
    )
