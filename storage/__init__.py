"""SQLite-backed storage (WAL mode) behind a small repository-style facade.

Phase 0's characterization tests call these functions directly, so the public
names and return shapes are preserved from the old JSON-file implementation
wherever the underlying behavior didn't need to change. Two things did
change, both required by CLAUDE.md's invariants and HARDENING_PLAN's Phase 1
scope:

1. Flights are now keyed by (flight_iata, scheduled_date), not flight_iata
   alone -- so two people on the same flight number on different dates no
   longer collide (see ARCHITECTURE.md's "known gaps"). Callers that already
   know the date (bot.py's scheduler loop) pass it explicitly. Callers that
   don't (existing tests, a bare `/status` lookup) can omit it; the lookup
   then resolves to the single matching row if there's exactly one, and
   raises if the flight code is genuinely ambiguous, rather than silently
   guessing.
2. Monthly usage is a queryable event log (one row per request) instead of a
   mutable counter blob, which incidentally removes a real bug: the old
   on-disk usage.json could show last month's count until something happened
   to call save_usage() again after the rollover. A query-based count is
   always correct the instant you ask.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock

from . import migrations

DB_PATH = os.environ.get("DB_PATH", "flights.db")
_lock = Lock()

_DEFAULT_SCHEDULE_ENTRY = {
    "last_checked": None,
    "done": False,
    "dep_scheduled": None,
    "arr_scheduled": None,
}

_SNAPSHOT_FIELDS = (
    "status",
    "dep_delay",
    "arr_delay",
    "dep_gate",
    "arr_gate",
    "dep_estimated",
    "arr_estimated",
)


@contextmanager
def _db():
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        try:
            migrations.apply(conn)
            yield conn
            conn.commit()
        finally:
            conn.close()


def _resolve_date(conn, flight_iata: str, date: str | None) -> str:
    """Turn an optional date into a concrete scheduled_date key.

    date=None means "the caller doesn't know/care" -- fine as long as there's
    at most one tracked date for this flight code; a real ambiguity must be
    disambiguated explicitly rather than guessed at.
    """
    if date is not None:
        return date
    rows = conn.execute(
        "SELECT DISTINCT scheduled_date FROM flights WHERE flight_iata = ?",
        (flight_iata,),
    ).fetchall()
    if len(rows) > 1:
        raise ValueError(
            f"Multiple tracked dates for {flight_iata}; pass date explicitly to disambiguate."
        )
    return rows[0]["scheduled_date"] if rows else ""


# --- subscriptions (who's tracking what) ------------------------------------


def load_flights() -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT name, flight_iata, scheduled_date AS date, dep_country, arr_country "
            "FROM subscriptions ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def add_flight(
    name: str,
    flight_iata: str,
    date: str,
    dep_country: str = "Unknown",
    arr_country: str = "Unknown",
) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT INTO subscriptions "
            "(name, flight_iata, scheduled_date, dep_country, arr_country, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                name,
                flight_iata.upper(),
                date,
                dep_country,
                arr_country,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def remove_flight(flight_iata: str) -> bool:
    flight_iata = flight_iata.upper()
    with _db() as conn:
        cur = conn.execute(
            "DELETE FROM subscriptions WHERE flight_iata = ?", (flight_iata,)
        )
        return cur.rowcount > 0


def update_flight_countries(
    flight_iata: str, dep_country: str, arr_country: str
) -> None:
    flight_iata = flight_iata.upper()
    changed = False
    with _db() as conn:
        if dep_country != "Unknown":
            cur = conn.execute(
                "UPDATE subscriptions SET dep_country = ? "
                "WHERE flight_iata = ? AND dep_country = 'Unknown'",
                (dep_country, flight_iata),
            )
            changed = changed or cur.rowcount > 0
        if arr_country != "Unknown":
            cur = conn.execute(
                "UPDATE subscriptions SET arr_country = ? "
                "WHERE flight_iata = ? AND arr_country = 'Unknown'",
                (arr_country, flight_iata),
            )
            changed = changed or cur.rowcount > 0


# --- flights (polling bookkeeping + last-known snapshot) --------------------


def get_flight_schedule(flight_iata: str, date: str | None = None) -> dict:
    flight_iata = flight_iata.upper()
    with _db() as conn:
        resolved = _resolve_date(conn, flight_iata, date)
        row = conn.execute(
            "SELECT last_checked, done, dep_scheduled, arr_scheduled FROM flights "
            "WHERE flight_iata = ? AND scheduled_date = ?",
            (flight_iata, resolved),
        ).fetchone()
    if row is None:
        return dict(_DEFAULT_SCHEDULE_ENTRY)
    return {
        "last_checked": row["last_checked"],
        "done": bool(row["done"]),
        "dep_scheduled": row["dep_scheduled"],
        "arr_scheduled": row["arr_scheduled"],
    }


def update_flight_schedule(flight_iata: str, date: str | None = None, **fields) -> None:
    flight_iata = flight_iata.upper()
    unknown = set(fields) - set(_DEFAULT_SCHEDULE_ENTRY)
    if unknown:
        raise TypeError(f"Unknown schedule field(s): {unknown}")

    with _db() as conn:
        resolved = _resolve_date(conn, flight_iata, date)
        row = conn.execute(
            "SELECT last_checked, done, dep_scheduled, arr_scheduled FROM flights "
            "WHERE flight_iata = ? AND scheduled_date = ?",
            (flight_iata, resolved),
        ).fetchone()
        current = (
            {
                "last_checked": row["last_checked"],
                "done": bool(row["done"]),
                "dep_scheduled": row["dep_scheduled"],
                "arr_scheduled": row["arr_scheduled"],
            }
            if row
            else dict(_DEFAULT_SCHEDULE_ENTRY)
        )
        entry = {**current, **fields}
        conn.execute(
            "INSERT INTO flights (flight_iata, scheduled_date, last_checked, done, "
            "dep_scheduled, arr_scheduled) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(flight_iata, scheduled_date) DO UPDATE SET "
            "last_checked=excluded.last_checked, done=excluded.done, "
            "dep_scheduled=excluded.dep_scheduled, arr_scheduled=excluded.arr_scheduled",
            (
                flight_iata,
                resolved,
                entry["last_checked"],
                int(entry["done"]),
                entry["dep_scheduled"],
                entry["arr_scheduled"],
            ),
        )


def get_flight_state(flight_iata: str, date: str) -> dict | None:
    """The last-known key-fields snapshot for one (flight_iata, date), or
    None if it's never been checked successfully before (the "baseline not
    recorded yet" case that make check_all_flights skip alerting)."""
    flight_iata = flight_iata.upper()
    with _db() as conn:
        row = conn.execute(
            "SELECT has_snapshot, status, dep_delay, arr_delay, dep_gate, arr_gate, "
            "dep_estimated, arr_estimated FROM flights "
            "WHERE flight_iata = ? AND scheduled_date = ?",
            (flight_iata, date),
        ).fetchone()
    if row is None or not row["has_snapshot"]:
        return None
    return {k: row[k] for k in _SNAPSHOT_FIELDS}


