# CLAUDE.md — Family Flight Tracker

## What this project is

A self-hostable Telegram bot for a family tracking each other's flights: it
notifies a chat when status, delay, gate, or terminal changes. A handful of
allowlisted chats, one flight-data provider (Aviationstack, free tier),
SQLite storage, long polling. Not a platform — keep it that size. Resist
adding abstractions (provider protocols, plugin systems, push/webhook modes)
for hypothetical future needs; add them only when a second real need
actually shows up.

## Non-negotiable invariants

1. **Never alert twice for the same change.** Every notification is keyed by
   `(flight_key, field, new_value)` and recorded as sent *before* the send is
   attempted, with reconciliation after. A crash or restart must not replay alerts.
2. **Never alert on missing data.** A field going `value -> null` because the
   provider blipped is not a change. Only `non-null -> different non-null`, plus an
   explicit whitelist of status transitions, produce a message.
3. **Never exceed the provider's quota.** The quota guard is a hard gate in
   `flight_api.py`, not a courtesy check in the scheduler. When exhausted, the bot
   says so plainly instead of going silently dark.
4. **All timestamps are stored in UTC.** Local times are a rendering concern only.
5. **`chat_id` is the tenant boundary.** No query, list, or alert may ever cross
   from one chat's data to another's. There is no global "the chat".
6. **Secrets never enter the repo, logs, or error messages.** Tokens are redacted in
   every log path including exception tracebacks.

## Actual architecture

Flat modules, not packages-within-packages — this is a single small bot, not
a platform:

```
bot.py              command handlers, formatting, scheduler tick, entry point
flight_api.py       Aviationstack HTTP client, quota gate, message formatting
change_detection.py which field changes are alert-worthy
scheduler.py        active-window + tiered polling-interval decisions
resilience.py       retry-with-backoff (HTTP), Telegram RetryAfter handling
access.py           fixed ALLOWED_CHAT_IDS allowlist check
airports.py         offline IATA -> country/timezone lookup
timezones.py        dual (airport + subscriber) time rendering
singleton.py        PID-file single-instance lock
storage/            SQLite (WAL), versioned migrations, repository functions
static/             bundled airports dataset (IATA -> country, tz, name)
```

- **Storage is SQLite**, not JSON files. WAL mode, one file, versioned schema
  migrations in `storage/migrations.py`.
- **One flight-data provider, called directly.** `flight_api.py` talks to
  Aviationstack; `bot.py` calls it directly. Don't reintroduce a
  provider-abstraction layer (Protocol, registry, `FLIGHT_PROVIDER` env var)
  unless a second provider is actually being wired in — a one-provider
  project doesn't need an interface for the provider it doesn't have yet.
- **Access is a fixed allowlist** (`ALLOWED_CHAT_IDS`), not a self-service
  approval workflow. This is a family bot with a handful of known chats, not
  a service strangers sign up for.
- **Long polling only.** No webhook mode. It needs no inbound network access
  and no reverse proxy/TLS setup — the simpler option for a family bot.
- **Airport metadata is bundled offline** (OurAirports/OpenFlights CSV, checked into
  `static/`). Country and timezone resolution must cost zero API calls.

## Data model notes

- A flight is identified by `(flight_iata, scheduled_departure_date_utc)`. A bare
  flight code is ambiguous — two family members can be on `RJ264` on different days.
- Many subscriptions can point at one flight. Poll the flight once; fan out the
  notification to every subscribed chat.
- Keep an `api_usage` table (provider, timestamp, endpoint, http_status, counted).
  `/budget` reads from it. Quota windows reset on the provider's calendar, not on
  process start.

## Failure semantics

- 429 and 5xx: exponential backoff with jitter (`resilience.retry_with_backoff`).
  No circuit breaker — a single-provider, low-request-volume bot doesn't need
  one; backoff alone keeps it well-behaved against a flaky API.
- 4xx other than 429: do not retry, log once, mark the flight as needing attention.
- Provider returns nothing for a flight repeatedly: the lookup error is logged and
  that flight is skipped for the poll cycle rather than blocking the others.
- Diverted, cancelled, and redirected flights are terminal states with their own
  message copy. Delays that push departure across midnight must not create a
  duplicate flight row under the next day's key.

## Coding standards

- Python 3.12+, `async`/`await` throughout, full type hints, `mypy --strict` clean.
- `ruff` for lint and format. No unformatted commits.
- `python-telegram-bot` v21+ async API.
- **HTML parse mode for Telegram messages, not MarkdownV2.** Escaping MarkdownV2 for
  names and airport strings is a persistent source of send failures.
- No bare `except:`. No `print()` — structured logging only.
- Business logic never imports from `telegram/`. Handlers are thin.

## Testing

- `pytest` + `pytest-asyncio`. Tests stub `flight_api.get_flight_status` /
  `requests.get` directly; no test may hit a real API.
- `time-machine` (or `freezegun`) to test the scheduler tiers, quota window rollover,
  and midnight boundaries.
- Required coverage of behavior, not lines: change detection, alert dedupe across a
  simulated restart, quota exhaustion, tz conversion, cancelled/diverted transitions,
  two chats subscribed to one flight.

## Rules for you, Claude

- **Plan before a non-trivial change.** Produce the plan and wait for approval.
- Small commits, tests in the same commit as the code.
- Preserve behavior that already works. Write a characterization test before
  changing any logic you don't fully understand.
- Do not invent API response shapes. Read the provider's live docs or a recorded
  fixture; if neither is available, stop and ask.
- Do not add dependencies without saying why in the commit message. Prefer stdlib.
- Keep this a small, flat, single-provider personal project. When a request would
  reintroduce something removed for that reason (a provider abstraction, an
  access-approval workflow, webhook mode, a circuit breaker), point that out
  before doing it.
