# Hardening Plan — Family Flight Tracker

Feed Claude Code **one phase at a time**. Do not paste this whole file as a single
prompt; it will produce a sprawling, untestable diff. Each phase is a branch, a
review, and a merge.

---

## Phase 0 — Safety net (do this first, always)

Before any refactor, lock in current behavior.

**Prompt:**
> Read the whole repo and write `ARCHITECTURE.md` describing what actually exists
> today — modules, data flow, every JSON file's schema, and the exact conditions
> under which an alert fires. Then write characterization tests that capture the
> current change-detection and scheduling behavior using a fake provider, with no
> network calls. Don't change any production code in this phase.

Deliverables: `ARCHITECTURE.md`, `tests/`, `pytest` green, `.gitignore` covering
`.env` and all `*.json` state files.

---

## Phase 1 — Storage: JSON → SQLite

Five JSON files with no atomicity is the single biggest source of future data loss —
a crash mid-write corrupts `state.json` and you either re-alert everything or lose
the baseline.

**Prompt:**
> Replace the JSON file storage with SQLite in WAL mode behind a repository layer.
> Tables: `subscriptions`, `flights`, `change_events`, `api_usage`, `airports`.
> Flights are keyed by `(flight_iata, scheduled_departure_date_utc)`. Add versioned
> migrations and a one-shot importer that reads the existing JSON files into the DB
> and renames them to `*.json.imported`. All existing tests must still pass.

---

## Phase 2 — Provider abstraction + offline airport data

**Prompt:**
> Extract a `FlightProvider` Protocol with `get_flight()`, a declared `QuotaPolicy`,
> and `supports_push`. Move the Aviationstack code behind it. Add a `FakeProvider`
> for tests. Bundle the OurAirports dataset in `static/` and resolve country and
> timezone from it instead of from API lookups — delete `airport_countries.json`
> entirely. Provider is selected by a single config value.

Then research the replacement:

**Prompt:**
> Compare AeroDataBox, FlightAware AeroAPI, Aviation Edge, and OpenSky as providers
> for this bot. Check their *current* free/entry tier quotas and whether they offer
> push/webhook flight alerts — verify against live docs, don't rely on training data.
> Write the findings to `docs/providers.md` with a recommendation.

**This is the decision that makes or breaks the project.** 100 requests/month is
~3 per day for the entire system; every tier, window, and safety-margin knob in the
current README exists only to survive that. A provider with a real quota deletes most
of that machinery. A provider with webhook alerts deletes all of it.

---

## Phase 3 — Correctness of alerts

**Prompt:**
> Rewrite change detection against these rules: alerts fire only on
> `non-null -> different non-null` transitions plus a whitelisted set of status
> changes; every alert is deduped by `(flight_key, field, new_value)` and persisted
> before sending so a restart can't replay it; rapid successive changes to the same
> flight are debounced into one message within a 60-second window; cancelled,
> diverted, and landed are terminal states with distinct copy. Store all times UTC
> and render in both the airport's local timezone and the subscriber's configured
> timezone. Add tests including a simulated crash-and-restart mid-notification.

---

## Phase 4 — Multi-user and access control

The current single `TELEGRAM_CHAT_ID` in `.env` is fine for you and fatal for anyone
who publishes it — the bot token is public-facing, so any stranger who finds the bot
can issue commands.

**Prompt:**
> Remove the global `TELEGRAM_CHAT_ID`. Every subscription belongs to the `chat_id`
> that created it, and no handler may read or write another chat's rows. Add an
> access model: `ALLOWED_CHAT_IDS` allowlist plus an admin approval flow for
> `/request_access`. Group chats are supported; admin-only commands are restricted to
> chat admins. Add `/forget` to delete all of a chat's data, and `/timezone` to set
> the render timezone. Register the command list via `setMyCommands`.

---

## Phase 5 — Resilience and the scheduler

**Prompt:**
> Replace the tick-based scheduler with a persisted `next_poll_at` per flight so
> restarts resume exactly where they left off. Add exponential backoff with jitter on
> 429/5xx, a per-provider circuit breaker, and a hard quota gate inside the provider
> layer that raises rather than relying on the scheduler to behave. Handle Telegram
> `RetryAfter`. Add SIGTERM graceful shutdown and a single-instance lock. Structured
> logging with token redaction and a correlation id per poll cycle.

---

## Phase 6 — Packaging and deployment

**Prompt:**
> Add a `pyproject.toml`, a multi-stage Dockerfile running as a non-root user with a
> healthcheck, and a `docker-compose.yml` with a named volume for the SQLite file and
> the `.env` mounted. Add a systemd unit as an alternative for non-Docker users.
> Support Telegram webhook mode in addition to long polling, selected by config.

Webhook mode fits your existing Cloudflare Tunnel setup — the bot stops holding an
outbound connection open and Telegram pushes to `server.yznweb.com` instead.

---

## Phase 7 — Publishable

**Prompt:**
> Prepare this repo for public release: rewrite the README for a stranger (what it
> does, screenshots, quickstart, config reference table, provider comparison,
> troubleshooting), add MIT LICENSE, CONTRIBUTING.md, CHANGELOG.md, issue and PR
> templates, and a GitHub Actions workflow running ruff, mypy --strict, pytest, and a
> docker build on every PR. Scan the full git history for any committed secrets or
> personal data — real names, chat ids, API keys — and report what you find before
> changing anything.

That last check matters: if a token or your family's names ever landed in a commit,
deleting the file now doesn't remove it from history.

---

## Working notes

- Keep `CLAUDE.md` in the repo root so it loads into every session automatically.
- Ask for a plan before each phase and actually read it. The plan is where you catch
  a bad approach cheaply.
- Run the test suite yourself between phases rather than trusting the summary.
- Anything you can't articulate as a test, you don't yet understand well enough to
  let an agent rewrite.
