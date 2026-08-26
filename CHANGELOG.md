# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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
