# Progress Log

## Phase 7 — Publishable

**What I did**
- Branched `harden/phase-7-publishable` from Phase 6's tip.
- **Scanned the full git history first**, per this phase's explicit
  instruction to report before changing anything: searched every commit's
  diff for Telegram-bot-token-shaped strings, `access_key=`-shaped API key
  patterns, a committed `.env` file, real `TELEGRAM_CHAT_ID` values, and
  email/phone-shaped strings. Found: no real secrets ever committed (only
  `.env.example` placeholders); the repo author's own email appears in
  every commit's authorship metadata (normal git behavior, not a leak);
  two pre-existing items from the very first ("Baseline") commit worth
  flagging for the repo owner — a first name in README's original example
  text, and a real-looking domain in `HARDENING_PLAN.md`'s own Phase 6
  planning note. Did not touch either (reporting only, and git history
  must never be rewritten regardless).
- Discovered mid-phase that Phase 7's own CI requirement ("mypy --strict"
  on every PR) would fail immediately — ran `mypy --strict` against the
  whole codebase for the first time and found ~100 errors across nearly
  every module, not the ~50 `bot.py`-only Optional-access errors I'd been
  tracking as a known gap since Phase 4. Fixed all of them rather than
  scoping CI's mypy step down to something weaker than what the plan
  actually asks for.
- Added `LICENSE`, `CONTRIBUTING.md`, GitHub issue/PR templates, and
  `.github/workflows/ci.yml`.
- Rewrote `README.md` for a stranger.

