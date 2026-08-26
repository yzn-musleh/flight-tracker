# Progress Log

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
