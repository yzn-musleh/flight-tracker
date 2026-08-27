"""Telegram bot that tracks family flights and alerts on status changes."""

import calendar
import logging
import os
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes

import access
import airports
import change_detection
import flight_api
import logging_config
import providers
import resilience
import scheduler
import singleton
import storage
import storage.importer
import timezones

load_dotenv()

logging_config.configure(level=logging.INFO)
log = logging.getLogger("flight_tracker")

SCHEDULER_TICK_MINUTES = int(os.environ.get("SCHEDULER_TICK_MINUTES", "15"))
MONTHLY_REQUEST_CAP = int(os.environ.get("MONTHLY_REQUEST_CAP", "100"))
REQUEST_SAFETY_MARGIN = int(os.environ.get("REQUEST_SAFETY_MARGIN", "5"))
provider = providers.get_provider()


async def _require_access(update: Update) -> bool:
    """Gate for every data-touching command. chat_id is the tenant boundary
    (CLAUDE.md invariant #5) -- an unapproved chat gets a message telling it
    how to ask, not silence and not a peek at anyone's data."""
    chat_id = str(update.effective_chat.id)
    if access.is_approved(chat_id):
        return True
    if access.is_denied(chat_id):
        await update.message.reply_text("Your access request was denied.")
    else:
        await update.message.reply_text(
            "This chat isn't approved to use this bot yet. "
            "Send /request_access to ask the operator."
        )
    return False


