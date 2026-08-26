# ARCHITECTURE.md — as of Phase 0 (pre-hardening baseline)

This describes what the code in this repo actually does today, warts included. It
is a characterization document, not a design spec — see `HARDENING_PLAN.md` and
`CLAUDE.md` for where this is going. Nothing here has been changed by Phase 0;
this file and `tests/` are the only additions.

## Modules

```
bot.py         Telegram command handlers + the periodic polling job. Entry point.
flight_api.py  Aviationstack HTTP client, response shaping, message formatting.
scheduler.py   Pure functions deciding whether a flight is "due" for a poll.
storage.py     JSON file read/write for all persistent state.
airports.py    IATA -> country name resolution, with its own JSON cache.
```

There is no package structure; everything is a flat module imported by `bot.py`.
`flight_api.py` imports `storage` (for the quota check). `bot.py` imports all four
other modules. `scheduler.py` and `airports.py` have no dependencies on each other
or on `bot.py`/`storage.py` (airports.py reads `AVIATIONSTACK_API_KEY` from env
directly, independent of `flight_api.py`).

## Data flow

1. `bot.py:main()` builds a `python-telegram-bot` `Application`, registers command
   handlers, and (if a job queue is available) schedules `check_all_flights` to run
   every `SCHEDULER_TICK_MINUTES` (default 15).
2. Each tick, `check_all_flights`:
   - Checks the monthly usage margin (see "Quota" below); if too close to the cap,
     warns once and returns without checking any flights.
   - Loads all tracked flights (`storage.load_flights()`) and the last-known
     per-field state for every flight (`storage.load_state()`).
   - For each flight, asks `scheduler.is_due()` whether it's worth spending a
     request on right now. If not due, skips it — no API call, no state touched.
   - If due, calls `flight_api.get_flight_status()` (one API request), then
     `flight_api.summarize()` to shape the response into a flat dict.
   - Updates the flight's schedule bookkeeping (`last_checked`, `dep_scheduled`,
     `arr_scheduled`, `done`) unconditionally on a successful lookup.
   - Extracts a fixed subset of fields ("key fields", see below) and compares them
     to the previously stored snapshot for that flight. If different, persists the
     new snapshot *before* sending, then sends a Telegram message — unless this is
     the very first snapshot ever recorded for that flight (baseline, silent).
   - Backfills `dep_country`/`arr_country` on the tracked-flight record if either
     is still `"Unknown"`.
3. Command handlers (`/list`, `/bycountry`, `/status`, `/add`, `/remove`,
   `/budget`, `/start`) read/write the same JSON files directly; none of them
   go through the scheduler.

## Storage: JSON file schemas

All files live in the working directory the bot is launched from and are created
on first write. There is no locking beyond an in-process `threading.Lock` (no
protection against two processes, and no atomic replace — a crash mid-`json.dump`
truncates the file).

**`flights.json`** — list of tracked flights, one entry per `/add`:
```json
[
  {
    "name": "Mom",
    "flight_iata": "RJ264",
    "date": "2026-08-05",
    "dep_country": "Jordan",
    "arr_country": "United States"
  }
]
```
`dep_country`/`arr_country` default to `"Unknown"` and are backfilled later.
No uniqueness constraint: `/add` can add the same `flight_iata` twice, producing
two independent tracked entries with (possibly) different names.

**`state.json`** — last-known "key fields" snapshot per flight, keyed by
`flight_iata` only (not by date — see "Known gaps" below):
```json
{
  "RJ264": {
    "status": "scheduled",
    "dep_delay": null,
    "arr_delay": null,
    "dep_gate": "12",
    "arr_gate": null,
    "dep_estimated": "2026-08-05T10:05:00+00:00",
    "arr_estimated": null
  }
}
```
This is the dict compared to decide whether to alert.

**`schedule.json`** — per-flight polling bookkeeping, keyed by `flight_iata`:
```json
{
  "RJ264": {
    "last_checked": "2026-08-05T09:00:00+00:00",
    "done": false,
    "dep_scheduled": "2026-08-05T10:00:00+00:00",
    "arr_scheduled": "2026-08-05T14:00:00+00:00"
  }
}
```
Missing keys default via `_DEFAULT_SCHEDULE_ENTRY` (`last_checked=None,
done=False, dep_scheduled=None, arr_scheduled=None`).

