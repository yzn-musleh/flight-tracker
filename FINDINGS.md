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

**Disposition:** left failing, marked `xfail`. `airports.CACHE_FILE` is kept
as an inert module constant (unused by `get_country()`) purely so these two
tests still *run* against something rather than erroring in fixture setup;
see the comment at its definition. New coverage for the SQLite-backed cache
lives in `tests/test_storage_repository.py`
(`test_airport_country_cache_hit_avoids_network` and neighbors). Note
`airports.py`'s live network lookup — and therefore this whole cache,
JSON or SQLite — is scheduled for deletion in Phase 2, which bundles an
offline airport dataset instead; at that point all of `test_airports.py`
becomes characterization of code that no longer exists and the same
xfail-vs-delete question will need revisiting for the whole file, not just
these two tests.
