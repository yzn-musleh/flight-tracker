"""Resolves an airport IATA code to a country name, with local caching.

Caching matters because Aviationstack's free tier only allows 100
requests/month — once an airport (e.g. AMM) has been resolved once, it's
never looked up again.
"""
import json
import os
import requests

CACHE_FILE = "airport_countries.json"
AIRPORTS_URL = "https://api.aviationstack.com/v1/airports"


def _load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_cache(cache: dict) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def get_country(iata_code: str) -> str:
    """Return the country name for an airport IATA code, or 'Unknown' if it can't be resolved yet."""
    if not iata_code:
        return "Unknown"
    iata_code = iata_code.upper()

    cache = _load_cache()
    if iata_code in cache:
        return cache[iata_code]

    api_key = os.environ.get("AVIATIONSTACK_API_KEY")
    if not api_key:
        return "Unknown"

    country = "Unknown"
    try:
        resp = requests.get(
            AIRPORTS_URL, params={"access_key": api_key, "iata_code": iata_code}, timeout=15
        )
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data") or []
        if data:
            country = data[0].get("country_name") or "Unknown"
    except Exception:
        # Network hiccup or quota exhausted — leave as Unknown, we'll retry next check.
        return "Unknown"

    if country != "Unknown":
        cache[iata_code] = country
        _save_cache(cache)
    return country
