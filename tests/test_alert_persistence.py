"""End-to-end characterization of the durable, crash-safe alert pipeline
through bot.check_all_flights -- dedupe-before-send, bundling multiple
simultaneous field changes into one message (the "debounce" requirement),
and a simulated crash/restart mid-notification that must not lose or replay
an alert. Pure-logic rules already covered by tests/test_change_detection.py
aren't re-tested here.

Updated for Phase 4: there's no more single global CHAT_ID -- check_all_flights
fans a flight's alert out to every chat subscribed to it, so these tests
create a subscription (storage.add_flight(chat_id, ...)) directly rather than
relying on a bot-level constant."""

import storage
from tests.fakes import FakeContext

TEST_CHAT_ID = "111"


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


def _get_bot(monkeypatch):
    import bot

    monkeypatch.setattr(bot, "MONTHLY_REQUEST_CAP", 100)
    monkeypatch.setattr(bot, "REQUEST_SAFETY_MARGIN", 5)
    monkeypatch.setattr(bot.scheduler, "is_due", lambda *a, **k: True)
    return bot


async def test_simultaneous_field_changes_are_bundled_into_one_message(monkeypatch):
    bot = _get_bot(monkeypatch)
    storage.add_flight(TEST_CHAT_ID, "Mom", "RJ264", "2026-08-05")
    responses = iter(
        [
            _raw_flight(),
            _raw_flight(
                flight_status="active",
                departure={**_raw_flight()["departure"], "gate": "14"},
            ),
        ]
    )
    monkeypatch.setattr(
        bot.flight_api, "get_flight_status", lambda *a, **k: next(responses)
    )

    await bot.check_all_flights(FakeContext())  # baseline
    context = FakeContext()
    await bot.check_all_flights(context)

    context.bot.send_message.assert_awaited_once()  # one message, not two
    kwargs = context.bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == TEST_CHAT_ID
    assert "Status: ACTIVE" in kwargs["text"]
    assert "Departure gate: 14" in kwargs["text"]


async def test_a_change_already_sent_is_never_resent(monkeypatch):
    bot = _get_bot(monkeypatch)
    storage.add_flight(TEST_CHAT_ID, "Mom", "RJ264", "2026-08-05")
    responses = iter([_raw_flight(), _raw_flight(flight_status="active")])
    monkeypatch.setattr(
        bot.flight_api, "get_flight_status", lambda *a, **k: next(responses)
    )

    await bot.check_all_flights(FakeContext())  # baseline
    await bot.check_all_flights(FakeContext())  # status change -> sent

    # Third poll: nothing new changes (still "active"), and the send channel
    # for this fake context would raise if called -- proves no resend.
    context = FakeContext()
    context.bot.send_message.side_effect = AssertionError(
        "must not resend an already-sent change"
    )
    monkeypatch.setattr(
        bot.flight_api,
        "get_flight_status",
        lambda *a, **k: _raw_flight(flight_status="active"),
    )
    await bot.check_all_flights(context)
    context.bot.send_message.assert_not_awaited()


async def test_change_is_recorded_before_send_is_attempted(monkeypatch):
    """The core of CLAUDE.md invariant #1: persisted first, so the send
    itself can be interrupted without losing the dedupe record."""
    bot = _get_bot(monkeypatch)
    storage.add_flight(TEST_CHAT_ID, "Mom", "RJ264", "2026-08-05")
    responses = iter([_raw_flight(), _raw_flight(flight_status="active")])
    monkeypatch.setattr(
        bot.flight_api, "get_flight_status", lambda *a, **k: next(responses)
    )

    context = FakeContext()

    async def _send_and_check_already_recorded(*args, **kwargs):
        pending = storage.get_pending_changes("RJ264", "2026-08-05")
        assert any(
            p["field"] == "status" and p["new_value"] == "active" for p in pending
        )

    context.bot.send_message.side_effect = _send_and_check_already_recorded

    await bot.check_all_flights(FakeContext())  # baseline
    await bot.check_all_flights(context)  # triggers the assertion above mid-send


