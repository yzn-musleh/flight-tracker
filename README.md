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
3. Leave `TELEGRAM_CHAT_ID` blank for now — you'll get it in step 5.

## 4. Install and run

```bash
pip install -r requirements.txt
python bot.py
```

Leave this running. For it to keep working while your laptop is closed,
either run it on a small always-on machine (a Raspberry Pi, an old PC, or a
cheap VPS), or use Windows Task Scheduler to start it at login.

## 5. Connect it to your family chat

1. Open a chat with your bot in Telegram (or add it to a family group) and send `/start`.
2. It replies with your chat ID. Put that in `TELEGRAM_CHAT_ID` in `.env`, then restart the bot.
   This is the chat that will receive alerts.

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

- `/list` — show everyone currently tracked, grouped by departure country → arrival country (e.g. all "United States → Jordan" flights together, all "Jordan → United States" return flights together)
- `/bycountry Jordan` — only show flights taking off from or landing in a given country
- `/status RJ264` — check a flight right now
- `/add <name> <flight_iata> <YYYY-MM-DD>` — track a new flight
- `/remove RJ264` — stop tracking a flight
- `/budget` — show how many of this month's Aviationstack requests are used up

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

The first check for a flight just records a baseline silently; after that,
any change (status, delay, gate) triggers a message to your chat.

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
