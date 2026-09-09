"""Multi-user chat_id tenant isolation.

Covers storage-level scoping (cross-tenant isolation: chat A can never see
or remove chat B's flights), access.py's fixed ALLOWED_CHAT_IDS allowlist,
and the bot.py handlers built on both: access gating, /forget, /timezone,
and admin-only restriction of destructive commands in group chats.
"""

import access
import bot
import storage
from tests.fakes import FakeContext, FakeUpdate

# --- storage: chat_id is a real tenant boundary -----------------------------


def test_load_flights_is_scoped_to_one_chat():
    storage.add_flight("chatA", "Mom", "RJ264", "2026-08-05")
    storage.add_flight("chatB", "Dad", "TK817", "2026-08-06")

    assert [f["flight_iata"] for f in storage.load_flights("chatA")] == ["RJ264"]
    assert [f["flight_iata"] for f in storage.load_flights("chatB")] == ["TK817"]


def test_remove_flight_cannot_remove_another_chats_subscription():
    storage.add_flight("chatA", "Mom", "RJ264", "2026-08-05")

    assert storage.remove_flight("chatB", "RJ264") is False
    assert [f["flight_iata"] for f in storage.load_flights("chatA")] == ["RJ264"]


def test_update_flight_countries_only_touches_the_owning_chats_row():
    storage.add_flight("chatA", "Mom", "RJ264", "2026-08-05")
    storage.add_flight("chatB", "Dad", "RJ264", "2026-08-05")

    storage.update_flight_countries("chatA", "RJ264", "Jordan", "United States")

    assert storage.load_flights("chatA")[0]["dep_country"] == "Jordan"
    assert storage.load_flights("chatB")[0]["dep_country"] == "Unknown"


def test_get_subscribers_returns_every_chat_tracking_the_same_flight():
    storage.add_flight("chatA", "Mom", "RJ264", "2026-08-05")
    storage.add_flight("chatB", "Uncle Khalid", "RJ264", "2026-08-05")
    storage.add_flight("chatA", "Mom", "TK817", "2026-08-06")  # different flight

    subs = storage.get_subscribers("RJ264", "2026-08-05")
    assert {s["chat_id"] for s in subs} == {"chatA", "chatB"}


def test_load_distinct_tracked_flights_deduplicates_across_chats():
    storage.add_flight("chatA", "Mom", "RJ264", "2026-08-05")
    storage.add_flight("chatB", "Uncle Khalid", "RJ264", "2026-08-05")

    assert storage.load_distinct_tracked_flights() == [
        {"flight_iata": "RJ264", "date": "2026-08-05"}
    ]


def test_forget_chat_deletes_only_that_chats_subscriptions():
    storage.add_flight("chatA", "Mom", "RJ264", "2026-08-05")
    storage.add_flight("chatB", "Dad", "TK817", "2026-08-06")

    deleted = storage.forget_chat("chatA")

    assert deleted == 1
    assert storage.load_flights("chatA") == []
    assert [f["flight_iata"] for f in storage.load_flights("chatB")] == ["TK817"]


def test_forget_chat_clears_timezone_settings():
    storage.set_chat_timezone("chatA", "Asia/Amman")

    storage.forget_chat("chatA")

    assert storage.get_chat_timezone("chatA") is None


# --- access.py: fixed allowlist ----------------------------------------------


def test_allowlisted_chat_is_approved():
    access.ALLOWED_CHAT_IDS = frozenset({"admin1"})
    try:
        assert access.is_approved("admin1") is True
    finally:
        access.ALLOWED_CHAT_IDS = frozenset()


def test_unknown_chat_is_not_approved():
    assert access.is_approved("stranger") is False


# --- bot.py: access gating ---------------------------------------------------


async def test_unapproved_chat_is_turned_away_from_list():
    update, context = FakeUpdate(chat_id="unapproved"), FakeContext()
    await bot.list_flights(update, context)
    text = update.message.reply_text.call_args[0][0]
    assert "ALLOWED_CHAT_IDS" in text
    context.bot.send_message.assert_not_called()


