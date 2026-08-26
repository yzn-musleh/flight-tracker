"""Characterizes check_all_flights: the periodic polling job that decides
whether to spend a request and whether to alert. This is the highest-value
safety net for the hardening work in later phases (esp. Phase 3, which
rewrites the null-transition and dedupe behavior documented here as bugs)."""

import pytest

import bot
import flight_api
import storage
from tests.fakes import FakeContext


def _raw_flight(**overrides):
    base = {
        "flight_status": "scheduled",
        "airline": {"name": "Royal Jordanian"},
        "departure": {
            "airport": "Queen Alia International",
            "iata": "AMM",
            "scheduled": "2026-08-05T10:00:00+00:00",
            "estimated": None,
            "actual": None,
            "delay": None,
            "terminal": "1",
            "gate": "12",
        },
        "arrival": {
            "airport": "JFK",
            "iata": "JFK",
            "scheduled": "2026-08-05T22:00:00+00:00",
            "estimated": None,
            "actual": None,
            "delay": None,
            "terminal": None,
            "gate": None,
        },
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _bot_config(monkeypatch):
    monkeypatch.setattr(bot, "CHAT_ID", "12345")
    monkeypatch.setattr(bot, "MONTHLY_REQUEST_CAP", 100)
    monkeypatch.setattr(bot, "REQUEST_SAFETY_MARGIN", 5)
    # Isolate from real scheduler timing rules unless a test overrides it --
    # those rules are already covered by tests/test_scheduler.py.
    monkeypatch.setattr(bot.scheduler, "is_due", lambda *a, **k: True)


async def test_no_chat_id_configured_does_nothing():
    bot.CHAT_ID = None
    try:
        context = FakeContext()
        await bot.check_all_flights(context)
        context.bot.send_message.assert_not_awaited()
    finally:
        bot.CHAT_ID = "12345"


async def test_first_check_records_baseline_and_sends_no_alert(monkeypatch):
    storage.add_flight("Mom", "RJ264", "2026-08-05")
    monkeypatch.setattr(
        bot.flight_api, "get_flight_status", lambda *a, **k: _raw_flight()
    )

    context = FakeContext()
    await bot.check_all_flights(context)

    context.bot.send_message.assert_not_awaited()
    assert storage.load_state()["RJ264"]["status"] == "scheduled"
    assert storage.get_flight_schedule("RJ264")["last_checked"] is not None


async def test_no_alert_when_nothing_changed(monkeypatch):
    storage.add_flight("Mom", "RJ264", "2026-08-05")
    monkeypatch.setattr(
        bot.flight_api, "get_flight_status", lambda *a, **k: _raw_flight()
    )

    await bot.check_all_flights(FakeContext())  # baseline
    context = FakeContext()
    await bot.check_all_flights(context)  # identical second read

    context.bot.send_message.assert_not_awaited()


async def test_alert_sent_when_status_changes(monkeypatch):
    storage.add_flight("Mom", "RJ264", "2026-08-05")
    responses = iter([_raw_flight(), _raw_flight(flight_status="active")])
    monkeypatch.setattr(
        bot.flight_api, "get_flight_status", lambda *a, **k: next(responses)
    )

    await bot.check_all_flights(FakeContext())  # baseline, silent
    context = FakeContext()
    await bot.check_all_flights(context)

    context.bot.send_message.assert_awaited_once()
    kwargs = context.bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == "12345"
    assert "ACTIVE" in kwargs["text"]
    assert storage.load_state()["RJ264"]["status"] == "active"


async def test_alert_fires_on_value_to_null_transition(monkeypatch):
    """Documents a known bug (see ARCHITECTURE.md): a field disappearing is
    treated the same as a real change. Phase 3 is expected to fix this --
    if it does, this test should be updated there, not silently deleted."""
    storage.add_flight("Mom", "RJ264", "2026-08-05")
    with_gate = _raw_flight()
    without_gate = _raw_flight()
    without_gate["departure"]["gate"] = None
    responses = iter([with_gate, without_gate])
    monkeypatch.setattr(
        bot.flight_api, "get_flight_status", lambda *a, **k: next(responses)
    )

    await bot.check_all_flights(FakeContext())  # baseline with gate=12
    context = FakeContext()
    await bot.check_all_flights(context)

    context.bot.send_message.assert_awaited_once()


async def test_budget_exhausted_stops_processing_remaining_flights(monkeypatch):
    storage.add_flight("Mom", "RJ264", "2026-08-05")
    storage.add_flight("Dad", "TK817", "2026-08-05")
    calls = []

    def _lookup(flight_iata, date=None):
        calls.append(flight_iata)
        raise flight_api.BudgetExhaustedError("out of budget")

    monkeypatch.setattr(bot.flight_api, "get_flight_status", _lookup)

    await bot.check_all_flights(FakeContext())

    assert calls == ["RJ264"]  # stopped before reaching TK817


async def test_lookup_error_for_one_flight_does_not_block_the_next(monkeypatch):
    storage.add_flight("Mom", "RJ264", "2026-08-05")
    storage.add_flight("Dad", "TK817", "2026-08-05")

    def _lookup(flight_iata, date=None):
        if flight_iata == "RJ264":
            raise flight_api.FlightLookupError("no data yet")
        return _raw_flight()

    monkeypatch.setattr(bot.flight_api, "get_flight_status", _lookup)

    await bot.check_all_flights(FakeContext())

    rj264_sched = storage.get_flight_schedule("RJ264")
    assert rj264_sched["last_checked"] is not None
    assert rj264_sched["done"] is False
    assert "TK817" in storage.load_state()  # second flight's baseline was recorded


async def test_country_backfill_when_unknown(monkeypatch):
    storage.add_flight("Mom", "RJ264", "2026-08-05")  # Unknown/Unknown by default
    monkeypatch.setattr(
        bot.flight_api, "get_flight_status", lambda *a, **k: _raw_flight()
    )
    monkeypatch.setattr(
        bot.airports,
        "get_country",
        lambda code: {"AMM": "Jordan", "JFK": "United States"}[code],
    )

    await bot.check_all_flights(FakeContext())

    flights = storage.load_flights()
    assert flights[0]["dep_country"] == "Jordan"
    assert flights[0]["arr_country"] == "United States"


async def test_skips_flight_when_not_due(monkeypatch):
    storage.add_flight("Mom", "RJ264", "2026-08-05")
    monkeypatch.setattr(bot.scheduler, "is_due", lambda *a, **k: False)

    def _unexpected(*a, **k):
        raise AssertionError("should not look up a flight that isn't due")

    monkeypatch.setattr(bot.flight_api, "get_flight_status", _unexpected)

    await bot.check_all_flights(FakeContext())
    assert storage.load_state() == {}


async def test_usage_margin_gate_pauses_all_polling_and_warns_once(monkeypatch):
    storage.add_flight("Mom", "RJ264", "2026-08-05")

    def _unexpected(*a, **k):
        raise AssertionError("should not spend a request once inside the safety margin")

    monkeypatch.setattr(bot.flight_api, "get_flight_status", _unexpected)

    for _ in range(96):  # 100 cap - 5 margin = 95 allowed; 96th trips the gate
        storage.increment_usage()

    context = FakeContext()
    await bot.check_all_flights(context)
    context.bot.send_message.assert_awaited_once()
    assert "budget" in context.bot.send_message.call_args.kwargs["text"].lower()
    assert storage.load_usage()["warned"] is True

    context2 = FakeContext()
    await bot.check_all_flights(context2)
    context2.bot.send_message.assert_not_awaited()  # warned already, stays silent