**What I decided and why**
- **Fixed the full `mypy --strict` gap rather than weakening the CI
  requirement.** I considered three options: run `mypy --strict` and ship
  known-red CI, run plain `mypy` in CI and quietly not do what the plan
  asked, or actually fix it. Given the explicit ask ("a GitHub Actions
  workflow running ruff, mypy --strict, pytest...") and that nothing about
  the fix was blocked (it was large, not hard, and entirely mechanical —
  missing generic type arguments, missing return annotations, a handful of
  `assert`s in `bot.py`), shipping broken or quietly-downgraded CI on a
  repo whose whole point is "publishable" felt like exactly the kind of
  corner this hardening effort exists to not cut. Full accounting of what
  changed is in the Phase 7 commit for it; the short version is zero
  behavior change, confirmed by the passing test suite at every step.
- **`assert update.message is not None` (etc.) rather than `if` guards with
  early returns, or restructuring handlers to take a narrower type.** Every
  one of these handlers is only ever invoked by `CommandHandler` for a
  `Message` update, which Telegram/PTB guarantees has `.message`,
  `.effective_chat` set (and `.effective_user` for a real user's message,
  used only in the group-admin check). An `assert` documents a real,
  always-true invariant at zero runtime cost when it holds, and gives a
  loud, honest failure (not a silent `None`-shaped bug) in the
  practically-impossible case it doesn't. Adding a defensive `if
  update.message is None: return` instead would silently swallow a case
  that should never happen and, if it somehow did, hide a real bug behind
  a no-op.
- **Replaced three lambda-with-default-arg closures with typed nested
  `async def` functions, not bare lambdas.** My first attempt at fixing
  mypy's "cannot infer type of lambda" error was to drop the
  `x=x`-style default-argument closures on the reasoning that each lambda
  is awaited within the same loop iteration it's created in, so the classic
  "closure captures the loop variable by reference, all of them see the
  last value" bug can't actually happen here. That's true *today*, but
  `ruff`'s `B023` correctly flagged the bare-lambda version anyway — it's
  right that this is a real footgun if the code is ever changed to fire
  sends concurrently instead of sequentially, and "true today, fragile
  tomorrow" isn't a bar this project should accept just to satisfy a type
  checker. A typed nested function keeps the exact same default-argument
  capture (still safe against that future change) while giving mypy an
  annotated parameter to infer from, which a lambda syntactically can't
  provide.
- **CI's Docker job re-runs the exact manual smoke checks from Phase 6**
  (non-root user, clean `import bot`, healthcheck exit code) rather than
  just `docker build` with no follow-up — a Dockerfile that merely builds
  can still be broken in ways that only show up when you actually run it,
  which is exactly what Phase 6's manual verification caught that a bare
  build wouldn't have.
- **Screenshots deliberately omitted from the README, not faked.** I have
  no way to produce a real screenshot of this bot's Telegram output without
  either fabricating a fake conversation (against this project's own "don't
  invent things that look real" ethos, and the broader instruction to never
  fabricate content that could pass as genuine) or actually running a live
  bot against a real Telegram chat (out of scope, needs real credentials).
  Left an explicit HTML-comment placeholder in the README explaining this
  and inviting the repo owner to add a real one, rather than silently
  dropping the request or shipping a fake image.

**What I deliberately did not do**
- Did not act on either git-history finding (the example name, the domain
  in `HARDENING_PLAN.md`) beyond reporting them — that's a call for the
  repo owner, not something to unilaterally redact, and git history must
  never be rewritten regardless of what's found in it.
- Did not add a CODEOWNERS file, branch protection rules, or a release/tag
  workflow — none of those were asked for, and inventing process for a
  single-maintainer personal project isn't "publishable," it's scope creep.
- Did not add real screenshots — see above.
- Did not type-check the `tests/` directory in CI's `mypy --strict` step —
  test files were never brought to strict compliance and doing so now
  would be a large, low-value effort (test code benefits far less from
  strict typing than the production modules it exercises).

## Phase 6 — Packaging and deployment

**What I did**
- Branched `harden/phase-6-packaging` from Phase 5's tip.
- Added `pyproject.toml` (project metadata, `dev` extra, tool config for
  pytest/ruff/mypy), removed `pytest.ini` (superseded), verified pytest
  still picked up the moved config correctly by running the full suite.
- Discovered that setting `target-version = "py312"` for ruff (not present
  before — there was no ruff config file at all until this pyproject.toml)
  changed ruff's *effective* findings, not just documented an assumption:
  it surfaced 16 new `UP017`/`FURB162` findings across 5 files that ruff's
  own defaults hadn't been suggesting without a known target version.
  Verified each category was behavior-identical before fixing (tested
  `datetime.fromisoformat` with a literal `"Z"` suffix directly in this
  Python 3.14 environment to confirm it parses identically to the
  `.replace("Z", "+00:00")` workaround) and fixed all of them, including in
  Phase-0-authored `scheduler.py` — a pure type/spelling change, not a
  behavior change, with the whole test suite as evidence.
- Wrote the multi-stage `Dockerfile`, `.dockerignore`, `docker-compose.yml`,
  `healthcheck.py`, `deploy/flight-tracker.service`, and `deploy/README.md`.
- **Actually built and ran the Docker image** (Docker Desktop was available
  in this environment) rather than only writing a Dockerfile and trusting
  it: `docker build` succeeded end-to-end; then, with `--entrypoint`
  overrides, confirmed `whoami`/`id` report the non-root `flighttracker`
  user (uid 1000), `python -c "import bot"` succeeds cleanly, and
  `healthcheck.py` correctly exits 1 with no lock file present. Then ran a
  script inside the container that acquired the single-instance lock and
  wrote a real SQLite row under `/data` (the volume mount point) as that
  non-root user, confirming the permissions (`chown` in the Dockerfile) are
  actually correct, not just plausible-looking. Cleaned up the test image
  afterward.
- Added `bot._webhook_config()` (pure, testable independent of starting a
  server) and wired it into `main()`; wrote
  `tests/test_webhook_config.py` covering the mode-selection logic
  (falsy/truthy env values, missing `WEBHOOK_URL` raising, URL/path
  joining, listen/port defaults and overrides) and
  `tests/test_healthcheck.py` for the healthcheck script's own logic.

**What I decided and why**
- **Fixed the newly-surfaced ruff findings rather than avoiding
  `target-version` to dodge them.** I could have left `[tool.ruff]` without
  a `target-version` to keep ruff's output byte-identical to before this
  phase — but that would mean deliberately keeping ruff *less accurate*
  about what Python version this project actually targets (CLAUDE.md says
  3.12+) just to avoid a one-time cleanup. Since every one of the 16
  findings was a mechanical, verified-behavior-identical modernization
  (confirmed via `ruff --fix` for `UP017` and a direct behavior check for
  `FURB162`), fixing them was the more honest choice — and since none of
  them touch any function's observable behavior (only *how* an equivalent
  UTC value is spelled), no Phase 0 test was at risk and none needed
  touching.
- **Kept `requirements.txt` alongside `pyproject.toml` rather than
  replacing it.** `Dockerfile`'s build stage installs from
  `requirements.txt` directly (`pip install -r requirements.txt`) rather
  than doing a full `pip install .` build-backend resolution inside the
  image — simpler, faster build, and avoids needing `pyproject.toml`'s
  `[build-system]` to be exercised in a context (a container build) where
  a slow or subtly different resolution would be an annoying place to debug
  it for the first time.
- **The Docker healthcheck checks process liveness via the single-instance
  lock, not an HTTP ping** — deliberately mode-agnostic (works identically
  whether `WEBHOOK_MODE` is on or off) rather than writing two different
  healthcheck strategies for two run modes. Trade-off: it can confirm the
  process hasn't crashed/been silently replaced, but can't detect "the
  process is alive but Telegram's API is unreachable" the way an HTTP
  self-check against a webhook-mode-only endpoint could. Judged proportionate
  for this project's scale; noted here rather than left silently unstated.
- **systemd unit assumes a specific path/user** (`/opt/flight-tracker`,
  `flighttracker`) with clear instructions to adjust both if different —
  matches `deploy/README.md`'s own setup steps exactly rather than being a
  generic template disconnected from the instructions that reference it.

**What I deliberately did not do**
- Did not add an HTTP `/health` endpoint even in webhook mode — the
  process-liveness check covers the case this project actually needs
  (detect a crashed/hung container) without adding a second code path.
- Did not push the built image anywhere or set up a container registry /
  CI image-publish step — that's Phase 7's GitHub Actions territory, if
  in scope there at all; this phase only needed the image to build and run
  correctly, which was verified directly.
- Did not restructure the flat module layout into an installable
  `src/`-style package — `pyproject.toml`'s `[tool.setuptools]` uses
  `py-modules`/`packages.find` against the existing flat layout rather than
  moving files, since nothing in this phase's scope (Docker/systemd
  deployment) needs the project to be pip-installable by a third party.

## Phase 5 — Resilience and the scheduler

**What I did**
- Branched `harden/phase-5-resilience` from Phase 4's tip.
- Rewrote `scheduler.is_due()` to compare against a persisted `next_poll_at`
  (migration version 5 adds `flights.next_poll_at`) instead of recomputing
  the tier interval from `last_checked` on every call; added
  `scheduler.compute_next_poll_at()` and wired it into both
  `update_flight_schedule()` call sites in `check_all_flights` (success and
  lookup-failure paths).
- Added `resilience.py` (circuit breaker, retry-with-backoff,
  Telegram-RetryAfter helper) and wired it into `flight_api.py` and every
  `send_message` call in `bot.py`.
- Added `singleton.py` (PID-file lock) and `logging_config.py` (JSON
  logging, redaction, correlation-id adapter), wired into `bot.py`'s
  `main()` and `check_all_flights()`.
- Verified `python-telegram-bot`'s SIGTERM handling directly against the
  installed library's source/docstring (`Application.run_polling`'s
  `stop_signals` parameter defaults to `SIGINT, SIGTERM, SIGABRT` on
  non-Windows) rather than assuming it from memory — this is exactly the
  kind of claim the project's rules say to verify, not invent.
- Ran a real smoke test of the JSON logging + redaction (confirmed a fake
  token string is replaced with `***REDACTED***` in actual log output) and
  of the single-instance lock (confirmed a second `acquire()` while the
  first is still held raises, and that release cleans up).

**What I decided and why**
- **Found and fixed a real bug in my own first draft of `retry_with_backoff`
  before it shipped**: `sleep=time.sleep`/`rand=random.random` as *default
  parameter values* bind those function references once, at module-import
  time — a test that later does `monkeypatch.setattr(resilience.time,
  "sleep", fake)` has no effect on an already-bound default, so my first
  version of the resilience test suite actually slept for real seconds
  during backoff delays (a 7-test file took 3.46s; it should have taken
  milliseconds). Fixed by resolving `time.sleep`/`random.random` (and
  `asyncio.sleep`, same bug in `send_with_retry`) *inside* the function body
  instead of as defaults, so the lookup happens at call time and genuinely
  respects a monkeypatch. Worth calling out because this exact bug pattern
  — "injectable dependency" that isn't actually injectable due to
  default-argument binding — is easy to write and easy to not notice unless
  you're watching the test runtime.
- **Retry/circuit-breaker scope is exactly HTTP status codes, not raw
  connection exceptions.** CLAUDE.md's failure semantics section enumerates
  "429 and 5xx" and "4xx other than 429" — both response-shaped. A raw
  `requests.ConnectionError` (no response at all) is treated as an
  immediate, single-attempt failure: recorded against the circuit breaker
  and raised as `FlightLookupError`, but not retried within the same call.
  This is a deliberate, narrower scope than "retry anything that might be
  transient" — expanding it would be reasonable future work but isn't what
  was asked.
- **Each real HTTP attempt increments usage separately, not once per logical
  call.** If a request retries twice due to 429s, that's two real requests
  against Aviationstack's actual server-side quota, and under-counting them
  locally would risk exceeding the real quota without our own accounting
  ever noticing (CLAUDE.md invariant #3). The tradeoff: the pre-call budget
  check (`usage_remaining(cap) <= 0`) isn't re-verified between retries
  within one call, so a burst of 429s right at the boundary could
  theoretically consume 1-2 units past the checked threshold. Accepted as a
  minor, rare-in-practice imprecision rather than adding a re-check on every
  retry attempt for a 100-requests/month hobby-scale budget.
- **A non-429 4xx now raises `FlightLookupError` instead of an uncaught
  `requests.HTTPError`.** This was a real, pre-existing robustness bug I
  found while implementing this phase, not something Phase 5 asked for
  directly — but CLAUDE.md's "4xx other than 429: do not retry, log once,
  mark the flight as needing attention" only makes sense if that error is
  actually catchable, and it wasn't (a bare `resp.raise_for_status()` raised
  `requests.HTTPError`, which `bot.py`'s `except flight_api.FlightLookupError`
  never caught, so it would have crashed the entire poll cycle including
  every flight after the one that 404'd). Fixing it was necessary to make
  the stated failure semantics true at all, not scope creep.
- **Single-instance lock is a plain PID file, not the `filelock` package.**
  ~30 lines of stdlib `os.kill(pid, 0)`-based liveness checking covers what's
  needed (detect and reclaim a stale lock from a crashed process) without a
  new dependency. Documented the real, verified platform gap this creates:
  `os.kill(pid, 0)` for a nonexistent pid raises a generic `OSError` on
  Windows (confirmed empirically, not assumed) rather than
  `ProcessLookupError`, so stale-lock reclaim is exact on POSIX (the actual
  Phase 6 Docker/Linux deployment target) and conservative
  (assume-still-running, refuse to steal the lock) on Windows. One test is
  explicitly skipped on Windows for this reason, with the platform
  difference explained in the skip reason rather than silently passing or
  silently failing.
- **Structured logging redacts on the fully-rendered string, not raw
  `%`-args.** Mutating `record.msg`/`record.args` before Python's own
  `%`-substitution runs is fragile (args can be non-strings, substitution
  order matters); redacting `record.getMessage()`'s already-substituted
  output, and `formatException()`'s already-rendered traceback, in the
  formatter itself is simpler and can't get out of sync with how logging's
  own substitution works.
- **Correlation id via `logging.LoggerAdapter`, not `extra=` at every call
  site.** One adapter created at the top of `check_all_flights`
  (`cycle_log`) tags every message logged through it automatically, instead
  of every individual `log.info(...)` call needing to remember to pass
  `extra={"correlation_id": ...}`.

**What I deliberately did not do**
- Did not retry raw connection-level exceptions (no HTTP response at all) —
  see above.
- Did not re-verify the quota budget between retry attempts within a single
  `get_flight_status()` call — see above.
- Did not add the `filelock` package — see above.
- Did not reimplement SIGTERM handling — verified `python-telegram-bot`
  already does this correctly on the deployment target and would have been
  redundant, possibly conflicting, code.
- Did not build a distributed/multi-host lock — `singleton.py` is explicitly
  a single-machine safeguard, matching the actual deployment shape (one
  bot process, per `HARDENING_PLAN.md`'s Phase 6 Docker Compose plan).

## Phase 4 — Multi-user and access control

**What I did**
- Branched `harden/phase-4-multi-user` from Phase 3's tip.
- Migration version 4: `subscriptions.chat_id` (required going forward) and
  a new `chats` table (access status, per-chat timezone).
- Rewrote the relevant `storage.py` functions to take `chat_id` as a
  required parameter, and added `forget_chat`, `load_distinct_tracked_flights`,
  `get_subscribers`, and the `chats`-table access/timezone functions.
- Added `access.py` (pure, no telegram import) and wired an access gate
  (`bot._require_access`) into every data-touching handler.
- Added `/forget`, `/timezone`, `/request_access`, `/approve`, `/deny`, and
  a group-admin check (`bot._is_chat_admin`, real Telegram chat-member
  status) gating `/remove` and `/forget` in group chats.
- Rewrote `check_all_flights` to poll each distinct flight once and fan
  alerts out to every subscribed chat, addressed with that chat's own
  subscriber name and rendered in that chat's own timezone.
- Registered the command list via `set_my_commands` in a `post_init` hook.
- Updated the one-shot importer to assign legacy `flights.json` entries to
  the chat in `TELEGRAM_CHAT_ID` (read once, for migration only) and
  auto-approve that chat.
- Extended `tests/fakes.py` additively (new optional constructor params:
  `chat_type`, `user_id`, `chat_member_status` — all defaulting to values
  that preserve every existing caller's behavior unchanged) so group-admin
  scenarios could be tested without touching any Phase 0 test file.
- Wrote `tests/test_multi_tenant.py` (28 tests): storage-level cross-tenant
  isolation, the full access request/approve/deny flow, `/forget`,
  `/timezone`, and group-admin restriction — all passing on the first run.
- Ran mypy against every touched module; fixed the handful of genuinely new
  type errors from my own code (widened three read-only "flight summary"
  parameters from `dict` to `Mapping[str, Any]` in `scheduler.py`,
  `flight_api.py`, and `change_detection.py`, since a `FlightProvider`'s
  `FlightSnapshot` `TypedDict` isn't structurally assignable to a plain
  `dict` parameter under mypy even though it behaves like one at runtime).

**What I decided and why**
- **This was, by a wide margin, the most test-file breakage of any phase —
  20 Phase 0 tests, all `xfail`, all justified by the phase's own explicit
  mandate.** `HARDENING_PLAN.md` doesn't say "add multi-tenancy carefully to
  minimize test churn" — it says *"Remove the global TELEGRAM_CHAT_ID"* and
  CLAUDE.md says *"There is no global 'the chat' any more."* Both are
  unconditional. I considered (and rejected) keeping the old unscoped
  `storage.add_flight()`/`load_flights()` around as a compatibility shim for
  the importer or for tests: it wouldn't actually have saved the
  `test_bot_handlers.py` tests that call it directly for fixture setup
  (they'd still need a `chat_id` that matches what the handler under test
  looks up), and keeping genuinely-superseded single-tenant code paths alive
  purely to dodge `xfail` bookkeeping is exactly the kind of "keep dead code
  to avoid a hard conversation" move `CLAUDE.md` and this project's own
  hardening philosophy argue against. I did add one real, low-cost mitigation
  instead: an autouse `approved_default_chat` fixture (`tests/conftest.py`)
  that pre-approves the default `FakeUpdate` chat_id, which recovered five
  handler tests (`test_list_flights_empty`, `test_by_country_requires_argument`,
  both `test_status_reports_*`, `test_budget_reports_usage_and_days_left`)
  for free, since they only exercise handlers and never call the changed
  storage functions directly — that's a legitimate infra fix (adapting test
  isolation to a new precondition), not a workaround for the changed
  functions themselves.
- **Fan-out is deduped by flight, not by (flight, chat).** Change detection
  and the `change_events` dedupe/retry record are keyed by
  `(flight_iata, scheduled_date, field, new_value)` — properties of the
  *flight*, not of any one subscriber — and the message is composed once
  per pending-changes batch, then sent to each current subscriber in a loop.
  A newly-subscribed chat that joins after a change was already marked
  `sent=1` won't get that historical alert (they can `/status` for current
  info) — this mirrors the existing "first check is a silent baseline"
  behavior and avoids needing a per-(flight, chat) delivery-tracking table,
  which would be real added complexity for a benefit (replaying history to
  late joiners) nobody asked for.
- **A partial fan-out failure isn't perfectly exactly-once.** If sending to
  subscriber 2 of 3 raises, the exception propagates immediately (matching
  Phase 3's existing "don't mark sent on failure, let the next poll retry
  everything" philosophy) — but subscriber 1, who already received it
  successfully, would receive it *again* on the retried poll. Building true
  per-recipient delivery tracking would fix this but is disproportionate for
  a hobby-scale bot where a handful of family members might occasionally get
  one duplicate message during a rare mid-fan-out failure, versus the
  alternative of a subscriber silently never getting notified at all. Noted
  as a known, accepted limitation rather than silently shipped.
- **Access re-checked at subscribe-time, not at every poll.** `check_all_flights`
  fans out to whoever currently has a subscription row, without re-verifying
  that chat's access status is still `'approved'` on every tick. Since only
  an approved chat could have created the subscription (`/add` is gated),
  and `/forget` is the only way to remove one's own subscriptions, this
  should be equivalent in practice — but it's not literally re-verified per
  poll, so I documented it explicitly in `ARCHITECTURE.md` rather than
  asserting it's airtight.
- **Admins are exactly `ALLOWED_CHAT_IDS`, with no separate roles.** The
  plan asks for "an admin approval flow" without specifying who the admins
  are beyond "the operator" — reusing the already-necessary
  bootstrap-trust-anchor (`ALLOWED_CHAT_IDS`, which has to exist for the
  operator to use the bot at all before anyone requests access) avoids
  inventing a second, separate admin-role concept for a single-operator
  hobby project.
- **Approval/denial notifications and admin broadcasts are best-effort.**
  `/approve`, `/deny`, and the budget-exhaustion warning all wrap their
  `send_message` calls in a broad `except Exception` (with `# noqa: BLE001`
  explaining why) — the decision/state change already happened and
  shouldn't be undone or blocked just because notifying the other party
  failed (e.g. they blocked the bot).

