"""Resolves an airport IATA code to its country and timezone using a bundled
offline dataset (static/airports.csv) -- no network call, no API quota spent,
ever. Replaces the Phase 1 SQLite-cached live Aviationstack /v1/airports
lookup entirely, per HARDENING_PLAN's Phase 2 scope.

The dataset is a filtered derivative of the OpenFlights Airport Database
(itself sourced primarily from OurAirports); see static/AIRPORTS_LICENSE.md
for its license (ODbL) and provenance.
"""

import csv
import os

_DATA_PATH = os.path.join(os.path.dirname(__file__), "static", "airports.csv")
_by_iata: dict[str, dict] | None = None


def _load() -> dict[str, dict]:
    global _by_iata
    if _by_iata is None:
        by_iata = {}
        with open(_DATA_PATH, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                by_iata[row["iata"]] = row
        _by_iata = by_iata
    return _by_iata


def get_country(iata_code: str | None) -> str:
    """Return the country name for an airport IATA code, or 'Unknown' if it's
    not in the bundled dataset."""
    if not iata_code:
        return "Unknown"
    row = _load().get(iata_code.upper())
    return row["country"] if row else "Unknown"


def get_timezone(iata_code: str | None) -> str | None:
    """Return the IANA timezone (e.g. 'Asia/Amman') for an airport IATA code,
    or None if it's not in the bundled dataset or has no timezone recorded."""
    if not iata_code:
        return None
    row = _load().get(iata_code.upper())
    return (row["tz"] or None) if row else None


def get_name(iata_code: str | None) -> str | None:
    """Return the airport's full name, or None if it's not in the dataset."""
    if not iata_code:
        return None
    row = _load().get(iata_code.upper())
    return row["name"] if row else None
