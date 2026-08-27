# ARCHITECTURE.md

Describes what the code in this repo actually does, kept up to date at the end of
each hardening phase. Originally written in Phase 0 as a pure characterization of
the pre-hardening baseline (warts included); updated in Phase 1 to reflect the
SQLite storage rewrite. See `HARDENING_PLAN.md` and `CLAUDE.md` for where this is
still going, and `CHANGELOG.md`/`PROGRESS.md` for the phase-by-phase history.

## Update history

- **Phase 1**: storage moved from five flat JSON files to a single SQLite
  database (`flights.db`, WAL mode) behind a repository-style facade in the
  `storage/` package. Flights are now keyed by `(flight_iata, scheduled_date)`
  instead of `flight_iata` alone, closing the two-people-same-flight-number
  collision gap called out below. `airports.py`'s cache moved from its own
  JSON file into the same database. A one-shot importer
  (`storage/importer.py`) migrates any pre-existing JSON files on first run
  and renames them to `*.json.imported`. The sections below describing JSON
  file schemas are Phase-0-era history, kept for context; see "Storage:
  SQLite schema (Phase 1+)" for the current shape.
- **Phase 2**: added a `providers/` package (`FlightProvider` Protocol,
  `QuotaPolicy`, `FlightSnapshot`) with `AviationstackProvider` (a thin
  adapter over the unchanged `flight_api.py`) and `FakeProvider`, selected by
  the `FLIGHT_PROVIDER` env var (default `aviationstack`). `bot.py` now calls
  `provider.get_flight()` instead of `flight_api.get_flight_status()` +
  `flight_api.summarize()` directly. `airports.py` no longer makes any
  network call at all: country/timezone resolution now reads a bundled,
  offline dataset (`static/airports.csv`, a filtered ODbL-licensed derivative
  of the OpenFlights Airport Database — see `static/AIRPORTS_LICENSE.md`).
  The Phase 1 `airports` SQLite table was dropped (migration version 2) since
  it's no longer needed. See `docs/providers.md` for the researched
  comparison of alternative providers and a recommendation — Aviationstack
  remains the default in code per this phase's explicit scope.
- **Phase 3**: rewrote change detection (`change_detection.py`, new) to
  enforce the null-transition guard and the cancelled/diverted/landed status
  whitelist, fixing the bug documented in `FINDINGS.md` #5. Alerts are now
  deduped and crash-safe via `change_events` (migration version 3 adds a
  `sent` column): every detected change is durably recorded before any send
  is attempted, and an unconfirmed (`sent=0`) row from an interrupted send is
  retried on the next poll rather than lost or endlessly re-detected. Field
  changes within one poll are bundled into a single message. Added
  `timezones.py` for dual-timezone rendering (airport-local +
  `SUBSCRIBER_TIMEZONE`, a global stand-in for the per-chat setting Phase 4
  is expected to add) in both the alert text and `/status`'s
  `flight_api.format_message()`.
- **Phase 4**: removed the global `TELEGRAM_CHAT_ID` entirely.
  `storage.add_flight`/`load_flights`/`remove_flight`/`update_flight_countries`
  now require `chat_id` (migration version 4 adds the column plus a `chats`
  table for access status and per-chat timezone). New `access.py` module:
  `ALLOWED_CHAT_IDS` (env var) are always-approved admin chats; any other
  chat must `/request_access`, which notifies admins, who `/approve` or
  `/deny` it. Every data-touching command is gated on approval
  (`bot._require_access`). `check_all_flights` now polls each distinct
  `(flight_iata, date)` once (`storage.load_distinct_tracked_flights`) and
  fans the result out to every chat subscribed to it
  (`storage.get_subscribers`) — CLAUDE.md's "poll the flight once; fan out
  ... to every subscribed chat", satisfied for both country-backfill and
  alerting. Added `/forget` (delete a chat's own data), `/timezone` (per-chat
  override of `SUBSCRIBER_TIMEZONE`), and admin-only restriction of
  `/remove`/`/forget` inside group chats (`bot._is_chat_admin`, real Telegram
  chat-admin status — private chats are exempt). Registered the command list
  via `set_my_commands` in an `Application.post_init` hook.

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

## Storage: SQLite schema (Phase 1+, current)