**What I deliberately did not do**
- Did not build inline-keyboard approve/deny buttons — plain
  `/approve <chat_id>` / `/deny <chat_id>` commands satisfy "an admin
  approval flow" without the added complexity of `CallbackQueryHandler`s and
  callback-data encoding. A nicer UX, not a missing requirement.
- Did not register a separate, admin-only `set_my_commands` scope (e.g. via
  `BotCommandScopeChat`) that would surface `/approve`/`/deny` to admins
  specifically — the plan only asks for command list registration, not
  per-role scoping.
- Did not build per-(flight, chat) delivery tracking for exactly-once
  fan-out — see above.
- Did not add a way to reassign an already-imported legacy subscription's
  `chat_id` if `TELEGRAM_CHAT_ID` wasn't set at import time (they land under
  the literal chat_id `"legacy"`, inaccessible until manually fixed) — a
  real gap for that specific upgrade edge case, called out in
  `storage/importer.py`'s docstring rather than silently accepted.
- Did not attempt to fix the ~50 pre-existing mypy `union-attr` errors in
  `bot.py` (`update.message`/`update.effective_chat`/`update.effective_user`
  typed `Optional` by `python-telegram-bot`'s own stubs, accessed without a
  guard in code that predates this entire hardening effort) — fixing them
  properly means an `assert update.message is not None`-style guard (or
  equivalent) in nearly every handler, a large mechanical change with no
  single natural phase home in `HARDENING_PLAN.md`. Flagging this explicitly
  in `HANDOFF.md` as unfinished typing work rather than working around it
  quietly.

