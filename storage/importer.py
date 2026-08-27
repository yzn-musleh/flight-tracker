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

airport_countries.json's contents are intentionally discarded, not imported:
Phase 2 replaced live-lookup-with-cache entirely with a bundled offline
dataset (airports.py + static/airports.csv), so cached entries are both
unnecessary and potentially stale. The file is still renamed to
`.imported` like the others so it doesn't linger around looking unhandled.

flights.json predates chat_id scoping (Phase 4) entirely -- it was written
by a single-tenant bot with one operator-wide TELEGRAM_CHAT_ID. Imported
subscriptions are assigned to that same chat (read directly from the
TELEGRAM_CHAT_ID env var, for this one-shot migration purpose only -- it's
not read anywhere else any more) so an upgrading operator's existing
tracked flights keep working without needing to /add them all again. If
that env var isn't set (e.g. a fresh checkout with old JSON files but no
matching .env), imported subscriptions land under the literal chat_id
"legacy" instead of being silently dropped or guessing wrong -- an operator
in that situation will need to re-track flights under their real chat_id
manually; there's no admin tool yet to reassign a subscription's chat_id.
"""

import json
import logging
import os

from . import (
    add_flight,
    save_flight_state,
    set_chat_access_status,
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

    legacy_chat_id = os.environ.get("TELEGRAM_CHAT_ID") or "legacy"
    flights = _load_json(flights_path, [])
    for f in flights:
        add_flight(
            legacy_chat_id,
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

    if flights and os.environ.get("TELEGRAM_CHAT_ID"):
        # The pre-Phase-4 operator chat was implicitly trusted (it was the
        # *only* chat) -- carry that trust forward so upgrading doesn't lock
        # the operator out of their own already-tracked flights. A real
        # ALLOWED_CHAT_IDS entry for this chat makes this redundant, but
        # doing it here too costs nothing and doesn't assume the operator
        # remembered to add one.
        set_chat_access_status(legacy_chat_id, "approved", decided_by="importer")

    for path in (flights_path, state_path, schedule_path, usage_path, airports_path):
        _mark_imported(path)

    log.info("Import complete: %d flight(s).", len(flights))
