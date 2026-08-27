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
#
# chat_id is the tenant boundary (CLAUDE.md invariant #5): every one of these
# functions is scoped to a single chat_id, except the two explicitly named
# "all chats" below, which exist only for the poll loop (which polls a
# flight once regardless of how many chats track it) and are never used to
# answer a query on a specific chat's behalf.


def load_flights(chat_id: str) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT name, flight_iata, scheduled_date AS date, dep_country, arr_country "
            "FROM subscriptions WHERE chat_id = ? ORDER BY id",
            (chat_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_flight(
    chat_id: str,
    name: str,
    flight_iata: str,
    date: str,
    dep_country: str = "Unknown",
    arr_country: str = "Unknown",
) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT INTO subscriptions "
            "(chat_id, name, flight_iata, scheduled_date, dep_country, arr_country, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                name,
                flight_iata.upper(),
                date,
                dep_country,
                arr_country,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def remove_flight(chat_id: str, flight_iata: str) -> bool:
    flight_iata = flight_iata.upper()
    with _db() as conn:
        cur = conn.execute(
            "DELETE FROM subscriptions WHERE chat_id = ? AND flight_iata = ?",
            (chat_id, flight_iata),
        )
        return cur.rowcount > 0


def forget_chat(chat_id: str) -> int:
    """Deletes every subscription belonging to chat_id, plus its access/
    settings row. Does not touch the shared `flights`/`change_events` rows
    for any flight another chat still tracks -- those aren't this chat's
    data. Returns how many subscriptions were deleted."""
    with _db() as conn:
        cur = conn.execute("DELETE FROM subscriptions WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
        return cur.rowcount


def load_distinct_tracked_flights() -> list[dict]:
    """Every distinct (flight_iata, date) tracked by *any* chat -- for the
    poll loop only, which fetches a flight's status once and fans the result
    out to every chat subscribed to it (CLAUDE.md's "poll the flight once;
    fan out ... to every subscribed chat"). Never used to answer a specific
    chat's /list."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT flight_iata, scheduled_date AS date FROM subscriptions"
        ).fetchall()
    return [dict(r) for r in rows]


def get_subscribers(flight_iata: str, date: str) -> list[dict]:
    """Every chat subscribed to one (flight_iata, date), for fan-out."""
    flight_iata = flight_iata.upper()
    with _db() as conn:
        rows = conn.execute(
            "SELECT chat_id, name, dep_country, arr_country FROM subscriptions "
            "WHERE flight_iata = ? AND scheduled_date = ? ORDER BY id",
            (flight_iata, date),
        ).fetchall()
    return [dict(r) for r in rows]


def update_flight_countries(
    chat_id: str, flight_iata: str, dep_country: str, arr_country: str
) -> None:
    flight_iata = flight_iata.upper()
    changed = False
    with _db() as conn:
        if dep_country != "Unknown":
            cur = conn.execute(
                "UPDATE subscriptions SET dep_country = ? "
                "WHERE chat_id = ? AND flight_iata = ? AND dep_country = 'Unknown'",
                (dep_country, chat_id, flight_iata),
            )
            changed = changed or cur.rowcount > 0
        if arr_country != "Unknown":
            cur = conn.execute(
                "UPDATE subscriptions SET arr_country = ? "
                "WHERE chat_id = ? AND flight_iata = ? AND arr_country = 'Unknown'",
                (arr_country, chat_id, flight_iata),
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


# --- change_events (alert dedupe + crash-safe retry) ------------------------


def record_pending_change(
    flight_iata: str, date: str, field: str, old_value: object, new_value: object
) -> bool:
    """Durably record a detected, alert-worthy field change *before* any
    send is attempted (CLAUDE.md invariant #1). Returns True if a new row was
    inserted, False if an identical (flight, date, field, new_value) change
    is already pending (sent=0) -- e.g. a crash happened after this was
    recorded the first time but before it was sent, so re-detecting the same
    transition on the next poll must not create a duplicate.
    """
    flight_iata = flight_iata.upper()
    old_str = None if old_value is None else str(old_value)
    new_str = None if new_value is None else str(new_value)
    with _db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM change_events WHERE flight_iata = ? AND scheduled_date = ? "
            "AND field = ? AND new_value IS ? AND sent = 0",
            (flight_iata, date, field, new_str),
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO change_events "
            "(flight_iata, scheduled_date, field, old_value, new_value, detected_at, sent) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (
                flight_iata,
                date,
                field,
                old_str,
                new_str,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return True


def get_pending_changes(flight_iata: str, date: str) -> list[dict]:
    """All not-yet-confirmed-sent changes for one (flight_iata, date),
    oldest first -- includes anything left over from a crash on a previous
    poll, so a retry naturally bundles with whatever's new this poll."""
    flight_iata = flight_iata.upper()
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, field, old_value, new_value, detected_at FROM change_events "
            "WHERE flight_iata = ? AND scheduled_date = ? AND sent = 0 ORDER BY id",
            (flight_iata, date),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_changes_sent(change_ids: list[int]) -> None:
    if not change_ids:
        return
    with _db() as conn:
        conn.executemany(
            "UPDATE change_events SET sent = 1 WHERE id = ?", [(i,) for i in change_ids]
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


# --- chats (per-chat access status + settings) ------------------------------


def request_chat_access(chat_id: str) -> None:
    """Records a pending access request, if this chat hasn't already been
    decided (or already has a pending request) -- idempotent, so a chat
    spamming /request_access doesn't reset an existing approval/denial."""
    with _db() as conn:
        conn.execute(
            "INSERT INTO chats (chat_id, access_status, requested_at) "
            "VALUES (?, 'pending', ?) "
            "ON CONFLICT(chat_id) DO NOTHING",
            (chat_id, datetime.now(timezone.utc).isoformat()),
        )


def get_chat_access_status(chat_id: str) -> str | None:
    """None means this chat has never requested access at all (distinct from
    'pending', which means it has and is waiting)."""
    with _db() as conn:
        row = conn.execute(
            "SELECT access_status FROM chats WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return row["access_status"] if row else None


def set_chat_access_status(
    chat_id: str, status: str, decided_by: str | None = None
) -> None:
    if status not in ("pending", "approved", "denied"):
        raise ValueError(f"Invalid access status: {status!r}")
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        conn.execute(
            "INSERT INTO chats (chat_id, access_status, requested_at, decided_at, decided_by) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "access_status = excluded.access_status, decided_at = excluded.decided_at, "
            "decided_by = excluded.decided_by",
            (chat_id, status, now, now, decided_by),
        )


def get_chat_timezone(chat_id: str) -> str | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT timezone FROM chats WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return row["timezone"] if row else None


def set_chat_timezone(chat_id: str, tz_name: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        conn.execute(
            "INSERT INTO chats (chat_id, access_status, requested_at, timezone) "
            "VALUES (?, 'pending', ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET timezone = excluded.timezone",
            (chat_id, now, tz_name),
        )