**`usage.json`** — monthly Aviationstack request counter:
```json
{"month": "2026-08", "count": 37, "warned": false}
```
`load_usage()` compares `usage["month"]` to the current UTC calendar month
(`YYYY-MM`) and resets to `{month, count: 0, warned: false}` in memory if they
differ — the reset is only written back to disk the next time something calls
`save_usage()` (e.g. via `increment_usage()` or `mark_usage_warned()`), so a
month can roll over and the on-disk file can still show the old month/count
until the next write.

**`airport_countries.json`** (managed by `airports.py`, not `storage.py`) — flat
IATA-code-to-country-name cache, e.g. `{"AMM": "Jordan"}`. Only successful
lookups (`country != "Unknown"`) are cached; unresolved codes are retried on
every call.

## Exact conditions under which an alert fires

An alert is sent from `check_all_flights` if and only if **all** of:

1. The global usage-margin gate is not tripped
   (`storage.usage_remaining(MONTHLY_REQUEST_CAP) > REQUEST_SAFETY_MARGIN`).
2. `scheduler.is_due(flight, schedule_entry, now)` is `True` for this flight
   (see scheduler rules below).
3. `flight_api.get_flight_status()` succeeds (no `BudgetExhaustedError`,
   no `FlightLookupError`).
4. The extracted key-fields dict —
   `{status, dep_delay, arr_delay, dep_gate, arr_gate, dep_estimated, arr_estimated}`
   — is **not equal** (plain dict `!=`) to the dict stored in `state.json` for
   that `flight_iata`.
5. There **was** a previous entry in `state.json` for that `flight_iata` (i.e.
   this is not the first successful lookup ever recorded for it — the first one
   only writes a silent baseline).

Notably, condition 4 is a raw dict comparison with **no null-transition
guard**: a field going from a real value to `None` (e.g. Aviationstack briefly
omitting `dep_gate`) counts as a change and fires an alert. There is also no
per-field dedupe key and no debounce — every tick that produces *any* differing
field sends exactly one message bundling the whole current summary, and if two
ticks in a row each change a different field, that's two separate messages. This
is intentional-today, not yet what `CLAUDE.md`'s invariants (2) and dedupe-by
`(flight_key, field, new_value)` require — that's Phase 3 work.

