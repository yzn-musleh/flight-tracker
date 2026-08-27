# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Phase 7 — Publishable
- **Scanned the full git history for committed secrets or personal data
  before making any other change**, per this phase's explicit instruction.
  No real API keys, tokens, or `.env` files were ever committed. Two
  pre-existing (present since the very first commit, not introduced during
  hardening) items worth the repo owner's attention before making the repo
  public: a first name ("Uncle_Khalid") used as an example in the original
  README, and a real-looking domain in `HARDENING_PLAN.md`'s own Phase 6
  note. Reported, not changed — see `HANDOFF.md`.
- **Achieved genuine `mypy --strict` compliance across the entire
  codebase** (not just `bot.py`'s previously-known Optional-access gap —
  every module had missing generic type arguments, missing return-type
  annotations, or similar). Zero behavior change throughout, verified by
  the full test suite passing unmodified at every step.
- Added `LICENSE` (MIT; `static/airports.csv` called out as separately
  ODbL-licensed), `CONTRIBUTING.md`, `.github/ISSUE_TEMPLATE/`,
  `.github/PULL_REQUEST_TEMPLATE.md`.
- Added `.github/workflows/ci.yml`: `ruff check`, `ruff format --check`,
  `mypy --strict`, and `pytest` on every PR and push to `main`, plus a
  separate job that builds the Docker image and runs the same non-root/
  import/healthcheck smoke checks verified manually in Phase 6 — verified
  by actually running the exact commands the workflow uses, not just
  writing YAML and assuming it works.
- Added `types-requests` as a dev dependency (the one third-party package
  needing stubs for a clean strict run with no blanket
  `--ignore-missing-imports`); set `strict = true` in `pyproject.toml`'s
  `[tool.mypy]` now that it's actually true.
- Rewrote `README.md` for a stranger: what it does, quickstart, a full
  configuration reference table, a troubleshooting section, and a pointer
  to the provider comparison — screenshots deliberately omitted with an
  explanation (see the README's own placeholder comment) rather than
  fabricated.
- No new Phase 0 test breakage — this phase's changes were type
  annotations, docs, and CI/packaging config, not behavior changes.

### Phase 6 — Packaging and deployment
- Added `pyproject.toml`: project metadata, a `dev` extra
  (pytest/pytest-asyncio/ruff/mypy/time-machine, pinned to the exact
  versions this project is developed and tested against), and
  `[tool.pytest.ini_options]` (`pytest.ini` removed, superseded),
  `[tool.ruff]`, `[tool.mypy]`. `requirements.txt` is kept alongside for
  Docker's build step.
- Setting an explicit `target-version = "py312"` for ruff surfaced 16
  legitimate modernizations ruff hadn't been suggesting without a
  configured target version — mainly `datetime.UTC` instead of
  `datetime.timezone.utc`, and dropping a `.replace("Z", "+00:00")`
  workaround that `datetime.fromisoformat` has handled natively since
  Python 3.11. Fixed all of them (verified behavior-identical) rather than
  leaving newly-surfaced findings unaddressed just because they weren't the
  point of adding the config.
- Added a multi-stage `Dockerfile`: builds dependencies in one stage, runs
  as a non-root `flighttracker` user (uid 1000) in the final image, with a
  `HEALTHCHECK` running the new `healthcheck.py`. Added `.dockerignore`
  (never bakes `.env`/`*.db`/`*.lock` into an image). Added
  `docker-compose.yml` with a named volume for the SQLite database and
  lock file (`DB_PATH`/`LOCK_PATH` point at `/data` in the image) and
  `.env` mounted via `env_file`. **Actually built and ran the image in this
  session** — verified the non-root user, a clean `bot.py` import, the
  healthcheck script's pass/fail behavior, and a real SQLite write to the
  mounted `/data` path as that non-root user, not just written and assumed
  correct.
- Added `deploy/flight-tracker.service` (systemd unit: dedicated non-root
  user, `Restart=on-failure`, light sandboxing via `ProtectSystem=strict`)
  and `deploy/README.md` walking through non-Docker setup, per
  `HARDENING_PLAN.md`'s "systemd unit as an alternative for non-Docker
  users."
- Added Telegram webhook mode as an alternative to long polling, selected
  by `WEBHOOK_MODE`/`WEBHOOK_URL`/`WEBHOOK_PATH`/`WEBHOOK_LISTEN`/
  `WEBHOOK_PORT`. The selection logic (`bot._webhook_config()`) is a pure
  function independent of actually starting a server, so it's fully unit
  tested (`tests/test_webhook_config.py`) without spinning up real HTTP.
- No Phase 0 tests affected this phase — no xfails added.
- No new runtime dependencies.

### Phase 5 — Resilience and the scheduler
- Replaced recompute-from-`last_checked` scheduling with a persisted
  `next_poll_at` per flight (migration version 5): fixed at check-time using
  the tier that applies then, so a restart resumes from an explicit stored
  fact rather than a value that could drift depending on when something
  asks "is it due yet".
- Added `resilience.py`: a per-provider `CircuitBreaker`
  (closed/open/half-open) and `retry_with_backoff` (exponential backoff with
  full jitter, injectable sleep/rand for fast deterministic tests), wired
  into `flight_api.get_flight_status` for HTTP 429/5xx. Fixed a real
  pre-existing gap along the way: a non-429 4xx used to raise an uncaught
  `requests.HTTPError` that would crash the whole poll cycle; it now raises
  `FlightLookupError`, handled the same as any other lookup failure.
- Added `resilience.send_with_retry`, handling Telegram's `RetryAfter` by
  waiting exactly as long as asked before retrying, wired into every
  `send_message` call in `bot.py`.
- Added `singleton.py`: a PID-file single-instance lock so a second copy of
  the bot can't run against the same token/database, with a clear error
  instead of a confusing Telegram 409.
- Added `logging_config.py`: JSON structured logging with secret redaction
  (tokens are stripped from the fully-rendered message and exception
  tracebacks, not just raw log args) and a correlation id per poll cycle.
- Verified — rather than reimplemented — that `python-telegram-bot`'s
  `Application.run_polling()` already installs SIGINT/SIGTERM/SIGABRT
  handlers and drains gracefully by default on non-Windows platforms
  (confirmed from the installed library's own docstring).
- 3 Phase 0 tests characterized the old last-checked-based scheduling
  algorithm and `get_flight_schedule()`'s exact pre-`next_poll_at` dict
  shape; left failing and marked `xfail` — see `FINDINGS.md` #7. New
  coverage is in `tests/test_scheduler_next_poll_at.py`,
  `tests/test_resilience.py`, `tests/test_flight_api_resilience.py`,
  `tests/test_singleton.py`, and `tests/test_logging_config.py`.
- No new runtime dependencies (`asyncio`/`random`/`time`/`dataclasses` are
  stdlib; the single-instance lock is a plain PID file, not a new package).

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
