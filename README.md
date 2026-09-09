# Family Flight Tracker (Telegram Bot)

A self-hostable Telegram bot that tracks flights and messages a chat when
status, delay, gate, or terminal changes — instead of everyone individually
refreshing a flight-tracking website. Built for a family tracking each
other's flights: a handful of chats, each with their own tracked flights.

- **Multi-chat, tenant-isolated**: each chat/group only ever sees its own
  tracked flights.
- **Correct by design, not by luck**: alerts are deduped and crash-safe (a
  restart can't replay or lose one), never fire on a provider hiccup (a
  field silently going missing isn't a "change"), and always fire for
  cancelled/diverted/landed even if nothing was known beforehand.
- **Free-tier friendly**: a scheduler that only spends an API request when a
  flight is actually close to departing/arriving, with a hard monthly quota
  gate.
- **Runs anywhere**: Docker, systemd, or `python bot.py` directly.

## Quickstart

1. **Create a Telegram bot.** Message **[@BotFather](https://t.me/BotFather)**
   → `/newbot` → follow the prompts → copy the token
   (looks like `123456789:AAExxxxx...`).
2. **Get a flight-data API key.** Free tier: [Aviationstack](https://aviationstack.com/),
   100 requests/month — sign up and copy your access key.
3. **Configure.** Copy `.env.example` to `.env`, fill in
   `TELEGRAM_BOT_TOKEN` and `AVIATIONSTACK_API_KEY`. Leave `ALLOWED_CHAT_IDS`
   blank for now.
4. **Run it** (see [Running it](#running-it) below):
   ```bash
   docker compose up -d --build
   ```
5. **Allowlist your own chat.** Message your bot `/start` — it replies with
   your chat ID. Put that in `ALLOWED_CHAT_IDS` in `.env` and restart.
6. **Track a flight:**
   ```
   /add Mom RJ264 2026-08-05
   ```

That's the whole path from zero to a working bot.

## Running it

All three read the same `.env`.

**Quickest, for trying it out:**
```bash
pip install -r requirements.txt
python bot.py
```
Leave this running; closing the terminal stops the bot.

**Docker (recommended for an always-on machine):**
```bash
docker compose up -d --build
```
Builds the multi-stage `Dockerfile` (runs as a non-root user, has a
`HEALTHCHECK`), and stores the SQLite database + lock file in a named
volume (`docker-compose.yml`) so they survive a rebuild. `docker compose
logs -f` to follow the structured JSON logs; `docker compose restart` to
apply an updated `.env`.

**systemd (no Docker, e.g. a Raspberry Pi or a VPS you manage directly):**
See [`deploy/README.md`](deploy/README.md) for the full setup —
`deploy/flight-tracker.service` runs it as a dedicated non-root user with
automatic restart on failure.

## Allowlisting chats

The bot supports multiple independent chats/groups (each only ever sees its
own tracked flights). There's no self-service signup — you (the operator)
add each chat's ID yourself:

1. Open a chat with your bot in Telegram (or add it to a family group) and
   send `/start`. It replies with that chat's ID.
2. Put that ID in `ALLOWED_CHAT_IDS` in `.env` (comma-separate multiple
   IDs), then restart the bot.

## Adding flights

In an allowlisted chat:

```
/add Mom RJ264 2026-08-05
/add Sara TK817 2026-08-10
```

Use a single word per name (underscores are fine, e.g. `Uncle_Khalid`).
Flight code is the IATA flight number (airline code + number, e.g. `RJ264`
for Royal Jordanian 264).

When you `/add` a flight, the bot looks it up immediately and auto-detects
the departure and arrival country from the airport codes — no need to type
countries yourself. If a flight is booked far enough in advance that the
provider doesn't have live data yet, it's added with "Unknown" countries
and filled in automatically the first time the periodic check finds data.

## Commands

| Command | What it does |
|---|---|
| `/start` | Show help and this chat's ID |
| `/list` | List *this chat's* tracked flights, grouped by departure → arrival country |
| `/bycountry <country>` | Only show this chat's flights involving a given country |
| `/status <flight_iata>` | Check a flight right now (costs one API request) |
| `/add <name> <flight_iata> <YYYY-MM-DD>` | Track a new flight |
| `/remove <flight_iata>` | Stop tracking a flight (group chats: admins only) |
| `/forget` | Delete all of this chat's tracked flights and settings (group chats: admins only) |
| `/timezone [IANA name]` | Show or set the timezone flight times are shown in for this chat, e.g. `/timezone Asia/Amman` |
| `/budget` | Show how many of this month's API requests are used (shared across every chat using this bot) |

Every command except `/start` only works once a chat is in
`ALLOWED_CHAT_IDS` — see [Allowlisting chats](#allowlisting-chats). A chat
only ever sees and manages its own tracked flights, never another chat's.

## How alerts work

The bot ticks every `SCHEDULER_TICK_MINUTES`, but it only spends an actual
API request on a flight that's inside its **active window** — same day, or
within `PRE_WINDOW_HOURS` of its known scheduled departure. Outside that
window a tracked flight costs nothing at all, however far out it is.

Inside the active window, polling ramps up as the event nears:
- within `CLOSE_EVENT_HOURS` of departure or arrival: every `CHECK_INTERVAL_MINUTES`
- otherwise (still in the window but not imminent): every `FAR_TIER_MINUTES`

Once a flight lands, is cancelled, or `POST_WINDOW_HOURS` pass with no
update, it's marked done and stops being polled for the rest of the month.

The bot also tracks how many requests it's used this month
(`MONTHLY_REQUEST_CAP`, default 100) and holds `REQUEST_SAFETY_MARGIN`
requests in reserve — periodic checks pause automatically as the cap
approaches so a manual `/status` during your actual trip never gets refused.
Check `/budget` any time to see usage.

The first check for a flight just records a baseline silently. After that, a
real change to status, delay, gate, or estimated time triggers a message —
but a field going from a known value to unknown (a provider blip) never
does, and a field going from unknown to known only does for status changes
to cancelled/diverted/landed (those always alert, even with no prior status
on record). Times are shown in both the airport's local timezone and this
chat's timezone (`/timezone`, default `SUBSCRIBER_TIMEZONE`/UTC if never set).

Alerts are also crash-safe: every detected change is durably recorded
*before* the bot attempts to send it, and a send that fails or is
interrupted (a crash, a restart, Telegram rate-limiting) is retried on the
next poll rather than lost or sent twice. Requests to Aviationstack retry
with exponential backoff on rate limits (429) and server errors (5xx); any
other error is logged once and the flight is skipped until the next poll.

## Configuration reference

All variables go in `.env` (copy `.env.example` to start). Only
`TELEGRAM_BOT_TOKEN` and `AVIATIONSTACK_API_KEY` are required; everything
else has a working default.

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — (required) | From @BotFather |
| `AVIATIONSTACK_API_KEY` | — (required) | From aviationstack.com |
| `ALLOWED_CHAT_IDS` | *(empty)* | Comma-separated chat IDs allowed to use the bot |
| `DB_PATH` | `flights.db` | SQLite database file path |
| `LOCK_PATH` | `bot.lock` | Single-instance lock file path |
| `SCHEDULER_TICK_MINUTES` | `15` | How often the bot checks whether any flight is due for a poll |
| `CHECK_INTERVAL_MINUTES` | `30` | Poll cadence once within `CLOSE_EVENT_HOURS` of an event |
| `FAR_TIER_MINUTES` | `120` | Poll cadence while in the active window but not yet close |
| `PRE_WINDOW_HOURS` | `6` | Hours before scheduled departure the active window opens |
| `CLOSE_EVENT_HOURS` | `3` | How close counts as "close" for `CHECK_INTERVAL_MINUTES` |
| `POST_WINDOW_HOURS` | `3` | Hours past scheduled/estimated arrival before giving up |
| `MONTHLY_REQUEST_CAP` | `100` | Monthly API request budget |
| `REQUEST_SAFETY_MARGIN` | `5` | Requests held in reserve for manual `/status` |
| `SUBSCRIBER_TIMEZONE` | `UTC` | Default display timezone for a chat that hasn't set its own via `/timezone` |

## Troubleshooting

**"Set TELEGRAM_BOT_TOKEN in your .env file first."** — `.env` is missing or
`TELEGRAM_BOT_TOKEN` isn't set in it. Confirm the file exists next to
`bot.py` (or is mounted into the container / read by systemd's
`WorkingDirectory`).

**"Another instance appears to already be running."** — the single-instance
lock (`LOCK_PATH`, default `bot.lock`) thinks a live process already holds
it. If you're sure nothing else is running, delete the lock file and
restart; if this keeps happening, something is starting the bot twice
(check for both a systemd unit *and* a manual `python bot.py` running, or a
Docker container that didn't fully stop).

**"This chat isn't approved to use this bot."** — expected for any chat
that hasn't been put in `ALLOWED_CHAT_IDS`. Add its chat ID and restart.

**No alerts are arriving, but `/status` works.** — `/status` bypasses the
scheduler entirely and always makes a live request; the periodic checker
only polls a flight inside its *active window* (see
[How alerts work](#how-alerts-work)). If the flight isn't within
`PRE_WINDOW_HOURS` of departure yet, no alert is expected. Also check
`/budget` — periodic checks pause silently (with one warning message to
`ALLOWED_CHAT_IDS`) once the monthly quota is nearly exhausted.

**Times look wrong.** — check `/timezone` for this chat; the default is UTC
until a chat sets its own. Times are always shown in *both* the airport's
local timezone and the chat's timezone, so if only one looks off, check
which one you're reading.

**Upgrading from an older, single-chat version of this bot.** — All state
lives in a single SQLite database file (`flights.db`, `DB_PATH`). If you're
upgrading from a version that used `flights.json`/`state.json`/
`schedule.json`/`usage.json`/`airport_countries.json`, the bot imports them
into `flights.db` automatically the first time it starts (reading your old
`TELEGRAM_CHAT_ID` once, if still set, to assign the imported flights to
that chat) and renames each JSON file to `*.json.imported` once done. You
still need to add that chat to `ALLOWED_CHAT_IDS` yourself.