## Phase 3 — Correctness of alerts

**What I did**
- Branched `harden/phase-3-alert-correctness` from Phase 2's tip.
- Added `change_detection.py` (pure logic: `detect_changes`,
  `format_alert_message`) and `timezones.py` (pure rendering:
  `render_dual`), both fully unit-tested with no storage/bot/network
  involved (`tests/test_change_detection.py`, `tests/test_timezones.py`).
- Added a migration (version 3) adding `sent` to `change_events`, and three
  storage functions (`record_pending_change`, `get_pending_changes`,
  `mark_changes_sent`) implementing durable, crash-safe alert dedupe.
- Rewrote `check_all_flights`'s alerting section in `bot.py` to use these;
  wired `timezones.render_dual` into `flight_api.format_message()` for
  `/status`'s estimated-time lines.
- Wrote `tests/test_alert_persistence.py`: end-to-end tests through
  `bot.check_all_flights` for bundling, no-resend-once-sent, "recorded
  before send is attempted", and — the one HARDENING_PLAN.md explicitly
  asked for — a simulated crash mid-notification (the send raises,
  as if the process died) followed by a simulated restart (a fresh poll),
  asserting the alert is retried exactly once: not lost, not duplicated.

**What I decided and why**
- **Found and fixed a real bug in my own first draft before it shipped**:
  my initial design only checked for pending/unsent alerts inside the `if
  previous != key_fields` branch, meaning a crash between recording a
  change and sending it would never be retried on a later poll where
  nothing *new* happened to differ (the snapshot was already updated to the
  new value, so a plain re-diff finds nothing). I caught this while writing
  the crash-and-restart test — before running it, by reasoning through what
  it needed to prove — and moved the pending-changes check to run
  unconditionally every poll. The test in `test_alert_persistence.py` now
  exercises exactly this path and would have caught the bug if I'd shipped
  the first version.
