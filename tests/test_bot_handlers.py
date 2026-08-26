"""Characterizes bot.py's Telegram command handlers, with flight_api/airports
stubbed out so no network call is possible."""

import time_machine

import bot
import flight_api
import storage
from tests.fakes import FakeContext, FakeUpdate


async def test_start_replies_with_chat_id():
    update, context = FakeUpdate(chat_id=999), FakeContext()
    await bot.start(update, context)
    text = update.message.reply_text.call_args[0][0]
    assert "999" in text


async def test_list_flights_empty():
    update, context = FakeUpdate(), FakeContext()
    await bot.list_flights(update, context)
    update.message.reply_text.assert_awaited_once_with(
        "No flights tracked yet. Use /add to add one."
    )


async def test_list_flights_groups_by_route_sorted():
    storage.add_flight("Mom", "RJ264", "2026-08-05", "Jordan", "United States")
    storage.add_flight("Dad", "TK817", "2026-08-06", "United States", "Jordan")
    storage.add_flight("Sara", "RJ100", "2026-08-07", "Jordan", "United States")

    update, context = FakeUpdate(), FakeContext()
    await bot.list_flights(update, context)
    text = update.message.reply_text.call_args[0][0]

    assert text.index("Jordan → United States") < text.index("United States → Jordan")
    assert "Mom — RJ264 on 2026-08-05" in text
    assert "Sara — RJ100 on 2026-08-07" in text


async def test_by_country_requires_argument():
    update, context = FakeUpdate(), FakeContext(args=[])
    await bot.by_country(update, context)
    update.message.reply_text.assert_awaited_once_with(
        "Usage: /bycountry <country name>"
    )


async def test_by_country_matches_case_insensitively_on_either_side():
    storage.add_flight("Mom", "RJ264", "2026-08-05", "Jordan", "United States")
    storage.add_flight("Dad", "TK817", "2026-08-06", "Turkey", "Germany")

    update, context = FakeUpdate(), FakeContext(args=["jordan"])
    await bot.by_country(update, context)
    text = update.message.reply_text.call_args[0][0]
    assert "RJ264" in text
    assert "TK817" not in text


async def test_status_reports_budget_exhausted(monkeypatch):
    def _raise(*a, **k):
        raise flight_api.BudgetExhaustedError(
            "Monthly API budget exhausted (100 requests/month)."
        )

    monkeypatch.setattr(bot.flight_api, "get_flight_status", _raise)
    update, context = FakeUpdate(), FakeContext(args=["RJ264"])
    await bot.status(update, context)
    text = update.message.reply_text.call_args[0][0]
    assert "budget is exhausted" in text


async def test_status_reports_lookup_error_with_reason(monkeypatch):
    def _raise(*a, **k):
        raise flight_api.FlightLookupError("No flight found for RJ264")

    monkeypatch.setattr(bot.flight_api, "get_flight_status", _raise)
    update, context = FakeUpdate(), FakeContext(args=["rj264"])
    await bot.status(update, context)
    text = update.message.reply_text.call_args[0][0]
    assert "Couldn't get status for RJ264" in text
    assert "No flight found for RJ264" in text


async def test_add_flight_rejects_bad_date():
    update, context = FakeUpdate(), FakeContext(args=["Mom", "RJ264", "not-a-date"])
    await bot.add_flight(update, context)
    update.message.reply_text.assert_awaited_once_with(
        "Date must be in YYYY-MM-DD format."
    )
    assert storage.load_flights() == []


async def test_add_flight_falls_back_to_unknown_countries_on_lookup_error(monkeypatch):
    def _raise(*a, **k):
        raise flight_api.FlightLookupError("too far in advance")

    monkeypatch.setattr(bot.flight_api, "get_flight_status", _raise)
    update, context = FakeUpdate(), FakeContext(args=["Mom", "RJ264", "2026-12-25"])
    await bot.add_flight(update, context)

    flights = storage.load_flights()
    assert len(flights) == 1
    assert flights[0]["dep_country"] == "Unknown"
    assert flights[0]["arr_country"] == "Unknown"
    assert "Unknown → Unknown" in update.message.reply_text.call_args[0][0]


async def test_add_flight_resolves_countries_on_successful_lookup(monkeypatch):
    monkeypatch.setattr(
        bot.flight_api,
        "get_flight_status",
        lambda *a, **k: {"departure": {"iata": "AMM"}, "arrival": {"iata": "JFK"}},
    )
    monkeypatch.setattr(
        bot.airports,
        "get_country",
        lambda code: {"AMM": "Jordan", "JFK": "United States"}[code],
    )
    update, context = FakeUpdate(), FakeContext(args=["Mom", "RJ264", "2026-08-05"])
    await bot.add_flight(update, context)

    flights = storage.load_flights()
    assert flights[0]["dep_country"] == "Jordan"
    assert flights[0]["arr_country"] == "United States"


async def test_remove_flight_reports_success_and_failure():
    storage.add_flight("Mom", "RJ264", "2026-08-05")

    update, context = FakeUpdate(), FakeContext(args=["RJ264"])
    await bot.remove_flight(update, context)
    assert "Stopped tracking RJ264" in update.message.reply_text.call_args[0][0]

    update2, context2 = FakeUpdate(), FakeContext(args=["RJ264"])
    await bot.remove_flight(update2, context2)
    assert "wasn't being tracked" in update2.message.reply_text.call_args[0][0]


async def test_budget_reports_usage_and_days_left(monkeypatch):
    monkeypatch.setattr(bot, "MONTHLY_REQUEST_CAP", 100)
    with time_machine.travel("2026-08-01T00:00:00+00:00"):
        storage.increment_usage()
        update, context = FakeUpdate(), FakeContext()
        await bot.budget(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "Used 1/100" in text
        assert "99 left" in text
        assert "30 days" in text  # 2026-08 has 31 days, 1 elapsed
