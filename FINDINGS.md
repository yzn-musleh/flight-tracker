# Findings

Record of cases where a Phase 0 characterization test could not be made to pass
after a later phase's intentional behavior change, per `CLAUDE.md`'s rule:
*"Never edit a Phase 0 test to make it pass... mark it xfail with a comment
linking to your reasoning here."* Each is marked `xfail` centrally in
`tests/conftest.py`, not by editing the test file itself.

## 1. `test_storage.py::test_usage_resets_in_memory_on_month_rollover_but_not_on_disk_until_next_write`

**Phase:** 1 (SQLite storage)

**What it characterized:** the old `usage.json` was a single mutable counter
blob. `load_usage()` computed the correct reset-to-zero value in memory the
instant the calendar month rolled over, but that reset was only ever written
back to disk the next time something called `save_usage()` (e.g.
`increment_usage()`). So the on-disk file could show last month's `count` for
an arbitrary amount of time after the rollover if nothing incremented it. The
test asserted exactly this staleness window existed.

**Why it can't pass anymore:** Phase 1 replaced the mutable counter with an
append-only `api_usage` event log (one row per request, with a timestamp).
`load_usage()` now computes the current month's count with
`COUNT(*) WHERE substr(timestamp,1,7) = :this_month` every time it's called —
there is no stored "current count" value to go stale in the first place. This
was a deliberate side effect of the storage redesign, not an oversight: an
event log is the natural shape for `CLAUDE.md`'s target `api_usage` schema
(`provider, timestamp, endpoint, http_status, counted`), and it happens to
remove a real correctness gap for free.

**Disposition:** left failing, marked `xfail`. If a future phase reintroduces
any cached/materialized usage count for performance, re-examine whether the
staleness property this test guards against could come back, and either fix
it or write a new test for the new implementation.

## 2 & 3. `test_airports.py::test_get_country_caches_successful_lookup_to_disk`, `test_get_country_uses_cache_without_calling_network_again`

**Phase:** 1 (SQLite storage)

**What they characterized:** `airports.py` cached IATA→country lookups in its
own `airport_countries.json` file, read/written directly by `airports.py`
(independent of `storage.py`). Both tests patch `airports.CACHE_FILE` and
assert against that JSON file's contents directly.

**Why they can't pass anymore:** `HARDENING_PLAN.md`'s Phase 1 scope
explicitly lists `airports` as one of the five original JSON files that
collapse into SQLite tables. `airports.py` now calls
`storage.get_airport_country()` / `storage.save_airport_country()`, which
persist to the `airports` table in the same SQLite database as everything
else — there is no longer any JSON file for these tests to inspect.

**Disposition:** left failing, marked `xfail`. New coverage for the
SQLite-backed cache lived in `tests/test_storage_repository.py` for Phase 1;
that cache (and its tests) were themselves removed in Phase 2 — see #4 below,
which is exactly the "revisit the whole file" moment anticipated here.

## 4. `test_airports.py`: the three remaining live-network-lookup tests

**Phase:** 2 (provider abstraction + offline airport data)

**Tests:** `test_get_country_returns_unknown_without_api_key_and_makes_no_call`,
`test_get_country_does_not_cache_unresolved_lookup`,
`test_get_country_swallows_network_errors_as_unknown`.

**What they characterized:** `airports.get_country()` used to call
Aviationstack's `/v1/airports` live, gated on `AVIATIONSTACK_API_KEY` being
set, swallowing network errors as `"Unknown"`. These three tests characterized
that gating and error-swallowing behavior specifically.

**Why they can't pass anymore:** `HARDENING_PLAN.md`'s Phase 2 scope
explicitly says to "resolve country and timezone from [a bundled offline
dataset] instead of API lookups" and "delete `airport_countries.json`
entirely." `airports.py` now reads `static/airports.csv` (a filtered,
ODbL-licensed derivative of the OpenFlights Airport Database — see
`static/AIRPORTS_LICENSE.md` for provenance and license) at import time and
never imports `requests` or touches an API key at all:
- Without an API key: the old code returned `"Unknown"`; the new code
  resolves airports from the bundled dataset regardless (e.g. `AMM` →
  `"Jordan"`), since there's no key to be missing in the first place. The
  first test's premise is gone.
- The other two tests call `monkeypatch.setattr(airports, "requests", ...)`
  / `airports.CACHE_FILE` to simulate a network failure/a cache miss — both
  attributes no longer exist on the module, so these error in fixture setup
  before their assertions even run.

The Phase 1 SQLite `airports` table itself was also dropped (migration
version 2 in `storage/migrations.py`) since a bundled, always-available,
zero-cost dataset needs no cache at all.

**Disposition:** left failing, marked `xfail`. `airports.CACHE_FILE`, kept
in Phase 1 purely to let two tests still run, was removed in Phase 2 since
by this point it wasn't saving any additional test from `xfail` status —
keeping genuinely dead code for no benefit isn't worth it. New coverage for
the offline dataset lives in `tests/test_airports_offline.py` (new in
Phase 2, kept as a separate file rather than appended to the frozen
`test_airports.py`). Only 1 of `test_airports.py`'s original 6 tests
(`test_get_country_returns_unknown_for_empty_code`) still passes — the
empty-input short-circuit is the one piece of behavior Phase 2 didn't touch.

## 5. `test_bot_alerts.py::test_alert_fires_on_value_to_null_transition`

**Phase:** 3 (correctness of alerts)

**What it characterized:** a deliberately-preserved *bug*, not a design
choice — the test's own docstring said so: "Documents a known bug (see
ARCHITECTURE.md): a field disappearing is treated the same as a real
change. Phase 3 is expected to fix this — if it does, this test should be
updated there, not silently deleted." Pre-Phase-3, `check_all_flights`
compared whole snapshots with a plain `!=`, so a field going from a real
value to `null` (e.g. a gate briefly dropping out of the provider's
response) counted as "changed" and fired an alert — violating `CLAUDE.md`
invariant #2 ("Never alert on missing data... Only non-null -> different
non-null... produce a message").

**Why it can't pass anymore:** it fixed itself, on schedule. Phase 3
introduced `change_detection.detect_changes()`, which enforces exactly this
null-guard (plus the status whitelist for cancelled/diverted/landed). Given
the same two polls as this test (gate `"12"` → `None`), the new logic
correctly finds no alert-worthy change (both `old is not None and new is
not None` fails, and `status` didn't change), so no message is sent —
which is *why* `context.bot.send_message.assert_awaited_once()` now fails:
zero awaits, not one.

**Disposition:** left failing, marked `xfail`, per `CLAUDE.md`'s rule
against editing a Phase 0 test even when the fix was fully anticipated by
the test's own docstring — the rule doesn't carve out an exception for
"but I meant to." New coverage of the *correct* behavior (no alert on a
null transition, whitelisted alert on a null→terminal-status transition,
dedupe-and-retry across a simulated crash) lives in
`tests/test_change_detection.py`.