async def test_unapproved_chat_cannot_add_a_flight():
    update, context = (
        FakeUpdate(chat_id="unapproved"),
        FakeContext(args=["Mom", "RJ264", "2026-08-05"]),
    )
    await bot.add_flight(update, context)
    assert storage.load_flights("unapproved") == []


async def test_approved_chat_can_list_its_own_flights(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({"approved-chat"}))
    storage.add_flight("approved-chat", "Mom", "RJ264", "2026-08-05")

    update, context = FakeUpdate(chat_id="approved-chat"), FakeContext()
    await bot.list_flights(update, context)

    assert "RJ264" in update.message.reply_text.call_args[0][0]


async def test_approved_chat_cannot_see_another_chats_flights(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({"chatA", "chatB"}))
    storage.add_flight("chatB", "Dad", "TK817", "2026-08-06")

    update, context = FakeUpdate(chat_id="chatA"), FakeContext()
    await bot.list_flights(update, context)

    update.message.reply_text.assert_awaited_once_with(
        "No flights tracked yet. Use /add to add one."
    )


# --- bot.py: /forget ----------------------------------------------------------


async def test_forget_deletes_this_chats_flights_in_a_private_chat(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({"chatA"}))
    storage.add_flight("chatA", "Mom", "RJ264", "2026-08-05")

    update, context = FakeUpdate(chat_id="chatA", chat_type="private"), FakeContext()
    await bot.forget(update, context)

    assert storage.load_flights("chatA") == []
    assert "1" in update.message.reply_text.call_args[0][0]


async def test_forget_in_a_group_requires_admin(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({"groupA"}))
    storage.add_flight("groupA", "Mom", "RJ264", "2026-08-05")

    update = FakeUpdate(chat_id="groupA", chat_type="group")
    context = FakeContext(chat_member_status="member")  # not an admin

    await bot.forget(update, context)

    assert "admin" in update.message.reply_text.call_args[0][0].lower()
    assert storage.load_flights("groupA") != []  # nothing was deleted


async def test_forget_in_a_group_succeeds_for_an_admin(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({"groupA"}))
    storage.add_flight("groupA", "Mom", "RJ264", "2026-08-05")

    update = FakeUpdate(chat_id="groupA", chat_type="group")
    context = FakeContext(chat_member_status="administrator")

    await bot.forget(update, context)

    assert storage.load_flights("groupA") == []


async def test_remove_in_a_group_requires_admin(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({"groupA"}))
    storage.add_flight("groupA", "Mom", "RJ264", "2026-08-05")

    update = FakeUpdate(chat_id="groupA", chat_type="group")
    context = FakeContext(args=["RJ264"], chat_member_status="member")

    await bot.remove_flight(update, context)

    assert "admin" in update.message.reply_text.call_args[0][0].lower()
    assert storage.load_flights("groupA") != []


# --- bot.py: /timezone ---------------------------------------------------------


async def test_timezone_with_no_args_shows_current_default(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({"chatA"}))
    update, context = FakeUpdate(chat_id="chatA"), FakeContext()

    await bot.timezone_cmd(update, context)

    assert "UTC" in update.message.reply_text.call_args[0][0]


async def test_timezone_sets_a_valid_iana_name(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({"chatA"}))
    update, context = FakeUpdate(chat_id="chatA"), FakeContext(args=["Asia/Amman"])

    await bot.timezone_cmd(update, context)

    assert storage.get_chat_timezone("chatA") == "Asia/Amman"
    assert "Asia/Amman" in update.message.reply_text.call_args[0][0]


async def test_timezone_rejects_an_unknown_name(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({"chatA"}))
    update, context = FakeUpdate(chat_id="chatA"), FakeContext(args=["Not/A_Zone"])

    await bot.timezone_cmd(update, context)

    assert storage.get_chat_timezone("chatA") is None
    assert "unknown timezone" in update.message.reply_text.call_args[0][0].lower()
