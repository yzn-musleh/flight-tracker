# Progress Log

## Phase 2 — Provider abstraction + offline airport data

**What I did**
- Branched `harden/phase-2-providers` from Phase 1's tip.
- Added `providers/` (Protocol, Aviationstack adapter, FakeProvider,
  selection factory) and wired `bot.py` to call `provider.get_flight()`
  instead of `flight_api.get_flight_status()` + `flight_api.summarize()` at
  all three call sites (`status`, `add_flight`, `check_all_flights`).
- Downloaded the real OpenFlights Airport Database (`data/airports.dat`,
  ~7,700 rows, fetched directly from the GitHub-hosted canonical source),
  filtered it to the 6,072 rows with a valid 3-letter IATA code and the
  4 columns this project needs (iata, name, country, tz), and bundled the
  result as `static/airports.csv`, with `static/AIRPORTS_LICENSE.md`
  documenting its ODbL license and exactly what transformation was applied
  (required by ODbL §4.2/§4.4 since filtering constitutes a Derivative
  Database). Verified real airports resolve correctly (spot-checked AMM,
  JFK) before wiring `airports.py` to use it.
- Rewrote `airports.py` to resolve country/timezone/name entirely from that
  bundled file — no network, no API key, no quota impact.
- Added migration version 2 (`DROP TABLE airports`) to retire the Phase 1
  SQLite cache table, now unused.
- Researched AeroDataBox, FlightAware AeroAPI, Aviation Edge, and OpenSky
  against their own live documentation (via `WebFetch`/`WebSearch`, checked
  2026-08-27) and wrote `docs/providers.md` with a comparison table and a
  recommendation. Kept Aviationstack as the default provider in code, per
  this phase's explicit scope note.
- Updated `ARCHITECTURE.md`/`CHANGELOG.md` and added
  `tests/test_providers.py`, `tests/test_airports_offline.py`.