async def test_crash_before_send_completes_is_retried_next_poll_not_lost_or_duplicated(
    monkeypatch,
):
    """Simulates a crash/restart mid-notification: the send raises (as if
    the process died mid-delivery) after the change was already durably
    recorded. The next poll -- even with no *new* field change -- must
    retry the still-pending alert exactly once, not zero times (lost) and
    not more than once (duplicated)."""
    bot = _get_bot(monkeypatch)
    storage.add_flight(TEST_CHAT_ID, "Mom", "RJ264", "2026-08-05")
    monkeypatch.setattr(
        bot.flight_api, "get_flight_status", lambda *a, **k: _raw_flight()
    )
    await bot.check_all_flights(FakeContext())  # baseline

    monkeypatch.setattr(
        bot.flight_api,
        "get_flight_status",
        lambda *a, **k: _raw_flight(flight_status="active"),
    )
    crash_context = FakeContext()
    crash_context.bot.send_message.side_effect = ConnectionError(
        "simulated crash mid-send"
    )
    try:
        await bot.check_all_flights(crash_context)
    except ConnectionError:
        pass

    # The change survived the "crash": it's durably pending, and the
    # snapshot already reflects the new status (so a naive re-diff wouldn't
    # find it again -- only the pending-changes reconciliation would).
    pending_after_crash = storage.get_pending_changes("RJ264", "2026-08-05")
    assert len(pending_after_crash) == 1
    assert pending_after_crash[0]["new_value"] == "active"
    assert storage.get_flight_state("RJ264", "2026-08-05")["status"] == "active"

    # "Restart": next poll, same summary (no new diff at all). Must retry
    # the still-pending alert exactly once.
    retry_context = FakeContext()
    await bot.check_all_flights(retry_context)

    retry_context.bot.send_message.assert_awaited_once()
    assert "ACTIVE" in retry_context.bot.send_message.call_args.kwargs["text"]
    assert storage.get_pending_changes("RJ264", "2026-08-05") == []

    # A third poll must not send anything more -- the retried alert is now
    # confirmed sent.
    final_context = FakeContext()
    await bot.check_all_flights(final_context)
    final_context.bot.send_message.assert_not_awaited()


async def test_terminal_status_alerts_even_with_no_prior_status_known(monkeypatch):
    """The status whitelist: a flight whose very first successfully-checked
    field snapshot already shows a terminal status must still alert on the
    *next* poll once a baseline exists -- this test drives that through two
    real polls rather than calling change_detection directly, to prove the
    wiring through storage.get_flight_state (which returns None pre-baseline,
    not a dict with status=None) doesn't accidentally suppress it."""
    bot = _get_bot(monkeypatch)
    storage.add_flight(TEST_CHAT_ID, "Mom", "RJ264", "2026-08-05")
    responses = iter(
        [_raw_flight(flight_status="active"), _raw_flight(flight_status="cancelled")]
    )
    monkeypatch.setattr(
        bot.flight_api, "get_flight_status", lambda *a, **k: next(responses)
    )

    await bot.check_all_flights(FakeContext())  # baseline: active
    context = FakeContext()
    await bot.check_all_flights(context)

    context.bot.send_message.assert_awaited_once()
    text = context.bot.send_message.call_args.kwargs["text"]
    assert text.startswith("❌ Cancelled")


async def test_alert_fans_out_to_every_chat_subscribed_to_the_same_flight(monkeypatch):
    """New in Phase 4: CLAUDE.md's data model note -- "poll the flight once;
    fan out the notification to every subscribed chat" -- two different
    chats tracking the identical (flight_iata, date) both get the update
    from a single poll, each addressed with their own subscriber name."""
    bot = _get_bot(monkeypatch)
    storage.add_flight("111", "Mom", "RJ264", "2026-08-05")
    storage.add_flight("222", "Uncle Khalid", "RJ264", "2026-08-05")
    responses = iter([_raw_flight(), _raw_flight(flight_status="active")])
    monkeypatch.setattr(
        bot.flight_api, "get_flight_status", lambda *a, **k: next(responses)
    )

    await bot.check_all_flights(FakeContext())  # baseline (one lookup, not two)
    context = FakeContext()
    await bot.check_all_flights(context)

    assert context.bot.send_message.await_count == 2
    sent_by_chat = {
        call.kwargs["chat_id"]: call.kwargs["text"]
        for call in context.bot.send_message.await_args_list
    }
    assert set(sent_by_chat) == {"111", "222"}
    assert "Mom" in sent_by_chat["111"]
    assert "Uncle Khalid" in sent_by_chat["222"]
