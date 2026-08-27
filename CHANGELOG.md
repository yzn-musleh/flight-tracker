# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Phase 4 — Multi-user and access control
- **Removed the global `TELEGRAM_CHAT_ID`.** Every subscription belongs to
  the `chat_id` that created it (`storage.add_flight`/`load_flights`/
  `remove_flight`/`update_flight_countries` now require it); no query can
  cross from one chat's data to another's.
- Added `access.py` and an access-control gate on every data-touching
  command: `ALLOWED_CHAT_IDS` (env var) are always-approved admin chats;
  any other chat must `/request_access`, which notifies admins, who
  `/approve <chat_id>` or `/deny <chat_id>`.
- Added `/forget` (delete this chat's own tracked flights and settings) and
  `/timezone [IANA name]` (per-chat override of the default
  `SUBSCRIBER_TIMEZONE`, validated against `zoneinfo`).
- `/remove` and `/forget` are restricted to Telegram group admins/creators
  inside group chats (private chats are exempt).
- `check_all_flights` now polls each distinct `(flight_iata, date)` once and
  fans the result out to every chat subscribed to it, rather than pushing
  every alert to one operator chat — multiple chats tracking the same real
  flight each get notified from a single provider lookup.
- Registered the command list with Telegram via `set_my_commands`
  (`Application.post_init`).
- A one-shot importer upgrade: pre-existing `flights.json` entries are
  assigned to the chat in the (still-read-for-this-purpose-only)
  `TELEGRAM_CHAT_ID` env var, which is also auto-approved, so an upgrading
  operator doesn't lose access to their own already-tracked flights.
- Migration version 4 adds `subscriptions.chat_id` and a `chats` table
  (access status + per-chat timezone).
- 20 Phase 0 tests characterized the single-tenant model this phase
  explicitly replaces (`HARDENING_PLAN.md`: *"There is no global 'the
  chat' any more"*) — left failing and marked `xfail`; see `FINDINGS.md` #6.
  New coverage (28 tests) is in `tests/test_multi_tenant.py`, covering
  cross-tenant isolation, the approval flow, `/forget`, `/timezone`, and
  group-admin restriction.
- No new runtime dependencies (`zoneinfo` is stdlib).

### Phase 3 — Correctness of alerts
- Added `change_detection.py`: pure, exhaustively-tested rules for which
  field changes are alert-worthy. Fixes the null-transition bug from the
  pre-hardening baseline (a field going non-null → null no longer fires an
  alert; see `FINDINGS.md` #5) and adds the explicit
  cancelled/diverted/landed status whitelist (alerts even from an unknown
  prior status).
- Alerts are now durably deduped and crash-safe: `change_events` (migration
  version 3 adds a `sent` column) records every alert-worthy change *before*
  any send is attempted, keyed by `(flight_iata, scheduled_date, field,
  new_value)`. An interrupted send (crash, network failure) leaves the row
  unconfirmed and it's retried on the next poll — not lost, not resent once
  confirmed. See `tests/test_alert_persistence.py` for a full
  crash-and-restart simulation.
- Multiple field changes detected in one poll (plus anything still pending
  from an earlier interrupted send) are bundled into a single message
  instead of one per field.
- Cancelled/diverted/landed get a distinct message headline instead of the
  generic "🔔 Update" framing.
- Added `timezones.py`: renders stored UTC timestamps in both the relevant
  airport's local timezone (from Phase 2's bundled dataset) and a
  subscriber timezone (`SUBSCRIBER_TIMEZONE` env var, default UTC — a
  global stand-in for the per-chat setting Phase 4 is expected to add).
  Wired into both the new alert messages and `/status`'s
  `flight_api.format_message()`.
- One Phase 0 test (`test_bot_alerts.py::test_alert_fires_on_value_to_null_transition`)
  characterized the null-transition bug and explicitly anticipated this fix
  in its own docstring; left failing and marked `xfail` per `CLAUDE.md`'s
  rule against editing a Phase 0 test regardless — see `FINDINGS.md` #5.
- No new runtime dependencies (`zoneinfo` is stdlib since Python 3.9).

### Phase 2 — Provider abstraction + offline airport data
- Added a `providers/` package: `FlightProvider` Protocol, `QuotaPolicy`,
  `FlightSnapshot` (`providers/base.py`); `AviationstackProvider`, a thin
  adapter over the unchanged `flight_api.py` (`providers/aviationstack.py`);
  `FakeProvider` for tests, driven by a queue of canned
  snapshots/exceptions per flight code (`providers/fake.py`); provider
  selection via the `FLIGHT_PROVIDER` env var, default `aviationstack`
  (`providers/__init__.py`). `bot.py` now goes through `provider.get_flight()`
  everywhere it used to call `flight_api.get_flight_status()` +
  `flight_api.summarize()` as two separate steps — behavior-preserving (same
  underlying calls, same exceptions), verified by the full existing test
  suite passing unmodified.
- Bundled an offline airport dataset (`static/airports.csv`, ODbL-licensed
  derivative of the OpenFlights Airport Database, 6,072 airports with a
  valid IATA code — see `static/AIRPORTS_LICENSE.md`). `airports.py` no
  longer makes any network call, needs no API key, and has zero quota impact.
  Dropped the Phase 1 `airports` SQLite table (now unused) via a new
  migration (version 2) rather than editing the already-applied migration 1.
- Added `docs/providers.md`: a researched comparison of AeroDataBox,
  FlightAware AeroAPI, Aviation Edge, and OpenSky against live vendor
  documentation (checked 2026-08-27), with a recommendation (AeroDataBox, if
  a switch ever happens) and an explicit list of what could not be verified
  from live sources. Aviationstack remains the default provider in code, per
  this phase's scope.
- Six Phase 0 tests (`test_airports.py`, five of its original six) and no
  Phase 1 tests characterized network/cache behavior this phase deliberately
  removed; left failing and marked `xfail` per `CLAUDE.md`'s rule against
  editing a Phase 0 test — see `FINDINGS.md` #4. New coverage lives in
  `tests/test_airports_offline.py` and `tests/test_providers.py`.
- No new runtime dependencies (the `providers/` package uses only stdlib
  typing/dataclasses; `static/airports.csv` is a plain data file read with
  the stdlib `csv` module).

### Phase 1 — Storage: JSON → SQLite
- Replaced the five flat JSON files with a single SQLite database
  (`flights.db`, WAL mode) behind a repository-style facade in the new
  `storage/` package (`storage/__init__.py`, `storage/migrations.py`,
  `storage/importer.py`). Public function names/signatures preserved from the
  old `storage.py` wherever behavior didn't need to change.
- **Fixed a real bug**: flights are now keyed by `(flight_iata, scheduled_date)`
  instead of `flight_iata` alone, so two people on the same flight number on
  different dates no longer collide in the same schedule/state row.
- **Fixed a real bug**: monthly usage is now a query-based count over an
  append-only `api_usage` event log instead of a mutable counter blob, so
  there's no window after a month rollover where the on-disk count is stale.
- Added a one-shot importer that migrates any pre-existing JSON files into the
  new database on first run and renames them to `*.json.imported`.
- Moved `airports.py`'s IATA→country cache from its own JSON file into the
  same SQLite database (its `airports` table); no change to its live-lookup
  business logic (still calls Aviationstack's `/v1/airports`, still caches
  only successful resolutions) — that live call is removed entirely in
  Phase 2.
- Added 25 new tests (`tests/test_storage_repository.py`,
  `tests/test_importer.py`) covering migrations, the composite-key
  convenience/ambiguity behavior, the query-based usage counter, the airports
  cache table, and the importer (including its data migration and the
  faithful-not-worsened handling of already-ambiguous legacy data).
- Three Phase 0 tests characterized JSON-file-specific implementation details
  that no longer apply; left failing and marked `xfail` centrally in
  `tests/conftest.py` per `CLAUDE.md`'s rule against editing a Phase 0 test —
  see `FINDINGS.md`.

### Phase 0 — Safety net
- Added `ARCHITECTURE.md` documenting the current (pre-hardening) system: module
  layout, JSON file schemas, exact alert-firing conditions, and known gaps versus
  `CLAUDE.md`'s target invariants.
- Added a `pytest` characterization test suite (`tests/`, 67 tests) covering
  storage, scheduler tiering/windowing, the Aviationstack client, airport-country
  caching, all Telegram command handlers, and the periodic polling job's
  change-detection/alerting behavior — including two tests that document known
  bugs on purpose (null-transition false alerts, no date-scoping on `/remove`).
- Added `.gitignore` (`.env`, all `*.json` state files, venv/cache dirs).
- No production code changed.
