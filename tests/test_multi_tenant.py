"""New in Phase 4: multi-user access control and chat_id tenant isolation.

Covers storage-level scoping (cross-tenant isolation: chat A can never see
or remove chat B's flights), the access.py approval model, and the bot.py
handlers built on both: access gating, /request_access + /approve + /deny,
/forget, /timezone, and admin-only restriction of destructive commands in
group chats. See FINDINGS.md #6 for why this supersedes most of
test_storage.py's/test_bot_handlers.py's/test_bot_alerts.py's subscription-
and CHAT_ID-related tests rather than editing them.
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


def test_forget_chat_clears_access_and_timezone_settings():
    storage.set_chat_access_status("chatA", "approved")
    storage.set_chat_timezone("chatA", "Asia/Amman")

    storage.forget_chat("chatA")

    assert storage.get_chat_access_status("chatA") is None
    assert storage.get_chat_timezone("chatA") is None


# --- access.py: approval model ----------------------------------------------


def test_allowlisted_chat_is_always_approved_without_requesting():
    access.ALLOWED_CHAT_IDS = frozenset({"admin1"})
    try:
        assert access.is_approved("admin1") is True
        assert access.is_admin("admin1") is True
    finally:
        access.ALLOWED_CHAT_IDS = frozenset()


def test_unknown_chat_is_not_approved():
    assert access.is_approved("stranger") is False


def test_request_access_records_pending_then_stays_stable():
    assert access.request_access("chatA") == "pending"
    assert storage.get_chat_access_status("chatA") == "pending"
    # Asking again doesn't reset anything.
    assert access.request_access("chatA") == "pending"


def test_request_access_reflects_a_prior_decision_without_resetting_it():
    storage.set_chat_access_status("chatA", "denied")
    assert access.request_access("chatA") == "denied"
    assert storage.get_chat_access_status("chatA") == "denied"  # unchanged

    storage.set_chat_access_status("chatB", "approved")
    assert access.request_access("chatB") == "approved"


# --- bot.py: access gating ---------------------------------------------------


async def test_unapproved_chat_is_turned_away_from_list():
    update, context = FakeUpdate(chat_id="unapproved"), FakeContext()
    await bot.list_flights(update, context)
    text = update.message.reply_text.call_args[0][0]
    assert "request_access" in text
    context.bot.send_message.assert_not_called()


async def test_unapproved_chat_cannot_add_a_flight():
    update, context = (
        FakeUpdate(chat_id="unapproved"),
        FakeContext(args=["Mom", "RJ264", "2026-08-05"]),
    )
    await bot.add_flight(update, context)
    assert storage.load_flights("unapproved") == []


async def test_denied_chat_gets_a_specific_message():
    storage.set_chat_access_status("denied-chat", "denied")
    update, context = FakeUpdate(chat_id="denied-chat"), FakeContext()
    await bot.list_flights(update, context)
    assert "denied" in update.message.reply_text.call_args[0][0].lower()


async def test_approved_chat_can_list_its_own_flights():
    storage.set_chat_access_status("approved-chat", "approved")
    storage.add_flight("approved-chat", "Mom", "RJ264", "2026-08-05")

    update, context = FakeUpdate(chat_id="approved-chat"), FakeContext()
    await bot.list_flights(update, context)

    assert "RJ264" in update.message.reply_text.call_args[0][0]


async def test_approved_chat_cannot_see_another_chats_flights():
    storage.set_chat_access_status("chatA", "approved")
    storage.set_chat_access_status("chatB", "approved")
    storage.add_flight("chatB", "Dad", "TK817", "2026-08-06")

    update, context = FakeUpdate(chat_id="chatA"), FakeContext()
    await bot.list_flights(update, context)

    update.message.reply_text.assert_awaited_once_with(
        "No flights tracked yet. Use /add to add one."
    )


# --- bot.py: /request_access, /approve, /deny -------------------------------


async def test_request_access_notifies_admins(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({"admin1", "admin2"}))
    update, context = FakeUpdate(chat_id="newchat"), FakeContext()

    await bot.request_access_cmd(update, context)

    assert "sent" in update.message.reply_text.call_args[0][0].lower()
    notified = {c.kwargs["chat_id"] for c in context.bot.send_message.await_args_list}
    assert notified == {"admin1", "admin2"}
    assert storage.get_chat_access_status("newchat") == "pending"


async def test_request_access_is_idempotent_once_approved(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset())
    storage.set_chat_access_status("chatA", "approved")
    update, context = FakeUpdate(chat_id="chatA"), FakeContext()

    await bot.request_access_cmd(update, context)

    assert "already approved" in update.message.reply_text.call_args[0][0].lower()
    context.bot.send_message.assert_not_called()


async def test_approve_requires_admin(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({"admin1"}))
    update, context = FakeUpdate(chat_id="not-an-admin"), FakeContext(args=["chatA"])

    await bot.approve(update, context)

    assert storage.get_chat_access_status("chatA") is None
    assert "operator" in update.message.reply_text.call_args[0][0].lower()


async def test_approve_by_admin_grants_access_and_notifies_target(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({"admin1"}))
    storage.request_chat_access("chatA")
    update, context = FakeUpdate(chat_id="admin1"), FakeContext(args=["chatA"])

    await bot.approve(update, context)

    assert storage.get_chat_access_status("chatA") == "approved"
    assert context.bot.send_message.call_args.kwargs["chat_id"] == "chatA"


async def test_deny_by_admin_records_denial(monkeypatch):
    monkeypatch.setattr(access, "ALLOWED_CHAT_IDS", frozenset({"admin1"}))
    update, context = FakeUpdate(chat_id="admin1"), FakeContext(args=["chatA"])

    await bot.deny(update, context)

    assert storage.get_chat_access_status("chatA") == "denied"


# --- bot.py: /forget ----------------------------------------------------------


async def test_forget_deletes_this_chats_flights_in_a_private_chat():
    storage.set_chat_access_status("chatA", "approved")
    storage.add_flight("chatA", "Mom", "RJ264", "2026-08-05")

    update, context = FakeUpdate(chat_id="chatA", chat_type="private"), FakeContext()
    await bot.forget(update, context)

    assert storage.load_flights("chatA") == []
    assert "1" in update.message.reply_text.call_args[0][0]


async def test_forget_in_a_group_requires_admin():
    storage.set_chat_access_status("groupA", "approved")
    storage.add_flight("groupA", "Mom", "RJ264", "2026-08-05")

    update = FakeUpdate(chat_id="groupA", chat_type="group")
    context = FakeContext(chat_member_status="member")  # not an admin

    await bot.forget(update, context)

    assert "admin" in update.message.reply_text.call_args[0][0].lower()
    assert storage.load_flights("groupA") != []  # nothing was deleted


async def test_forget_in_a_group_succeeds_for_an_admin():
    storage.set_chat_access_status("groupA", "approved")
    storage.add_flight("groupA", "Mom", "RJ264", "2026-08-05")

    update = FakeUpdate(chat_id="groupA", chat_type="group")
    context = FakeContext(chat_member_status="administrator")

    await bot.forget(update, context)

    assert storage.load_flights("groupA") == []


async def test_remove_in_a_group_requires_admin():
    storage.set_chat_access_status("groupA", "approved")
    storage.add_flight("groupA", "Mom", "RJ264", "2026-08-05")

    update = FakeUpdate(chat_id="groupA", chat_type="group")
    context = FakeContext(args=["RJ264"], chat_member_status="member")

    await bot.remove_flight(update, context)

    assert "admin" in update.message.reply_text.call_args[0][0].lower()
    assert storage.load_flights("groupA") != []


# --- bot.py: /timezone ---------------------------------------------------------


async def test_timezone_with_no_args_shows_current_default():
    storage.set_chat_access_status("chatA", "approved")
    update, context = FakeUpdate(chat_id="chatA"), FakeContext()

    await bot.timezone_cmd(update, context)

    assert "UTC" in update.message.reply_text.call_args[0][0]


async def test_timezone_sets_a_valid_iana_name():
    storage.set_chat_access_status("chatA", "approved")
    update, context = FakeUpdate(chat_id="chatA"), FakeContext(args=["Asia/Amman"])

    await bot.timezone_cmd(update, context)

    assert storage.get_chat_timezone("chatA") == "Asia/Amman"
    assert "Asia/Amman" in update.message.reply_text.call_args[0][0]


async def test_timezone_rejects_an_unknown_name():
    storage.set_chat_access_status("chatA", "approved")
    update, context = FakeUpdate(chat_id="chatA"), FakeContext(args=["Not/A_Zone"])

    await bot.timezone_cmd(update, context)

    assert storage.get_chat_timezone("chatA") is None
    assert "unknown timezone" in update.message.reply_text.call_args[0][0].lower()