def save_flight_state(flight_iata: str, date: str, key_fields: dict) -> None:
    flight_iata = flight_iata.upper()
    values = [key_fields.get(k) for k in _SNAPSHOT_FIELDS]
    with _db() as conn:
        conn.execute(
            "INSERT INTO flights (flight_iata, scheduled_date, has_snapshot, status, "
            "dep_delay, arr_delay, dep_gate, arr_gate, dep_estimated, arr_estimated) "
            "VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(flight_iata, scheduled_date) DO UPDATE SET "
            "has_snapshot=1, status=excluded.status, dep_delay=excluded.dep_delay, "
            "arr_delay=excluded.arr_delay, dep_gate=excluded.dep_gate, "
            "arr_gate=excluded.arr_gate, dep_estimated=excluded.dep_estimated, "
            "arr_estimated=excluded.arr_estimated",
            (flight_iata, date, *values),
        )


def load_state() -> dict:
    """Read-only convenience view: {flight_iata: last_snapshot}, flattened
    across dates. Kept only because Phase 0 tests call it directly; the
    scheduler loop itself uses get_flight_state/save_flight_state, which are
    date-scoped and don't have this view's flight_iata-collision limitation."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT flight_iata, status, dep_delay, arr_delay, dep_gate, arr_gate, "
            "dep_estimated, arr_estimated FROM flights WHERE has_snapshot = 1"
        ).fetchall()
    return {row["flight_iata"]: {k: row[k] for k in _SNAPSHOT_FIELDS} for row in rows}


# --- api_usage (monthly quota) ----------------------------------------------


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def load_usage() -> dict:
    month = _current_month()
    with _db() as conn:
        count_row = conn.execute(
            "SELECT COUNT(*) AS n FROM api_usage WHERE counted = 1 AND substr(timestamp, 1, 7) = ?",
            (month,),
        ).fetchone()
        warned_row = conn.execute(
            "SELECT warned FROM usage_warnings WHERE month = ?", (month,)
        ).fetchone()
    return {
        "month": month,
        "count": count_row["n"],
        "warned": bool(warned_row["warned"]) if warned_row else False,
    }


def increment_usage(
    provider: str = "aviationstack",
    endpoint: str = "flights",
    http_status: int | None = None,
) -> int:
    with _db() as conn:
        conn.execute(
            "INSERT INTO api_usage (provider, timestamp, endpoint, http_status, counted) "
            "VALUES (?, ?, ?, ?, 1)",
            (provider, datetime.now(timezone.utc).isoformat(), endpoint, http_status),
        )
    return load_usage()["count"]


def usage_remaining(cap: int) -> int:
    return max(0, cap - load_usage()["count"])


def mark_usage_warned() -> None:
    month = _current_month()
    with _db() as conn:
        conn.execute(
            "INSERT INTO usage_warnings (month, warned) VALUES (?, 1) "
            "ON CONFLICT(month) DO UPDATE SET warned = 1",
            (month,),
        )


# --- airports (IATA -> country cache) ---------------------------------------


def get_airport_country(iata_code: str) -> str | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT country FROM airports WHERE iata = ?", (iata_code,)
        ).fetchone()
    return row["country"] if row else None


def save_airport_country(iata_code: str, country: str) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT INTO airports (iata, country) VALUES (?, ?) "
            "ON CONFLICT(iata) DO UPDATE SET country = excluded.country",
            (iata_code, country),
        )
