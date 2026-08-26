# CLAUDE.md — Family Flight Tracker

## What this project is

A self-hostable Telegram bot that tracks flights and notifies a chat when status,
delay, gate, or terminal changes. Currently a personal single-user script backed by
JSON files and the Aviationstack free tier. The goal is a publishable open-source
project that a stranger can clone, configure, and run reliably for months.

## Non-negotiable invariants

1. **Never alert twice for the same change.** Every notification is keyed by
   `(flight_key, field, new_value)` and recorded as sent *before* the send is
   attempted, with reconciliation after. A crash or restart must not replay alerts.
2. **Never alert on missing data.** A field going `value -> null` because the
   provider blipped is not a change. Only `non-null -> different non-null`, plus an
   explicit whitelist of status transitions, produce a message.
3. **Never exceed the provider's quota.** The quota guard is a hard gate in the
   provider layer, not a courtesy check in the scheduler. When exhausted, the bot
   says so plainly instead of going silently dark.
4. **All timestamps are stored in UTC.** Local times are a rendering concern only.
5. **`chat_id` is the tenant boundary.** No query, list, or alert may ever cross
   from one chat's data to another's. There is no global "the chat" any more.
6. **Secrets never enter the repo, logs, or error messages.** Tokens are redacted in
   every log path including exception tracebacks.

## Target architecture

```
telegram/        command handlers, formatting, keyboards (no business logic)
core/            domain: Flight, Subscription, ChangeEvent, change detection
providers/       FlightProvider protocol + aviationstack/, aerodatabox/, fake/
scheduler/       poll loop, next_poll_at computation, backoff, circuit breaker
storage/         SQLite (WAL), migrations, repositories
static/          bundled airports dataset (IATA -> country, tz, name)
config.py        pydantic-settings, validated at boot, fail fast
```

- **Storage is SQLite**, not JSON files. WAL mode, one file, versioned schema
  migrations. The five JSON files collapse into tables; ship a one-time importer so
  existing users don't lose their data.
- **`FlightProvider` is a Protocol**, not an inheritance tree. It exposes
  `get_flight(flight_iata, date) -> FlightSnapshot | None`, a declared
  `quota: QuotaPolicy`, and `supports_push: bool`. Adding a provider means adding one
  file and one config value — no changes anywhere else.
- **Push is a first-class mode.** If a provider supports subscription webhooks, the
  poll scheduler is bypassed entirely for its flights. Design the interface so this
  slots in without restructuring; do not hardcode the polling model into the domain.
- **Airport metadata is bundled offline** (OurAirports/OpenFlights CSV, checked into
  `static/`). Country and timezone resolution must cost zero API calls. This removes
  the `airport_countries.json` runtime lookups entirely.

## Data model notes

- A flight is identified by `(flight_iata, scheduled_departure_date_utc)`. A bare
  flight code is ambiguous — two family members can be on `RJ264` on different days.
  Commands that take a bare code must disambiguate via inline keyboard, never guess.
- Many subscriptions can point at one flight. Poll the flight once; fan out the
  notification to every subscribed chat.
- Keep an `api_usage` table (provider, timestamp, endpoint, http_status, counted).
  `/budget` reads from it. Quota windows reset on the provider's calendar, not on
  process start.

## Failure semantics

- 429 and 5xx: exponential backoff with jitter, per-provider circuit breaker.
- 4xx other than 429: do not retry, log once, mark the flight as needing attention.
- Provider returns nothing for a flight repeatedly: after N attempts, tell the
  subscriber the flight can't be found rather than failing silently.
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

- `pytest` + `pytest-asyncio`. A `FakeProvider` driven by recorded JSON fixtures is
  the backbone; no test may hit a real API.
- `time-machine` (or `freezegun`) to test the scheduler tiers, quota window rollover,
  and midnight boundaries.
- Required coverage of behavior, not lines: change detection, alert dedupe across a
  simulated restart, quota exhaustion, tz conversion, cancelled/diverted transitions,
  two chats subscribed to one flight.

## Rules for you, Claude

- **Plan before editing.** For any phase, produce the plan and wait for approval.
- **One phase per branch, small commits, tests in the same commit as the code.**
- Do not scaffold a new project or rewrite everything at once. This is an incremental
  hardening of existing working code — preserve behavior that already works, and write
  a characterization test before changing any logic you don't fully understand.
- Do not invent API response shapes. Read the provider's live docs or a recorded
  fixture; if neither is available, stop and ask.
- Do not add dependencies without saying why in the commit message. Prefer stdlib.
- When you finish a phase, update `ARCHITECTURE.md` and `CHANGELOG.md`.
