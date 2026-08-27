# Family Flight Tracker (Telegram Bot)

Tracks your family's flights to Jordan and messages you on Telegram when a
status, delay, or gate changes. Also lets you check any flight on demand.

## 1. Create a Telegram bot

1. In Telegram, message **@BotFather** → `/newbot` → follow the prompts.
2. Copy the token it gives you (looks like `123456789:AAExxxxx...`).

## 2. Get an Aviationstack API key (free tier: 100 requests/month)

1. Sign up at https://aviationstack.com/ and copy your API access key from the dashboard.
2. Free tier limits: 100 requests/month, 1 request per 60 seconds. The bot
   self-throttles to live within this (see "How alerts work" below), so you
   can leave it running continuously all month — no need to hand-tune the
   interval or only run it around travel dates.

## 3. Configure

1. Copy `.env.example` to `.env`.
2. Fill in `TELEGRAM_BOT_TOKEN` and `AVIATIONSTACK_API_KEY`.
3. Leave `ALLOWED_CHAT_IDS` blank for now — you'll get your chat ID in step 5.

## 4. Install and run

```bash
pip install -r requirements.txt
python bot.py
```

Leave this running. For it to keep working while your laptop is closed,
either run it on a small always-on machine (a Raspberry Pi, an old PC, or a
cheap VPS), or use Windows Task Scheduler to start it at login.

## 5. Approve your own chat

The bot supports multiple independent chats/groups (each only ever sees its
own tracked flights), so every chat needs approval before it can do anything.

1. Open a chat with your bot in Telegram (or add it to a family group) and
   send `/start`. It replies with that chat's ID.
2. Put that ID in `ALLOWED_CHAT_IDS` in `.env` (comma-separate multiple IDs
   if more than one chat should be an operator/admin), then restart the bot.
   This chat is now always approved and can also approve others.
3. Any other chat that wants to use the bot sends `/request_access` — you'll
   get a notification with `/approve <chat_id>` / `/deny <chat_id>` to
   decide.

## 6. Add flights to track

In the Telegram chat, use:

```
/add Mom RJ264 2026-08-05
/add Sara TK817 2026-08-10
```

Use a single word per name (underscores are fine, e.g. `Uncle_Khalid`).
Flight code is the IATA flight number (airline code + number, e.g. `RJ264` for
Royal Jordanian 264).

## Commands

- `/list` — show everyone *this chat* is currently tracking, grouped by departure country → arrival country (e.g. all "United States → Jordan" flights together, all "Jordan → United States" return flights together)
- `/bycountry Jordan` — only show this chat's flights taking off from or landing in a given country
- `/status RJ264` — check a flight right now
- `/add <name> <flight_iata> <YYYY-MM-DD>` — track a new flight
- `/remove RJ264` — stop tracking a flight (group chats: admins only)
- `/forget` — delete all of this chat's tracked flights and settings (group chats: admins only)
- `/timezone [IANA name]` — show or set the timezone flight times are shown in for this chat, e.g. `/timezone Asia/Amman`
- `/budget` — show how many of this month's Aviationstack requests are used up (shared across every chat using this bot)
- `/request_access` — ask the operator to approve this chat
- `/approve <chat_id>`, `/deny <chat_id>` — operator-only, decide a pending request

Every command except `/start` and `/request_access` only works once a chat
is approved — see "Approve your own chat" above. A chat only ever sees and
manages its own tracked flights, never another chat's.

When you `/add` a flight, the bot looks it up immediately and auto-detects
the departure and arrival country from the airport codes — no need to type
countries yourself. If a flight is booked far enough in advance that
Aviationstack doesn't have live data yet, it's added with "Unknown" countries
and filled in automatically the first time the periodic check finds data.

## How alerts work

The bot ticks every `SCHEDULER_TICK_MINUTES`, but it only spends an actual
Aviationstack request on a flight that's inside its **active window** — same
day, or within `PRE_WINDOW_HOURS` of its known scheduled departure. Outside
that window a tracked flight costs nothing at all, however far out it is.

Inside the active window, polling ramps up as the event nears:
- within `CLOSE_EVENT_HOURS` of departure or arrival: every `CHECK_INTERVAL_MINUTES`
- otherwise (still in the window but not imminent): every `FAR_TIER_MINUTES`

Once a flight lands, is cancelled, or `POST_WINDOW_HOURS` pass with no update,
it's marked done and stops being polled for the rest of the month.

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

## Notes

- All state lives in a single SQLite database file, `flights.db` (created
  automatically next to the bot — configurable via the `DB_PATH` env var), no
  need to edit it by hand. If you're upgrading from an older version that used
  `flights.json`/`state.json`/`schedule.json`/`usage.json`/
  `airport_countries.json`, the bot imports them into `flights.db`
  automatically the first time it starts and renames each one to
  `*.json.imported` once done.
- If you outgrow Aviationstack's free tier, `flight_api.py` is a single small
  module — swap in another provider (e.g. AeroDataBox) without touching the bot logic.