**What I decided and why**
- **`get_flight()` returns a normalized `FlightSnapshot`, not the raw
  provider payload.** This is what makes "adding a provider means adding one
  file" actually true — if the Protocol returned each provider's raw wire
  format, `bot.py` would need provider-specific parsing again. The existing
  `flight_api.get_flight_status()` (raw payload) and `flight_api.summarize()`
  (raw → normalized) are both left completely untouched and still directly
  tested by Phase 0's `test_flight_api.py`; `AviationstackProvider.get_flight()`
  is a thin two-line composition of both, not a reimplementation. I verified
  this composition is transparent to every existing test by checking that
  `providers/aviationstack.py` calls `flight_api.get_flight_status(...)` via
  attribute access on the shared `flight_api` module object (not a
  from-import), so a test's `monkeypatch.setattr(bot.flight_api,
  "get_flight_status", ...)` still reaches it — confirmed by the full suite
  passing with zero new xfails from this change.
- **Exceptions stay in `flight_api.py`, not duplicated per-provider.** Every
  provider that will plausibly exist needs the same two failure modes
  (not found, quota exhausted); giving each provider its own exception types
  would just push provider-awareness back into `bot.py`'s except clauses,
  defeating the point of the Protocol. Documented this reasoning directly in
  `providers/base.py`'s docstring since it's a non-obvious design choice.
- **Downloaded a real dataset rather than writing one.** `HARDENING_PLAN.md`
  says "OurAirports/OpenFlights CSV" explicitly; I used OpenFlights'
  `airports.dat` (verified license: ODbL, confirmed against
  `github.com/jpatokal/openflights`'s own `data/LICENSE` file, not assumed
  from memory) because it already includes an IANA timezone column
  (`tz_database_time_zone`), matching `CLAUDE.md`'s target
  "IATA -> country, tz, name" exactly — OurAirports' own `airports.csv` would
  have needed a separate join against a coordinates-to-timezone dataset to
  get the `tz` column at all.
- **Added a new migration to drop the `airports` table rather than editing
  migration 1.** Nothing has "shipped" this table to a real deployed database
  yet (this whole project is still mid-hardening), so quietly rewriting
  migration 1 was tempting and would have been slightly less code — but
  demonstrating the forward-only migration discipline now, while it's cheap
  and low-stakes, is the point of having versioned migrations at all. Did the
  same thing I'd do if this table had real user data in it.
- **`get_provider()` validates and raises on an unknown `FLIGHT_PROVIDER`**
  rather than silently falling back to Aviationstack — a typo'd env var
  should fail loud at startup, not quietly ignore the operator's config.

**What I deliberately did not do**
- Did not migrate any existing test off directly stubbing
  `flight_api.get_flight_status` and onto `FakeProvider` — both are valid
  "no test hits a real API" strategies per `CLAUDE.md`'s Testing section, and
  churning already-passing, already-frozen Phase 0 tests just to use the new
  seam isn't this phase's job. `FakeProvider` exists and is tested in
  isolation (`tests/test_providers.py`); future phases can build on it
  directly without needing flight_api.py's internals at all.
- Did not switch the default provider away from Aviationstack, sign up for
  any other provider's API key, or verify any quota number by actually
  making calls against a live key — all explicitly out of scope for this
  phase, and the `docs/providers.md` research explicitly flags every number
  I could not verify from a vendor's own live page rather than estimating.
- Did not implement `supports_push`/webhook receiving for any provider —
  `AviationstackProvider.supports_push = False` is accurate (it has no push
  capability); building an actual webhook receiver is meaningful, unstarted
  work that belongs with whichever future phase actually adopts a
  push-capable provider, not this research-and-abstraction phase.
- Did not remove `flight_api.py`'s pre-existing lint findings (implicit
  Optional, etc.) — same reasoning as Phase 0/1, still out of this phase's
  scope.

## Phase 1 — Storage: JSON → SQLite

**What I did**
- Branched `harden/phase-1-sqlite-storage` from Phase 0's tip (corrected after
  accidentally branching from `main` first — no commits existed on the wrong
  branch yet, so `git reset --hard` onto the right tip was a safe pointer
  move, not a discard of real work).
- Replaced `storage.py` with a `storage/` package: `__init__.py` (facade
  functions, same names/most signatures as before), `migrations.py`
  (versioned, idempotent schema), `importer.py` (one-shot JSON→SQLite
  migration). Updated `airports.py` to persist its cache via `storage`
  instead of its own JSON file. Updated `bot.py`'s `check_all_flights` to
  pass `date` explicitly into the now-composite-keyed schedule/state calls,
  and to call `storage.importer.run()` once at startup.
- Designed the schema around the 5 tables `HARDENING_PLAN.md` names
  (`subscriptions`, `flights`, `change_events`, `api_usage`, `airports`), plus
  a small `usage_warnings` table and a `schema_version` table for the
  migration runner.
- Added 25 new tests and updated `ARCHITECTURE.md`/`CHANGELOG.md`.
- Ran a real (non-pytest) smoke test in the scratch directory: wrote sample
  legacy JSON files, ran the importer against a real file-backed DB, confirmed
  the data landed correctly and the source files were renamed to
  `*.json.imported`.

**What I decided and why**
- **Composite key with a convenience fallback.** `CLAUDE.md` requires flights
  keyed by `(flight_iata, scheduled_date)` to stop two people on the same
  flight number from colliding. Rather than making `date` a strictly required
  argument everywhere (which would have broken several frozen Phase 0 tests
  that call `storage.get_flight_schedule("RJ264")` with no date), I made
  `date` optional: omitting it resolves to the single matching row if there's
  exactly one, and raises `ValueError` if the flight code is genuinely
  ambiguous. This preserves every Phase 0 test that exercises the
  single-flight case unmodified, while still closing the real bug for the
  case that mattered (multiple dates for one flight number). `bot.py`'s
  polling loop always passes `date` explicitly regardless, so production
  behavior doesn't depend on the fallback at all.
- **`api_usage` as an event log, not a counter.** `CLAUDE.md`'s target schema
  is literally `(provider, timestamp, endpoint, http_status, counted)` — a
  log, not a single mutable row. Computing the monthly count via `COUNT(*)`
  over rows in the current month is both what the schema implies and
  incidentally removes the on-disk-staleness bug documented in `FINDINGS.md`.
- **Exactly 3 Phase 0 tests marked `xfail`, not edited.** Per `CLAUDE.md`'s
  hard-stop rule, I did not touch the content of any Phase 0 test file. Where
  a test characterized a JSON-file-specific implementation detail Phase 1
  deliberately eliminated (raw on-disk usage.json staleness; the airport cache
  being a JSON file at all), I added a single `pytest_collection_modifyitems`
  hook in `tests/conftest.py` that marks those exact three node IDs `xfail`,
  with the reasoning in `FINDINGS.md`. I did update `tests/conftest.py`'s
  fixture body itself (JSON path constants → a single `storage.DB_PATH`) since
  that's test *infrastructure* adapting to a new backend, not an assertion
  being weakened — the intent (isolated, network-free, per-test state) is
  unchanged. New coverage for the SQLite-backed airport cache lives in
  `tests/test_storage_repository.py`.
- **Kept `airports.CACHE_FILE` as an inert constant.** Two of the three
  "would otherwise break" `test_airports.py` tests only fail because
  `monkeypatch.setattr(airports, "CACHE_FILE", ...)` raises `AttributeError`
  if the attribute doesn't exist — their actual assertions don't depend on
  JSON-file mechanics at all. Keeping a genuinely unused `CACHE_FILE`
  constant let those two keep passing truthfully. This is short-lived: Phase
  2 deletes `airports.py`'s live network lookup entirely (bundled offline
  data instead), at which point the constant and the rest of
  `test_airports.py` go with it.
- **`change_events` table added but not yet used.** Creating it now (empty,
  unread) means Phase 3's dedupe/debounce rewrite doesn't need a second
  migration and doesn't lose any history between now and then. This is schema
  preparation, not scope creep into Phase 3's actual logic change.
- Left the alert-firing *logic* itself (the plain `!=` dict comparison, no
  null-transition guard, no dedupe/debounce) completely untouched — that's
  explicitly Phase 3's job. Phase 1 only changed *where and how* the same
  data is stored.
- Made a small, non-storage correction to README.md's "Notes" section (it
  named files that no longer exist) rather than leaving factually wrong docs
  in place until Phase 7's full rewrite.

**What I deliberately did not do**
- Did not touch `flight_api.py` at all — its two `storage` calls
  (`usage_remaining`, `increment_usage`) needed no signature change.
- Did not change the order of `increment_usage()` relative to the HTTP
  request in `flight_api.py` — quota is still consumed before the request is
  attempted, preserving existing (documented) behavior exactly, even though a
  `http_status` column now exists that could theoretically motivate
  reordering. Not this phase's job.
- Did not add a `chat_id` column to `subscriptions` even though Phase 4 will
  need one — no unused schema for a feature that isn't wired up yet.
- Did not remove `airports.py`'s live Aviationstack `/v1/airports` call —
  that's explicitly Phase 2 scope (bundled offline dataset).
- Did not add `pyproject.toml` — still deferred to Phase 6 as decided in
  Phase 0.

## Phase 0 — Safety net

**What I did**
- Initialized git (repo didn't exist yet), committed the pre-hardening code as a
  baseline on `main`, then branched `harden/phase-0-safety-net`.
- Created a Python 3.14 venv (`.venv/`) and installed `requirements.txt` plus dev
  tooling (`pytest`, `pytest-asyncio`, `ruff`, `mypy`, `time-machine`) — none of
  this was present on the system before.
- Read every module in full and wrote `ARCHITECTURE.md`: module layout, data
  flow, all five JSON file schemas, the exact boolean conditions under which an
  alert fires today, and a "known gaps" section cataloguing where current
  behavior falls short of `CLAUDE.md`'s target invariants.
- Wrote 67 characterization tests across 6 files (`tests/test_storage.py`,
  `test_scheduler.py`, `test_flight_api.py`, `test_airports.py`,
  `test_bot_handlers.py`, `test_bot_alerts.py`), all against a `tmp_path`-isolated
  copy of the JSON storage, with `requests.get` hard-blocked by an autouse
  fixture (raises `AssertionError` on any unstubbed call) and real API-key env
  vars stripped so a developer's real `.env` can never leak into a test run.
- Made no changes to `bot.py`, `flight_api.py`, `scheduler.py`, `storage.py`, or
  `airports.py`.

**What I decided and why**
- Two of the tests deliberately pin *current bugs*, not desired behavior:
  `test_alert_fires_on_value_to_null_transition` (a field going non-null → null
  is treated as a real change and fires an alert) and
  `test_remove_flight_removes_all_matching_codes_regardless_of_date` (`/remove`
  isn't date-scoped). Both are called out in `ARCHITECTURE.md`'s "known gaps"
  section and are expected to change in Phase 3 / Phase 4 respectively — when
  that happens, these two tests should be *updated* then, with a note, not
  silently deleted, since they're the record of what changed and why.
- Found and fixed a test-isolation gap before it could bite: `airports.py`
  caches to a hardcoded relative path and swallows all exceptions (including
  a deliberately-injected `AssertionError` from the network-block fixture) via
  a bare `except Exception`. Added `airports.CACHE_FILE` to the isolation
  fixture and an autouse fixture that strips `AVIATIONSTACK_API_KEY`/
  `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` from the environment for every test,
  so test behavior can never depend on what happens to be in the developer's
  real `.env` or shell.
- Used `time-machine` (already specified in `CLAUDE.md`) instead of `freezegun`
  — no reason to install both, and `time-machine` is faster and is the one
  named first.
- Did not add a `pyproject.toml` yet even though `ruff`/`mypy` support one —
  Phase 6 ("Packaging") explicitly owns adding it; a bare `pytest.ini` is enough
  for now and avoids getting ahead of that phase's scope.
- Ran `ruff check` against the *existing* production modules out of curiosity;
  it surfaces several pre-existing lint findings (an unsorted import in
  `flight_api.py`, an implicit-Optional parameter, a bare `except Exception` in
  `airports.py`, a naive-datetime construction in `bot.py`). Left all of them
  untouched — Phase 0's rule is no production code changes, and these aren't
  characterization-test concerns.

**What I deliberately did not do**
- Did not touch any production module.
- Did not add mypy strict-mode enforcement yet (current code has no type hints
  to check against — that's Phase 1+ as modules get rewritten).
- Did not write tests for `bot.py:main()` itself (Application wiring, job queue
  registration) — it's pure framework glue with no branching logic worth
  characterizing, and testing it would require standing up a real
  `Application`, which adds no safety net value.
