# HANDOFF

Result of running `HARDENING_PLAN.md` phases 0–7 against `CLAUDE.md`'s
invariants, in one continuous, unattended pass, per your explicit
instruction to run straight through without pausing for approval between
phases. Two clarifying questions were asked before Phase 0 started (see
"Two things I checked with you before starting" below); every other
decision below was made autonomously and is reported here for you to
review, not asked about in the moment.

**No `BLOCKED.md` exists.** I never hit one of the listed hard stops
(a needed credential/signup, an undocumented provider response shape, or
genuinely contradictory phase requirements). Two lesser tensions came up —
`HARDENING_PLAN.md`'s own "one phase at a time" note versus your "run
straight through" instruction, and Phase 7's CI asking for `mypy --strict`
against a codebase that wasn't strict-clean — both are covered below, and
neither rose to a hard stop as the plan defines them.

## What changed, phase by phase

**Phase 0 — Safety net.** Read every module and wrote `ARCHITECTURE.md`
describing the pre-hardening system exactly as it was, warts included
(state.json's flight_iata-only keying, a null-transition alerting bug, no
`chat_id` scoping). Wrote 67 characterization tests against a fresh,
isolated copy of the JSON storage, with real network calls hard-blocked by
an autouse fixture. No production code was touched. This is the baseline
every later phase's "did I actually preserve behavior" claim is checked
against.

**Phase 1 — Storage: JSON → SQLite.** Replaced the five flat JSON files
with a single SQLite database (WAL mode) behind a `storage/` package,
keeping the same function-level API the rest of the code already called.
Fixed two real bugs as a direct consequence of the redesign, not as scope
creep: flights are now keyed by `(flight_iata, scheduled_date)` instead of
`flight_iata` alone (two people on the same flight number on different
dates no longer collide), and monthly usage is a query-based event log
instead of a mutable counter that could show a stale month's count on disk.
A one-shot importer migrates any pre-existing JSON files automatically.

**Phase 2 — Provider abstraction + offline airport data.** Extracted a
`FlightProvider` protocol and moved Aviationstack behind it, added a
`FakeProvider` for tests. Bundled a real, downloaded-and-verified offline
airport dataset (`static/airports.csv`, filtered from OpenFlights, ODbL
licensed) so country/timezone resolution costs zero API calls and zero
network round-trips, replacing a live lookup entirely. Researched
AeroDataBox, FlightAware AeroAPI, Aviation Edge, and OpenSky against their
own live documentation and wrote `docs/providers.md` with a recommendation
— Aviationstack stayed the default in code, exactly as scoped.

**Phase 3 — Correctness of alerts.** Rewrote change detection
(`change_detection.py`) to enforce the invariants `CLAUDE.md` actually
states: alerts fire only on a genuine non-null → different-non-null
transition, plus an explicit whitelist (cancelled/diverted/landed alert
even with no prior status on record). Every detected change is durably
recorded *before* any send is attempted and deduped by
`(flight_iata, scheduled_date, field, new_value)`, so a crash mid-send is
retried next poll, not lost or replayed — proven with an actual simulated
crash-and-restart test. Added dual-timezone rendering (airport-local +
subscriber).

