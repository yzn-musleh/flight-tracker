"""Telegram bot that tracks family flights to Jordan and alerts on status changes."""
import calendar
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import airports
import flight_api
import scheduler
import storage

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("flight_tracker")

SCHEDULER_TICK_MINUTES = int(os.environ.get("SCHEDULER_TICK_MINUTES", "15"))
MONTHLY_REQUEST_CAP = int(os.environ.get("MONTHLY_REQUEST_CAP", "100"))
REQUEST_SAFETY_MARGIN = int(os.environ.get("REQUEST_SAFETY_MARGIN", "5"))
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # where alerts get pushed


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Flight tracker bot is running.\n"
        "/list - show tracked flights, grouped by departure → arrival country\n"
        "/bycountry <country> - only show flights taking off from or landing in that country\n"
        "/status <flight_iata> - check a flight right now\n"
        "/add <name> <flight_iata> <YYYY-MM-DD> - track a new flight\n"
        "/remove <flight_iata> - stop tracking a flight\n"
        "/budget - show remaining monthly API requests\n\n"
        f"Your chat ID is {update.effective_chat.id} "
        "(put this in TELEGRAM_CHAT_ID in your .env file to receive alerts here)."
    )


def _route_label(f: dict) -> str:
    return f"{f.get('dep_country', 'Unknown')} → {f.get('arr_country', 'Unknown')}"


async def list_flights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    flights = storage.load_flights()
    if not flights:
        await update.message.reply_text("No flights tracked yet. Use /add to add one.")
        return

    groups: dict[str, list] = {}
    for f in flights:
        groups.setdefault(_route_label(f), []).append(f)

    lines = []
    for route in sorted(groups):
        lines.append(f"— {route} —")
        for f in groups[route]:
            lines.append(f"  • {f['name']} — {f['flight_iata']} on {f['date']}")
    await update.message.reply_text("\n".join(lines))


async def by_country(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /bycountry <country name>")
        return
    query = " ".join(context.args).strip().lower()
    matches = [
        f
        for f in storage.load_flights()
        if query in f.get("dep_country", "").lower() or query in f.get("arr_country", "").lower()
    ]
    if not matches:
        await update.message.reply_text(f"No tracked flights involve '{' '.join(context.args)}'.")
        return
    lines = [f"• {f['name']} — {f['flight_iata']} ({_route_label(f)}) on {f['date']}" for f in matches]
    await update.message.reply_text("\n".join(lines))


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /status <flight_iata>")
        return
    flight_iata = context.args[0].upper()
    tracked = next((f for f in storage.load_flights() if f["flight_iata"] == flight_iata), None)
    date = tracked["date"] if tracked else None
    name = tracked["name"] if tracked else flight_iata
    try:
        flight = flight_api.get_flight_status(flight_iata, date)
        summary = flight_api.summarize(flight)
        await update.message.reply_text(flight_api.format_message(name, flight_iata, summary))
    except flight_api.BudgetExhaustedError:
        await update.message.reply_text(
            "Monthly API budget is exhausted — no requests left until it resets on the 1st."
        )
    except flight_api.FlightLookupError as e:
        await update.message.reply_text(f"Couldn't get status for {flight_iata}: {e}")


async def budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    usage = storage.load_usage()
    remaining = max(0, MONTHLY_REQUEST_CAP - usage["count"])
    now = datetime.now(timezone.utc)
    days_left = calendar.monthrange(now.year, now.month)[1] - now.day
    await update.message.reply_text(
        f"Used {usage['count']}/{MONTHLY_REQUEST_CAP} Aviationstack requests this month "
        f"({remaining} left, resets in {days_left} day{'s' if days_left != 1 else ''})."
    )


async def add_flight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /add <name> <flight_iata> <YYYY-MM-DD>\n"
            "Use a single word for name, e.g. /add Mom RJ264 2026-08-05"
        )
        return
    name, flight_iata, date = context.args[0], context.args[1], context.args[2]
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("Date must be in YYYY-MM-DD format.")
        return

    flight_iata = flight_iata.upper()
    dep_country = arr_country = "Unknown"
    try:
        flight = flight_api.get_flight_status(flight_iata, date)
        summary = flight_api.summarize(flight)
        dep_country = airports.get_country(summary.get("dep_iata"))
        arr_country = airports.get_country(summary.get("arr_iata"))
    except flight_api.FlightLookupError:
        # No live data yet (common for flights booked far in advance) — countries
        # will backfill automatically once the periodic check finds live data.
        pass

    storage.add_flight(name, flight_iata, date, dep_country, arr_country)
    await update.message.reply_text(
        f"Now tracking {name} — {flight_iata} on {date} ({dep_country} → {arr_country})."
    )