- **Debounce implemented as "bundle everything in one poll", not a wall-clock
  timer.** HARDENING_PLAN.md asks for "rapid successive changes... debounced
  into one message within a 60-second window." Given `SCHEDULER_TICK_MINUTES`
  (default 15) and `CHECK_INTERVAL_MINUTES`/`FAR_TIER_MINUTES` (30/120) are
  always far more than 60 seconds apart, two *automatic* polls can never
  actually land within 60 seconds of each other in this bot's real operation
  — so a genuine time-windowed debounce (which would need a deferred-send
  mechanism, e.g. "wait N seconds after the first change before composing
  the message") would add real complexity to solve a case that can't occur
  yet. Bundling everything detected in one poll (which *is* effectively
  instantaneous — one synchronous pass over one flight) satisfies the
  requirement for every case this architecture can currently produce. If
  Phase 5 or later introduces concurrent/overlapping triggers (e.g. webhook
  push arriving between two polls, or a manual `/status` some day writing to
  the same alert state), this decision should be revisited.
- **`SUBSCRIBER_TIMEZONE` is one global env var, not a per-chat setting.**
  HARDENING_PLAN.md's Phase 3 prompt asks to render times in "the
  subscriber's configured timezone", but there's no per-chat
  subscription/settings model until Phase 4 introduces chat_id scoping and
  (per its own prompt) a `/timezone` command. Building real per-chat timezone
  storage now would mean doing part of Phase 4's data-model work early and
  probably redoing it once chat_id scoping lands. Every function that needs
  a subscriber timezone (`timezones.render_dual`,
  `change_detection.format_alert_message`) already takes it as an explicit
  parameter with the global env var only as the *default* — Phase 4 replacing
  the global with a per-chat lookup should be a call-site change, not a
  signature change.
- **A gate being assigned for the first time doesn't alert.** This was a
  deliberate reading of CLAUDE.md's exact wording — "Only non-null ->
  different non-null... produce a message" — which excludes `None -> value`
  as well as `value -> None`, not just the latter. I flagged this
  explicitly (in `ARCHITECTURE.md` and a dedicated test) since it's a real,
  possibly-surprising usability tradeoff (a family member won't be told
  about a gate assignment that appears after the baseline was already
  recorded) that the project owner may want revisited even though it's what
  the invariant as written implies.
- Followed `CLAUDE.md`'s hard-stop rule literally even where the Phase 0
  test's own docstring anticipated and welcomed this exact fix
  (`test_alert_fires_on_value_to_null_transition`) — marked `xfail`, did not
  edit, per `FINDINGS.md` #5.

**What I deliberately did not do**
- Did not build a real wall-clock debounce/deferred-send mechanism — see
  above.
- Did not implement a per-chat `/timezone` command or chat_id-scoped
  timezone storage — Phase 4's job.
- Did not change `scheduler.py`'s tiering/backoff logic at all — Phase 3 is
  about *whether an already-fetched result is alert-worthy*, not *when to
  fetch*. That's Phase 5.
- Did not add retry/backoff for the Telegram `send_message` call itself
  (e.g. handling `RetryAfter`) — that's explicitly Phase 5 scope
  ("Handle Telegram RetryAfter"). Phase 3 only makes sure a failed send
  doesn't lose or duplicate the underlying alert; it doesn't make the send
  itself more resilient.

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
