# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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