async def remove_flight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /remove <flight_iata>")
        return
    flight_iata = context.args[0]
    if storage.remove_flight(flight_iata):
        await update.message.reply_text(f"Stopped tracking {flight_iata.upper()}.")
    else:
        await update.message.reply_text(f"{flight_iata.upper()} wasn't being tracked.")


async def check_all_flights(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not CHAT_ID:
        return

    # Reserve REQUEST_SAFETY_MARGIN requests for manual /status calls — periodic
    # checks back off before the hard cap so a trip-day /status never gets refused.
    if storage.usage_remaining(MONTHLY_REQUEST_CAP) <= REQUEST_SAFETY_MARGIN:
        usage = storage.load_usage()
        if not usage.get("warned"):
            storage.mark_usage_warned()
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=(
                    "⚠️ Monthly Aviationstack request budget is nearly exhausted. "
                    "Periodic checks are paused until it resets on the 1st "
                    "(manual /status still works with the requests held in reserve)."
                ),
            )
        log.warning("Monthly budget near cap, pausing periodic checks.")
        return

    flights = storage.load_flights()
    state = storage.load_state()
    now = datetime.now(timezone.utc)

    for f in flights:
        flight_iata = f["flight_iata"]
        sched = storage.get_flight_schedule(flight_iata)
        if not scheduler.is_due(f, sched, now):
            continue

        try:
            flight = flight_api.get_flight_status(flight_iata, f.get("date"))
            summary = flight_api.summarize(flight)
        except flight_api.BudgetExhaustedError as e:
            log.warning("Monthly budget exhausted mid-run, stopping periodic checks: %s", e)
            return
        except flight_api.FlightLookupError as e:
            log.warning("Lookup failed for %s: %s", flight_iata, e)
            storage.update_flight_schedule(flight_iata, last_checked=now.isoformat())
            continue

        storage.update_flight_schedule(
            flight_iata,
            last_checked=now.isoformat(),
            dep_scheduled=summary.get("dep_scheduled") or sched.get("dep_scheduled"),
            arr_scheduled=summary.get("arr_scheduled") or sched.get("arr_scheduled"),
            done=scheduler.mark_done(summary),
        )

        key_fields = {
            k: summary[k]
            for k in (
                "status",
                "dep_delay",
                "arr_delay",
                "dep_gate",
                "arr_gate",
                "dep_estimated",
                "arr_estimated",
            )
        }
        if f.get("dep_country", "Unknown") == "Unknown" or f.get("arr_country", "Unknown") == "Unknown":
            dep_country = airports.get_country(summary.get("dep_iata"))
            arr_country = airports.get_country(summary.get("arr_iata"))
            storage.update_flight_countries(flight_iata, dep_country, arr_country)

        previous = state.get(flight_iata)

        if previous != key_fields:
            state[flight_iata] = key_fields
            storage.save_state(state)
            if previous is not None:  # skip alert on the very first check, just record a baseline
                text = "🔔 Update:\n" + flight_api.format_message(f["name"], flight_iata, summary)
                await context.bot.send_message(chat_id=CHAT_ID, text=text)
            log.info("Recorded state for %s", flight_iata)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in your .env file first.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_flights))
    app.add_handler(CommandHandler("bycountry", by_country))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("add", add_flight))
    app.add_handler(CommandHandler("remove", remove_flight))
    app.add_handler(CommandHandler("budget", budget))

    if app.job_queue:
        app.job_queue.run_repeating(check_all_flights, interval=SCHEDULER_TICK_MINUTES * 60, first=10)

    log.info(
        "Bot starting, scheduler tick every %s minutes (flights only polled inside their active window).",
        SCHEDULER_TICK_MINUTES,
    )
    app.run_polling()


if __name__ == "__main__":
    main()
