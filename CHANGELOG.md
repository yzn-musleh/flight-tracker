# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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