Also notable: state is persisted (`storage.save_state`) **before** the Telegram
send is attempted, so if `send_message` raises, the change is not retried on the
next tick (it's already "the known state"). This matches the *spirit* of
invariant (1) — never replay — but only at the granularity of "whole flight
snapshot", not per-field, and there is no reconciliation step if the send
actually failed.

## Scheduler rules (`scheduler.py`)

- `mark_done(summary)`: `True` if `status` (case-insensitive) is `landed` or
  `cancelled`, or if `arr_actual` is set. Once `done` is persisted to
  `schedule.json`, `is_active_window` always returns `False` for that flight —
  it is never polled again this run, even if the month rolls over.
- `is_active_window(flight, sched, now)`:
  - `False` if already marked done.
  - If `dep_scheduled` is unknown: `True` only if `now`'s UTC calendar date
    string equals `flight["date"]` (the user-supplied date), independent of
    time of day.
  - If `dep_scheduled` is known: window is
    `[dep_scheduled - PRE_WINDOW_HOURS, (arr_scheduled or dep_scheduled + 24h) + POST_WINDOW_HOURS]`.
- `tier_interval_minutes(flight, sched, now)`: inside the window, if neither
  `dep_scheduled` nor `arr_scheduled` is known yet, treat as urgent
  (`CHECK_INTERVAL_MINUTES`). Otherwise: `CHECK_INTERVAL_MINUTES` if the nearest
  of dep/arr is within `CLOSE_EVENT_HOURS`, else `FAR_TIER_MINUTES`.
- `is_due(...)`: `False` if not in the active window. `True` if never checked
  before. Otherwise `True` iff `now - last_checked >= tier_interval`.

## Quota (`flight_api.py`, `storage.py`)

- `get_flight_status` raises `BudgetExhaustedError` (before making any HTTP
  request) if `storage.usage_remaining(MONTHLY_REQUEST_CAP) <= 0`.
- Every attempted call (even ones that later fail with a 4xx/5xx or return no
  data) increments `usage.json`'s counter *before* the HTTP request is made —
  a network failure after `increment_usage()` still consumes quota.
- Separately, `check_all_flights` itself refuses to even start polling once
  `usage_remaining <= REQUEST_SAFETY_MARGIN`, holding that margin in reserve for
  manual `/status` calls, and sends a one-time (`usage["warned"]`-gated) warning
  to `TELEGRAM_CHAT_ID` when it first crosses that line.
- `airports.get_country` has its own, unrelated HTTP call to Aviationstack's
  `/v1/airports` endpoint and **does not check or increment** `usage.json` at
  all — an airport-country backfill is not counted against the monthly cap, and
  is not blocked by `BudgetExhaustedError`. This is a real gap versus the
  "quota guard is a hard gate in the provider layer" invariant, to be closed in
  Phase 2 (bundled offline airport data removes the network call entirely).

## Command handlers (`bot.py`)

- `/start`: static help text plus the caller's `chat.id`, no state read/written.
- `/list`: groups all tracked flights by `f"{dep_country} → {arr_country}"`,
  sorted by that label string, and lists `name — flight_iata on date` under each.
- `/bycountry <query>`: case-insensitive substring match against
  `dep_country` or `arr_country`.
- `/status <flight_iata>`: uppercases the code, looks up a tracked entry (for its
  `name`/`date`, purely cosmetic — falls back to the code itself and no date) and
  calls the API directly, live, **outside** the scheduler and its due-checking —
  a manual `/status` still costs one request (if budget allows) regardless of
  the flight's active window.
- `/add <name> <flight_iata> <date>`: validates the date format only (no check
  that `flight_iata` looks like a real IATA code, no dedupe against an existing
  identical entry). Tries one live lookup to resolve countries immediately;
  on `FlightLookupError` (e.g. too far in advance for the provider to have data)
  it adds the flight anyway with `"Unknown"`/`"Unknown"`, silently swallowing the
  error — the countries backfill later via the periodic job.
- `/remove <flight_iata>`: removes **all** tracked entries matching that code
  (case-insensitive), regardless of `date` or `name` — if two people are on the
  same flight number on different dates, `/remove` takes out both.
- `/budget`: reads `usage.json`, reports `count`/`MONTHLY_REQUEST_CAP` and days
  left in the calendar month (not the API's actual billing cycle, which may not
  align with the calendar month — this is a display approximation).

## Known gaps versus `CLAUDE.md`'s target invariants (not fixed in Phase 0)

- Flights are keyed by `flight_iata` alone in `state.json`/`schedule.json`, not
  `(flight_iata, date)` — two people on the same flight number on different
  dates share one schedule/state entry and will corrupt each other's tracking.
  `flights.json` itself does store `date` per entry, so `/add`/`/list`/
  `/bycountry` are fine; it's the polling/alerting side that collapses the key.
- No `chat_id` scoping anywhere — every file is implicitly global to the single
  `TELEGRAM_CHAT_ID` operator. Any chat that can reach the bot can `/add`,
  `/remove`, and read every tracked flight.
- No null-transition guard on alerts (see above).
- No per-field dedupe key, no debounce window.
- Timestamps are stored as whatever Aviationstack returns (ISO 8601 with
  offset, effectively UTC) but never explicitly normalized or rendered in a
  chosen timezone — display is just the raw ISO string.
- Airport country resolution is a live, uncached-until-hit API call sharing no
  budget accounting with the main quota.
- No structured logging, no secret redaction (tokens aren't logged today, but
  nothing enforces that going forward), no circuit breaker/backoff beyond the
  monthly-cap check, no graceful shutdown, no single-instance lock.

These gaps are the reason for Phases 1–5; this document only records that they
exist today, as a baseline for judging whether later phases actually fixed them.