One file, `flights.db` (path configurable via `DB_PATH`), opened in WAL mode.
Schema is applied via versioned migrations in `storage/migrations.py`
(idempotent — safe to run on every connection). Access goes through a flat
function-style facade in `storage/__init__.py` rather than the tables
directly, so `bot.py`/`flight_api.py`/`airports.py` call e.g.
`storage.load_flights()` exactly as before Phase 1.

- **`subscriptions`**: one row per `/add` (replaces `flights.json`). Columns:
  `id, chat_id, name, flight_iata, scheduled_date, dep_country, arr_country,
  created_at` (`chat_id` added Phase 4 — see below). No uniqueness
  constraint — same behavior as before, duplicate adds allowed (even by the
  same chat).
- **`chats`** (Phase 4): one row per chat that has ever `/request_access`ed
  or set a setting. Columns: `chat_id, access_status ('pending'|'approved'|
  'denied'), timezone, requested_at, decided_at, decided_by`. A chat in
  `ALLOWED_CHAT_IDS` (env var) is always treated as approved regardless of
  what's in this table — see `access.py`.
- **`flights`**: one row per `(flight_iata, scheduled_date)` — **primary key is
  composite**, replacing `state.json` + `schedule.json`, both of which used to
  be keyed by `flight_iata` alone (the collision bug in "Known gaps" below).
  Columns: polling bookkeeping (`last_checked, done, dep_scheduled,
  arr_scheduled`) plus the last-known "key fields" snapshot used for change
  detection (`status, dep_delay, arr_delay, dep_gate, arr_gate, dep_estimated,
  arr_estimated`) and a `has_snapshot` flag distinguishing "never checked" from
  "checked and every field happened to be null".
- **`change_events`**: durable dedupe/retry record for alerts, plus an
  incidental audit trail (`flight_iata, scheduled_date, field, old_value,
  new_value, detected_at, sent`). Added empty in Phase 1's schema; Phase 3
  is the code that actually writes and reads it — see "Crash-safe dedupe
  and retry" below.
- **`api_usage`**: append-only request log (`provider, timestamp, endpoint,
  http_status, counted`), matching `CLAUDE.md`'s target schema exactly.
  Replaces the old mutable `usage.json` counter. `load_usage()`'s `count` is
  computed with `COUNT(*) WHERE substr(timestamp,1,7) = this_month` — always
  correct instantly, no on-disk staleness window (see `FINDINGS.md` #1 for the
  bug this incidentally fixed).
- **`usage_warnings`**: `(month PRIMARY KEY, warned)` — the "already warned
  this month" flag, split out since it doesn't fit `api_usage`'s
  one-row-per-request shape.
- **`airports`**: `(iata PRIMARY KEY, country)`. Replaces
  `airport_countries.json`; same cache-only-on-success semantics as before.

**Composite-key convenience/ambiguity rule**: `get_flight_schedule`,
`update_flight_schedule`, and `get_flight_schedule`'s callers may omit `date`.
If exactly one row exists for that `flight_iata`, it's used (this keeps
existing single-flight call sites — a bare `/status`, most tests — working
unchanged). If more than one date is tracked for that flight number, omitting
`date` raises `ValueError` rather than silently guessing. `bot.py`'s polling
loop always passes `date` explicitly, so it never depends on this fallback.
`storage.load_state()` still exists as a **read-only convenience view**
(`{flight_iata: last_snapshot}`, flattened across dates, last-write-wins on a
genuine collision) purely because Phase 0 tests call it directly — the actual
polling loop uses the date-scoped `get_flight_state`/`save_flight_state`.

**One-shot importer** (`storage/importer.py`, invoked from `bot.py:main()` on
every startup, effectively no-op after the first): if any of the five old
JSON files are found, imports their contents into the tables above, then
renames each to `<name>.json.imported`. Where `state.json`/`schedule.json`
entries can't be matched to exactly one `flights.json` subscription for that
flight code (i.e. the data was *already* ambiguous under the old scheme), they
import into a `scheduled_date = ""` sentinel row rather than guessing — a
faithful migration of already-ambiguous data, not a new data-loss risk.

## Provider abstraction (Phase 2, current)