**Phase 4 — Multi-user and access control.** Removed the global
`TELEGRAM_CHAT_ID` entirely. Every subscription now belongs to the
`chat_id` that created it, enforced by required parameters on every storage
function, not a convention. Added an access-control gate
(`ALLOWED_CHAT_IDS` admins, `/request_access` → `/approve`/`/deny`),
`/forget`, per-chat `/timezone`, and group-admin restriction on destructive
commands. `check_all_flights` now polls each real flight once and fans the
result out to every chat subscribed to it. This phase broke the most
Phase-0 tests of any phase (20, all `xfail`'d, all directly required by the
phase's own explicit mandate — see `FINDINGS.md` #6) and added the most new
test coverage (28 tests) to compensate.

**Phase 5 — Resilience and the scheduler.** Replaced recompute-from-
`last_checked` scheduling with a persisted `next_poll_at`, fixed at
check-time rather than re-derived on every tick. Added a circuit breaker +
exponential-backoff-with-jitter for 429/5xx (`resilience.py`), and fixed a
real pre-existing bug while wiring it in: a non-429 4xx used to raise an
uncaught `requests.HTTPError` that would have crashed the entire poll cycle
mid-loop. Added Telegram `RetryAfter` handling, a PID-file single-instance
lock, and JSON structured logging with secret redaction and a
per-poll-cycle correlation id. Verified (via the installed library's own
docstring, not assumed) that `python-telegram-bot` already provides
graceful SIGTERM shutdown on the actual deployment target.

**Phase 6 — Packaging and deployment.** Added `pyproject.toml`. Setting an
honest `target-version` for the linter surfaced 16 real, safe modernizations
that got fixed rather than left. Wrote a multi-stage `Dockerfile`
(non-root user, healthcheck) and `docker-compose.yml`, then **actually
built and ran the image** in this session — confirmed the non-root user,
a clean import, the healthcheck's exit code, and a real SQLite write to the
mounted volume path, not just a plausible-looking Dockerfile. Added a
systemd unit as the non-Docker alternative, and webhook mode as an
alternative to long polling.

**Phase 7 — Publishable.** Scanned the full git history for secrets/PII
before making any other change (findings below). Discovered Phase 7's own
CI requirement would fail immediately against this codebase and brought the
*entire* codebase to genuine `mypy --strict` compliance rather than
weakening that requirement — confirmed with the full test suite passing
unmodified throughout, since it was a pure type-annotation pass. Added
`LICENSE`, `CONTRIBUTING.md`, issue/PR templates, and
`.github/workflows/ci.yml` — and actually ran the exact commands that
workflow uses (the Docker build, the smoke checks, `pip install -e
".[dev]"`) locally to confirm they work, not just wrote YAML. Rewrote
`README.md` for a stranger.

## Two things I checked with you before starting

Both answered before Phase 0 began, both load-bearing for everything after:

1. **`HARDENING_PLAN.md`'s own text says "feed Claude Code one phase at a
   time... ask for a plan before each phase"** — directly opposite your
   "run straight through, don't ask for approval between phases"
   instruction. You chose to run straight through; I did. Worth knowing
   this contradiction exists in your own planning document if you didn't
   remember writing that line.
2. Whether to `git init` the (until-then-ungitted) directory. You said yes.

## Assumptions I made that you haven't confirmed

- **The LICENSE copyright name is "Yazan"**, taken from your git commit
  author config (`Yazan <yazanmusleh020@gmail.com>`). I don't know your
  legal name and didn't want to guess further — check `LICENSE` before
  publishing.
- **MIT is the right license.** You didn't specify one; MIT is what
  `HARDENING_PLAN.md`'s Phase 7 prompt names explicitly, so I used it
  without asking further.
- **`legacy_chat_id = os.environ.get("TELEGRAM_CHAT_ID") or "legacy"`** in
  the importer (`storage/importer.py`) assumes you'll either still have
  `TELEGRAM_CHAT_ID` set in your real `.env` when you first run the
  upgraded bot (in which case your existing tracked flights land under that
  chat automatically and it's auto-approved), or you're fine with them
  landing under the literal chat_id `"legacy"` if not (inaccessible until
  manually reassigned — there's no admin tool for that). I did not run this
  importer against your real data; I only tested it against synthetic
  fixtures in the scratch directory.
- **`AviationstackProvider` remains the default `FLIGHT_PROVIDER`.** Per
  Phase 2's explicit scope note. `docs/providers.md` recommends AeroDataBox
  *if* you ever switch, but nothing was switched.
- **Aviationstack's, AeroDataBox's, FlightAware's, and Aviation Edge's
  pricing/quota pages reflect what I could load on 2026-08-27.** These
  change; if you're reading this much later, re-verify before trusting
  `docs/providers.md`'s numbers.

## Open questions and things I'm not fully confident about

- **`storage/importer.py`'s upgrade path for a real `TELEGRAM_CHAT_ID` is
  untested against real data.** I built and tested it against synthetic
  fixtures (`tests/test_importer.py`) and a manual scratch-directory run
  with fabricated files, never against your actual pre-hardening
  `flights.json`/`state.json`/etc. If you have real tracked flights in the
  old format, back up those JSON files before letting the new bot's
  importer touch them — it renames them to `*.json.imported` on success,
  but I'd rather you had a copy regardless.
- **Two git-history findings I did not act on, only reported**, since
  both predate my work (present in the very first "Baseline" commit) and
  git history must never be rewritten regardless:
  - README.md's original text uses "Uncle_Khalid" as an example name.
    Mild — a first name only, in a private repo you control — but worth a
    look before making the repo public, since it's presumably a real
    family member's name.
  - `HARDENING_PLAN.md`'s own Phase 6 note mentions
    "`server.yznweb.com`" as your Cloudflare Tunnel domain. This is a more
    concrete piece of personal infrastructure information than the name
    above; consider whether you want `HARDENING_PLAN.md` itself included
    in a public release of this repo, or genericized first.
- **`static/AIRPORTS_LICENSE.md`'s ODbL compliance is my own reading of the
  license text, not a lawyer's.** I believe bundling a filtered subset of
  OpenFlights' data with attribution and a license pointer satisfies ODbL
  §4.2/§4.4, but if this project is ever commercialized or distributed at
  meaningfully larger scale, that's worth a second, more qualified look.
- **The healthcheck (`healthcheck.py`) can't distinguish "the process is
  alive" from "the process is alive but Telegram is unreachable."** It only
  checks the single-instance lock's PID. Called out in `PROGRESS.md`'s
  Phase 6 entry as a deliberate scope decision, not an oversight — flagging
  again here since it's the kind of thing that's easy to forget six months
  from now when debugging a "container looks healthy but nothing's
  happening" report.
- **Fan-out alert delivery isn't perfectly exactly-once across multiple
  subscribers.** If sending to subscriber 2 of 3 fails, subscriber 1 (who
  already got it) will get the same alert again on the retried poll. See
  `PROGRESS.md`'s Phase 4 entry for the reasoning on why this was judged an
  acceptable tradeoff at this project's scale.
- **`bot.py`'s command handlers were never manually tested against a real
  Telegram client** — no real bot token exists in this environment, and the
  task rules explicitly forbid signing up for one. Everything is verified
  through the test suite (185 passing tests exercising every handler with
  faked `Update`/`Context` objects) and, for the Docker/systemd side,
  actual container runs — but not a real `/add` typed into a real Telegram
  chat.

## Where every phase's changes actually live

Nothing was merged to `main` — each phase is its own branch, cut from the
previous phase's tip, exactly as instructed:

```
main
 └─ harden/phase-0-safety-net
     └─ harden/phase-1-sqlite-storage
         └─ harden/phase-2-providers
             └─ harden/phase-3-alert-correctness
                 └─ harden/phase-4-multi-user
                     └─ harden/phase-5-resilience
                         └─ harden/phase-6-packaging
                             └─ harden/phase-7-publishable   (tip: everything)
```

`harden/phase-7-publishable` contains every phase's work, in order, as 51
commits. Reviewing phase-by-phase means diffing consecutive branches
(`git diff harden/phase-0-safety-net..harden/phase-1-sqlite-storage`, etc.);
reviewing the whole thing means diffing `main..harden/phase-7-publishable`.

## Exact commands to verify this yourself

```bash
# Get onto the finished branch
git checkout harden/phase-7-publishable

# Set up the environment (mirrors what CI does)
python -m venv .venv
.venv\Scripts\activate        # Windows; source .venv/bin/activate elsewhere
pip install -r requirements.txt
pip install -e ".[dev]"

# The four checks CI runs on every PR
pytest -q
ruff check .
ruff format --check .
mypy --strict bot.py access.py airports.py change_detection.py flight_api.py healthcheck.py logging_config.py providers/ resilience.py scheduler.py singleton.py storage/ timezones.py

# Expect: 185 passed, 1 skipped (a Windows-only skip in test_singleton.py,
# explained in its own skip reason), 30 xfailed (all documented in
# FINDINGS.md, all Phase 0 tests superseded by a later phase's intentional,
# plan-mandated behavior change -- none are unexplained failures)

# Docker build + the same smoke checks CI's docker-build job runs
docker build -t family-flight-tracker:verify .
docker run --rm --entrypoint id family-flight-tracker:verify
docker run --rm --entrypoint python family-flight-tracker:verify -c "import bot; print('OK')"
docker run --rm --entrypoint python family-flight-tracker:verify healthcheck.py; echo "exit code: $? (expect 1, no lock file yet)"
docker image rm family-flight-tracker:verify

# Read the reasoning behind every non-obvious decision
cat ARCHITECTURE.md   # what the system does and why, updated every phase
cat FINDINGS.md       # every Phase 0 test that had to be xfail'd, and why
cat PROGRESS.md       # what I did and decided, phase by phase, in my own words
cat CHANGELOG.md       # the same history in changelog form
```

If you want to actually run the bot for real, you'll need your own
`TELEGRAM_BOT_TOKEN` and `AVIATIONSTACK_API_KEY` — see `README.md`'s
Quickstart. Nothing in this repo has one.
