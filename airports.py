"""Resolves an airport IATA code to a country name, with caching in SQLite.

Caching matters because Aviationstack's free tier only allows 100
requests/month -- once an airport (e.g. AMM) has been resolved once, it's
never looked up again.
"""

import os

import requests

import storage

AIRPORTS_URL = "https://api.aviationstack.com/v1/airports"

# Unused since Phase 1 moved the cache into SQLite (storage.airports table).
# Kept only so tests written against the old JSON-cache file path don't error
# on setup; removed entirely once Phase 2 deletes the live airport lookup.
CACHE_FILE = "airport_countries.json"


def get_country(iata_code: str) -> str:
    """Return the country name for an airport IATA code, or 'Unknown' if it can't be resolved yet."""
    if not iata_code:
        return "Unknown"
    iata_code = iata_code.upper()

    cached = storage.get_airport_country(iata_code)
    if cached is not None:
        return cached

    api_key = os.environ.get("AVIATIONSTACK_API_KEY")
    if not api_key:
        return "Unknown"

    country = "Unknown"
    try:
        resp = requests.get(
            AIRPORTS_URL,
            params={"access_key": api_key, "iata_code": iata_code},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data") or []
        if data:
            country = data[0].get("country_name") or "Unknown"
    except Exception:
        # Network hiccup or quota exhausted -- leave as Unknown, we'll retry next check.
        return "Unknown"

    if country != "Unknown":
        storage.save_airport_country(iata_code, country)
    return country