`providers/base.py` defines the `FlightProvider` Protocol
(`get_flight(flight_iata, date=None) -> FlightSnapshot`, plus declared
`quota: QuotaPolicy` and `supports_push: bool`), `providers/aviationstack.py`
implements it by wrapping `flight_api.py` unchanged (same wire format, same
hard quota gate — the gate already lived inside `flight_api.get_flight_status`
before this Protocol existed, satisfying `CLAUDE.md` invariant #3), and
`providers/fake.py` implements it for tests via a queue of canned
snapshots/exceptions per flight code. `providers/__init__.get_provider()`
selects the implementation via the `FLIGHT_PROVIDER` env var (default
`aviationstack`); `bot.py` holds one provider instance at module scope and
calls `provider.get_flight(...)` everywhere it used to call
`flight_api.get_flight_status()` + `flight_api.summarize()` as two steps.
Exceptions (`flight_api.FlightLookupError`, `flight_api.BudgetExhaustedError`)
are still defined in `flight_api.py` and propagate through the provider layer
unchanged — see `providers/base.py`'s docstring for why they weren't
duplicated as provider-specific types. See `docs/providers.md` for the
Phase 2 research comparing AeroDataBox, FlightAware AeroAPI, Aviation Edge,
and OpenSky against this Protocol, with a recommendation (AeroDataBox, if a
switch happens) — Aviationstack stays the default in code for now.

## Airport data (Phase 2, current)

`airports.py` resolves IATA → country/timezone/name entirely from
`static/airports.csv` (6,072 airports with a valid IATA code, filtered from
the ~7,700-row OpenFlights Airport Database — see
`static/AIRPORTS_LICENSE.md` for license/provenance), loaded once into an
in-memory dict on first use. No network call, no API key, no quota impact,
ever. This replaced both the original live Aviationstack `/v1/airports`
lookup (Phase 0 baseline) and its Phase 1 SQLite cache table (dropped via
migration version 2) in one step, per `HARDENING_PLAN.md`'s explicit Phase 2
instruction to bundle offline data instead of caching a live lookup.

## Storage: original JSON file schemas (Phase 0 history, superseded above)

These files no longer exist once a bot has started once under Phase 1+ (the
importer renames them to `*.json.imported`); this section is kept for
historical context since it explains what the importer reads. All files lived
in the working directory the bot was launched from and were created on first
write. There was no locking beyond an in-process `threading.Lock` (no
protection against two processes, and no atomic replace — a crash mid-`json.dump`
truncated the file).

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

## Exact conditions under which an alert fires (Phase 3+, current)

An alert is sent from `check_all_flights` if and only if **all** of:

1. The global usage-margin gate is not tripped
   (`storage.usage_remaining(MONTHLY_REQUEST_CAP) > REQUEST_SAFETY_MARGIN`).
2. `scheduler.is_due(flight, schedule_entry, now)` is `True` for this flight
   (see scheduler rules below).
3. `provider.get_flight()` succeeds (no `BudgetExhaustedError`, no
   `FlightLookupError`).
4. This is not the very first successful lookup ever recorded for this
   `(flight_iata, date)` (`storage.get_flight_state(...)` is not `None`) —
   that case only writes a silent baseline, same as before Phase 3.
5. `change_detection.detect_changes(previous, current)` returns at least one
   `FieldChange` for at least one of `{status, dep_delay, arr_delay, dep_gate,
   arr_gate, dep_estimated, arr_estimated}` — see the rules below — **or**
   there's a leftover unsent row in `change_events` from a previous poll that
   crashed before its send completed (see "Crash-safe dedupe and retry"
   below). Either way, `storage.get_pending_changes()` returning a non-empty
   list is what actually triggers the send.

`change_detection.detect_changes()`'s per-field rule (`change_detection.py`,
CLAUDE.md invariant #2): a field only counts as alert-worthy if it goes from
a non-null value to a *different* non-null value, **or** — the one explicit
exception — the `status` field's new value is in
`change_detection.ALWAYS_ALERT_STATUSES` (`cancelled`, `diverted`, `landed`),
in which case it alerts even coming from `None` (a flight whose very first
successful check already shows it cancelled must still say so). A value
going non-null → `None`, or `None` → an ordinary (non-terminal) value, is
*not* alert-worthy either way — this is the null-transition bug from the
pre-Phase-3 baseline, now fixed (see `FINDINGS.md` #5). One consequence
worth knowing: a gate being assigned for the first time (`None` → `"12"`)
does **not** alert under this rule, by the same invariant that excludes a
gate disappearing.

All changes detected across all fields in one poll are bundled into a single
message (`change_detection.format_alert_message`) rather than one message
per field — this is the "rapid successive changes... debounced into one
message" requirement, implemented as "everything detected in one poll (plus
anything still pending from before) is one send", which is exact and
sufficient given `SCHEDULER_TICK_MINUTES`/`CHECK_INTERVAL_MINUTES` are
always far more than 60 seconds apart in practice — see `PROGRESS.md`'s
Phase 3 entry for why a true wall-clock debounce timer wasn't built.
Cancelled/diverted/landed get a distinct headline instead of the generic
"🔔 Update" framing (CLAUDE.md: terminal states get their own copy).

## Crash-safe dedupe and retry (`change_events` table)

Before any send is attempted, every detected `FieldChange` is written to
`change_events` with `sent=0` (`storage.record_pending_change`), keyed by
`(flight_iata, scheduled_date, field, new_value)` — CLAUDE.md invariant #1's
literal dedupe key. `storage.get_flight_state`'s snapshot is updated
immediately after, independent of whether the send below succeeds. Then:

- All currently-`sent=0` rows for this flight (not just ones from this poll)
  are fetched and sent as one message.
- On success, they're marked `sent=1` (`storage.mark_changes_sent`) —
  confirmed delivered, never resent.
- If the send raises (network failure, or the process crashes/restarts
  entirely before this line runs), the rows stay `sent=0`. Because the
  snapshot was already updated to the new values, a plain re-diff on the
  next poll would find *no new change* — the pending-changes check runs
  **unconditionally**, not only when something new changed, specifically so
  this leftover row still gets retried. See
  `tests/test_alert_persistence.py::test_crash_before_send_completes_is_retried_next_poll_not_lost_or_duplicated`
  for this exact sequence exercised end-to-end.

This is the "recorded as sent before the send is attempted, with
reconciliation after" invariant, implemented without a separate background
retry job — reconciliation piggybacks on the next regular poll.

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

Every command below except `/start` and `/request_access` first calls
`_require_access(update)`, which replies with a rejection (and does nothing
else) unless the calling chat is approved — see "Access control" below.

- `/start`: static help text plus the caller's `chat.id`, no state read/written,
  no access check (a chat needs to see this before it can even
  `/request_access`).
- `/list`: groups **this chat's own** tracked flights
  (`storage.load_flights(chat_id)`) by `f"{dep_country} → {arr_country}"`,
  sorted by that label string, and lists `name — flight_iata on date` under
  each. Never sees another chat's flights.
- `/bycountry <query>`: case-insensitive substring match against
  `dep_country` or `arr_country`, scoped to this chat.
- `/status <flight_iata>`: uppercases the code, looks up a tracked entry
  *among this chat's own* (for its `name`/`date`, purely cosmetic — falls
  back to the code itself and no date) and calls the provider directly,
  live, **outside** the scheduler and its due-checking — a manual `/status`
  still costs one request (if budget allows) regardless of the flight's
  active window. Renders times in this chat's timezone (`/timezone`).
- `/add <name> <flight_iata> <date>`: validates the date format only (no check
  that `flight_iata` looks like a real IATA code, no dedupe against an existing
  identical entry, even from the same chat). Tries one live lookup to resolve
  countries immediately; on `FlightLookupError` (e.g. too far in advance for
  the provider to have data) it adds the flight anyway with
  `"Unknown"`/`"Unknown"`, silently swallowing the error — the countries
  backfill later via the periodic job. The new subscription belongs to the
  calling chat.
- `/remove <flight_iata>`: removes **all of this chat's own** tracked entries
  matching that code (case-insensitive), regardless of `date` or `name` — if
  two people *in the same chat* are tracking the same flight number on
  different dates, `/remove` takes out both of that chat's entries, but never
  another chat's. In a group chat, restricted to Telegram admins/creators
  (`_is_chat_admin`); private chats are exempt (the single user already
  controls their own chat).
- `/forget`: deletes every subscription belonging to this chat plus its
  `chats` row (access status, timezone) — `storage.forget_chat`. Same
  group-admin restriction as `/remove`. Never touches another chat's data or
  another chat's shared `flights`/`change_events` rows for a flight this
  chat happens to also track.
- `/timezone [IANA name]`: with no argument, shows the current effective
  timezone (this chat's override, or the `SUBSCRIBER_TIMEZONE` default).
  With an argument, validates it's a real IANA zone (`zoneinfo.ZoneInfo`)
  before storing it as this chat's override.
- `/request_access`: idempotent — a chat that's already approved or denied
  gets told so and nothing changes; otherwise records a pending request and
  messages every `ALLOWED_CHAT_IDS` admin with `/approve <chat_id>`/
  `/deny <chat_id>` instructions. No access check (this is how access is
  requested in the first place).
- `/approve <chat_id>`, `/deny <chat_id>`: admin-only (`access.is_admin`,
  i.e. the calling chat is in `ALLOWED_CHAT_IDS`) — not gated by
  `_require_access` at all, since an admin chat is always approved anyway.
  Records the decision and best-effort-notifies the target chat.
- `/budget`: reads `api_usage`, reports `count`/`MONTHLY_REQUEST_CAP` and days
  left in the calendar month (not the API's actual billing cycle, which may not
  align with the calendar month — this is a display approximation). Global,
  not per-chat — the quota is shared across every chat using this bot
  instance.

## Access control (`access.py`, Phase 4)

- `ALLOWED_CHAT_IDS` (env var, comma-separated) are the operator's admin
  chat(s) — always approved, and the only chats that can `/approve`/`/deny`.
- Any other chat starts with no `chats` row at all (`get_chat_access_status`
  returns `None`, distinct from `'pending'`). `/request_access` moves it to
  `'pending'` and notifies admins; `/approve`/`/deny` moves it to
  `'approved'`/`'denied'`.
- `_require_access` (in `bot.py`, not `access.py` — it needs
  `update.message.reply_text`) is the single gate every data-touching
  handler calls first. A `'denied'` chat gets a specific message rather than
  the generic "ask for access" one; asking again after denial doesn't reset
  anything (`access.request_access` is idempotent once decided).
- **Known limitation**: fan-out alerting (`check_all_flights`) does not
  re-check a subscribed chat's current access status before sending — only
  the commands that *create* a subscription are gated. A chat denied or
  `/forget`-removed after subscribing simply has no subscription rows left
  to fan out to (`/forget`) or was never approved to create one in the first
  place (`/add`), so this is believed to not be exploitable in practice, but
  it wasn't explicitly re-verified per-poll. See `PROGRESS.md`'s Phase 4
  entry.

## Known gaps versus `CLAUDE.md`'s target invariants

- ~~Flights are keyed by `flight_iata` alone in `state.json`/`schedule.json`~~
  **Fixed in Phase 1**: the `flights` table's primary key is
  `(flight_iata, scheduled_date)`, so two people on the same flight number on
  different dates now get independent rows.
- ~~No `chat_id` scoping anywhere~~ **Fixed in Phase 4**:
  `subscriptions.chat_id` is required and enforced by every storage function;
  an access-control gate (`access.py`) blocks unapproved chats from any
  data-touching command entirely.
- ~~No null-transition guard on alerts~~ **Fixed in Phase 3**:
  `change_detection.detect_changes()` enforces it, plus the
  cancelled/diverted/landed status whitelist.
- ~~No per-field dedupe key, no debounce window~~ **Fixed in Phase 3**:
  deduped by `(flight_iata, scheduled_date, field, new_value)` via
  `change_events`, crash-safe (see "Crash-safe dedupe and retry"); changes
  within one poll are bundled into one message.
- ~~Timestamps are... never explicitly normalized or rendered in a chosen
  timezone~~ **Partially fixed in Phase 3**: `timezones.py` renders stored
  UTC timestamps in the airport's local timezone and a subscriber timezone,
  in both the alert text and `/status`. Storage/comparison were always UTC
  already (Aviationstack returns offset-aware ISO 8601). **Fully fixed in
  Phase 4**: `/timezone` sets a per-chat override (`chats.timezone`),
  falling back to `SUBSCRIBER_TIMEZONE` only for chats that haven't set one.
- ~~Airport country resolution is a live, uncached-until-hit API call sharing
  no budget accounting with the main quota~~ **Fixed in Phase 2**: resolved
  from a bundled offline dataset, zero network calls, zero quota impact.
- No structured logging, no secret redaction (tokens aren't logged today, but
  nothing enforces that going forward), no circuit breaker/backoff beyond the
  monthly-cap check, no graceful shutdown, no single-instance lock.

These gaps are the reason for Phases 1–5; this document only records that they
exist today, as a baseline for judging whether later phases actually fixed them.