async def _is_chat_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Private chats: the single user trivially controls their own chat.
    Group chats: only Telegram admins/creators may run destructive
    commands, so one member can't wipe everyone's tracked flights."""
    chat = update.effective_chat
    if chat.type == "private":
        return True
    member = await context.bot.get_chat_member(chat.id, update.effective_user.id)
    return member.status in ("administrator", "creator")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Flight tracker bot is running.\n"
        "/list - show tracked flights, grouped by departure → arrival country\n"
        "/bycountry <country> - only show flights taking off from or landing in that country\n"
        "/status <flight_iata> - check a flight right now\n"
        "/add <name> <flight_iata> <YYYY-MM-DD> - track a new flight\n"
        "/remove <flight_iata> - stop tracking a flight\n"
        "/budget - show remaining monthly API requests\n"
        "/timezone <IANA name> - set the timezone flight times are shown in for this chat\n"
        "/forget - delete all tracked flights and settings for this chat\n"
        "/request_access - ask the operator to approve this chat\n\n"
        f"Your chat ID is {update.effective_chat.id}."
    )


def _route_label(f: dict) -> str:
    return f"{f.get('dep_country', 'Unknown')} → {f.get('arr_country', 'Unknown')}"


async def list_flights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_access(update):
        return
    flights = storage.load_flights(str(update.effective_chat.id))
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
    if not await _require_access(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /bycountry <country name>")
        return
    query = " ".join(context.args).strip().lower()
    matches = [
        f
        for f in storage.load_flights(str(update.effective_chat.id))
        if query in f.get("dep_country", "").lower()
        or query in f.get("arr_country", "").lower()
    ]
    if not matches:
        await update.message.reply_text(
            f"No tracked flights involve '{' '.join(context.args)}'."
        )
        return
    lines = [
        f"• {f['name']} — {f['flight_iata']} ({_route_label(f)}) on {f['date']}"
        for f in matches
    ]
    await update.message.reply_text("\n".join(lines))


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_access(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /status <flight_iata>")
        return
    chat_id = str(update.effective_chat.id)
    flight_iata = context.args[0].upper()
    tracked = next(
        (f for f in storage.load_flights(chat_id) if f["flight_iata"] == flight_iata),
        None,
    )
    date = tracked["date"] if tracked else None
    name = tracked["name"] if tracked else flight_iata
    try:
        summary = provider.get_flight(flight_iata, date)
        subscriber_tz = storage.get_chat_timezone(chat_id)
        await update.message.reply_text(
            flight_api.format_message(
                name, flight_iata, summary, subscriber_tz=subscriber_tz
            )
        )
    except flight_api.BudgetExhaustedError:
        await update.message.reply_text(
            "Monthly API budget is exhausted — no requests left until it resets on the 1st."
        )
    except flight_api.FlightLookupError as e:
        await update.message.reply_text(f"Couldn't get status for {flight_iata}: {e}")


async def budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_access(update):
        return
    usage = storage.load_usage()
    remaining = max(0, MONTHLY_REQUEST_CAP - usage["count"])
    now = datetime.now(timezone.utc)
    days_left = calendar.monthrange(now.year, now.month)[1] - now.day
    await update.message.reply_text(
        f"Used {usage['count']}/{MONTHLY_REQUEST_CAP} Aviationstack requests this month "
        f"({remaining} left, resets in {days_left} day{'s' if days_left != 1 else ''})."
    )


async def add_flight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_access(update):
        return
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
        summary = provider.get_flight(flight_iata, date)
        dep_country = airports.get_country(summary.get("dep_iata"))
        arr_country = airports.get_country(summary.get("arr_iata"))
    except flight_api.FlightLookupError:
        # No live data yet (common for flights booked far in advance) — countries
        # will backfill automatically once the periodic check finds live data.
        pass

    storage.add_flight(
        str(update.effective_chat.id), name, flight_iata, date, dep_country, arr_country
    )
    await update.message.reply_text(
        f"Now tracking {name} — {flight_iata} on {date} ({dep_country} → {arr_country})."
    )


async def remove_flight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_access(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /remove <flight_iata>")
        return
    if not await _is_chat_admin(update, context):
        await update.message.reply_text("Only group admins can do that.")
        return
    flight_iata = context.args[0]
    if storage.remove_flight(str(update.effective_chat.id), flight_iata):
        await update.message.reply_text(f"Stopped tracking {flight_iata.upper()}.")
    else:
        await update.message.reply_text(f"{flight_iata.upper()} wasn't being tracked.")


async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_access(update):
        return
    if not await _is_chat_admin(update, context):
        await update.message.reply_text("Only group admins can do that.")
        return
    count = storage.forget_chat(str(update.effective_chat.id))
    await update.message.reply_text(
        f"Forgot {count} tracked flight(s) and all settings for this chat."
    )


async def timezone_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_access(update):
        return
    chat_id = str(update.effective_chat.id)
    if not context.args:
        current = (
            storage.get_chat_timezone(chat_id) or timezones.DEFAULT_SUBSCRIBER_TIMEZONE
        )
        await update.message.reply_text(
            f"Current timezone: {current}\nUsage: /timezone <IANA timezone, e.g. Asia/Amman>"
        )
        return
    tz_name = context.args[0]
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        await update.message.reply_text(
            f"Unknown timezone: {tz_name}. Use an IANA name like Asia/Amman or America/New_York."
        )
        return
    storage.set_chat_timezone(chat_id, tz_name)
    await update.message.reply_text(f"Timezone set to {tz_name}.")


async def request_access_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    chat_id = str(update.effective_chat.id)
    result = access.request_access(chat_id)
    if result == "approved":
        await update.message.reply_text("This chat is already approved.")
        return
    if result == "denied":
        await update.message.reply_text("Your access request was previously denied.")
        return
    await update.message.reply_text(
        "Access request sent. You'll be notified once an operator approves it."
    )
    for admin_chat_id in access.ALLOWED_CHAT_IDS:
        try:
            await resilience.send_with_retry(
                lambda admin_chat_id=admin_chat_id: context.bot.send_message(
                    chat_id=admin_chat_id,
                    text=(
                        f"Access request from chat {chat_id}.\n"
                        f"Approve with /approve {chat_id} or deny with /deny {chat_id}."
                    ),
                )
            )
        except Exception as e:  # noqa: BLE001 -- best-effort notify, one admin's failure shouldn't block the rest
            log.warning(
                "Couldn't notify admin chat %s of access request: %s", admin_chat_id, e
            )


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if not access.is_admin(chat_id):
        await update.message.reply_text("Only an operator can do that.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /approve <chat_id>")
        return
    target = context.args[0]
    storage.set_chat_access_status(target, "approved", decided_by=chat_id)
    await update.message.reply_text(f"Approved {target}.")
    try:
        await resilience.send_with_retry(
            lambda: context.bot.send_message(
                chat_id=target,
                text="Your access request was approved. You can now use the bot.",
            )
        )
    except Exception as e:  # noqa: BLE001 -- approval already recorded; a failed notify shouldn't undo it
        log.warning("Couldn't notify chat %s of approval: %s", target, e)


async def deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    if not access.is_admin(chat_id):
        await update.message.reply_text("Only an operator can do that.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /deny <chat_id>")
        return
    target = context.args[0]
    storage.set_chat_access_status(target, "denied", decided_by=chat_id)
    await update.message.reply_text(f"Denied {target}.")


async def check_all_flights(context: ContextTypes.DEFAULT_TYPE) -> None:
    # A correlation id per poll cycle (CLAUDE.md) -- every log line from this
    # invocation carries it, so a support request ("what happened around
    # 14:32?") can be traced through one cycle's worth of log lines even
    # when several flights/chats are involved.
    cycle_log = logging_config.with_correlation_id(log, uuid.uuid4().hex[:8])

    # Reserve REQUEST_SAFETY_MARGIN requests for manual /status calls — periodic
    # checks back off before the hard cap so a trip-day /status never gets refused.
    if storage.usage_remaining(MONTHLY_REQUEST_CAP) <= REQUEST_SAFETY_MARGIN:
        usage = storage.load_usage()
        if not usage.get("warned"):
            storage.mark_usage_warned()
            for admin_chat_id in access.ALLOWED_CHAT_IDS:
                try:
                    await resilience.send_with_retry(
                        lambda admin_chat_id=admin_chat_id: context.bot.send_message(
                            chat_id=admin_chat_id,
                            text=(
                                "⚠️ Monthly Aviationstack request budget is nearly exhausted. "
                                "Periodic checks are paused until it resets on the 1st "
                                "(manual /status still works with the requests held in reserve)."
                            ),
                        )
                    )
                except Exception as e:  # noqa: BLE001 -- best-effort notify, one admin's failure shouldn't block the rest
                    cycle_log.warning(
                        "Couldn't send budget warning to %s: %s", admin_chat_id, e
                    )
        cycle_log.warning("Monthly budget near cap, pausing periodic checks.")
        return

    flights = storage.load_distinct_tracked_flights()
    now = datetime.now(timezone.utc)

    for f in flights:
        flight_iata = f["flight_iata"]
        flight_date: str = f["date"]
        sched = storage.get_flight_schedule(flight_iata, flight_date)
        if not scheduler.is_due(f, sched, now):
            continue

        try:
            summary = provider.get_flight(flight_iata, flight_date)
        except flight_api.BudgetExhaustedError as e:
            cycle_log.warning(
                "Monthly budget exhausted mid-run, stopping periodic checks: %s", e
            )
            return
        except flight_api.FlightLookupError as e:
            cycle_log.warning("Lookup failed for %s: %s", flight_iata, e)
            storage.update_flight_schedule(
                flight_iata,
                flight_date,
                last_checked=now.isoformat(),
                next_poll_at=scheduler.compute_next_poll_at(f, sched, now),
            )
            continue

        storage.update_flight_schedule(
            flight_iata,
            flight_date,
            last_checked=now.isoformat(),
            dep_scheduled=summary.get("dep_scheduled") or sched.get("dep_scheduled"),
            arr_scheduled=summary.get("arr_scheduled") or sched.get("arr_scheduled"),
            done=scheduler.mark_done(summary),
            next_poll_at=scheduler.compute_next_poll_at(f, sched, now),
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

        # Poll the flight once; fan out to every chat subscribed to it.
        subscribers = storage.get_subscribers(flight_iata, flight_date)
        for sub in subscribers:
            if (
                sub.get("dep_country", "Unknown") == "Unknown"
                or sub.get("arr_country", "Unknown") == "Unknown"
            ):
                dep_country = airports.get_country(summary.get("dep_iata"))
                arr_country = airports.get_country(summary.get("arr_iata"))
                storage.update_flight_countries(
                    sub["chat_id"], flight_iata, dep_country, arr_country
                )

        previous = storage.get_flight_state(flight_iata, flight_date)

        if previous is None:
            # First-ever successful check: record a silent baseline, no alert.
            storage.save_flight_state(flight_iata, flight_date, key_fields)
            cycle_log.info("Recorded baseline for %s", flight_iata)
            continue

        if previous != key_fields:
            for change in change_detection.detect_changes(previous, key_fields):
                storage.record_pending_change(
                    flight_iata,
                    flight_date,
                    change.field,
                    change.old_value,
                    change.new_value,
                )
            storage.save_flight_state(flight_iata, flight_date, key_fields)

        # Checked unconditionally, not just when something changed this poll:
        # a crash between recording a change and sending it leaves it pending
        # with no further snapshot diff to re-trigger detection, so this is
        # what actually retries it on the next poll (CLAUDE.md's "recorded as
        # sent before the send is attempted, with reconciliation after").
        pending = storage.get_pending_changes(flight_iata, flight_date)
        if pending:
            for sub in subscribers:
                subscriber_tz = storage.get_chat_timezone(sub["chat_id"])
                text = change_detection.format_alert_message(
                    sub["name"],
                    flight_iata,
                    pending,
                    summary,
                    subscriber_tz=subscriber_tz,
                )
                await resilience.send_with_retry(
                    lambda sub=sub, text=text: context.bot.send_message(
                        chat_id=sub["chat_id"], text=text
                    )
                )
            storage.mark_changes_sent([p["id"] for p in pending])
        cycle_log.info("Recorded state for %s", flight_iata)


async def _post_init(app: Application) -> None:
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Show help"),
            BotCommand("list", "List tracked flights"),
            BotCommand("bycountry", "Filter tracked flights by country"),
            BotCommand("status", "Check a flight right now"),
            BotCommand("add", "Track a new flight"),
            BotCommand("remove", "Stop tracking a flight"),
            BotCommand("budget", "Show remaining monthly API requests"),
            BotCommand("timezone", "Set this chat's display timezone"),
            BotCommand("forget", "Delete all data for this chat"),
            BotCommand("request_access", "Ask the operator to approve this chat"),
        ]
    )


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in your .env file first.")

    try:
        singleton.acquire()
    except singleton.AlreadyRunningError as e:
        raise SystemExit(str(e)) from e

    try:
        storage.importer.run()

        app = Application.builder().token(token).post_init(_post_init).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("list", list_flights))
        app.add_handler(CommandHandler("bycountry", by_country))
        app.add_handler(CommandHandler("status", status))
        app.add_handler(CommandHandler("add", add_flight))
        app.add_handler(CommandHandler("remove", remove_flight))
        app.add_handler(CommandHandler("budget", budget))
        app.add_handler(CommandHandler("timezone", timezone_cmd))
        app.add_handler(CommandHandler("forget", forget))
        app.add_handler(CommandHandler("request_access", request_access_cmd))
        app.add_handler(CommandHandler("approve", approve))
        app.add_handler(CommandHandler("deny", deny))

        if app.job_queue:
            app.job_queue.run_repeating(
                check_all_flights, interval=SCHEDULER_TICK_MINUTES * 60, first=10
            )

        log.info(
            "Bot starting, scheduler tick every %s minutes (flights only polled inside their active window).",
            SCHEDULER_TICK_MINUTES,
        )
        # run_polling() installs SIGINT/SIGTERM/SIGABRT handlers by default
        # on non-Windows platforms (verified against the installed
        # python-telegram-bot's own docstring) and drains in-flight work
        # before exiting -- graceful shutdown on the actual deployment
        # target (Docker/Linux, Phase 6) needs nothing further here.
        app.run_polling()
    finally:
        singleton.release()


if __name__ == "__main__":
    main()
