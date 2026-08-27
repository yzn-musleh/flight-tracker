"""Minimal stand-ins for python-telegram-bot objects.

bot.py's handlers touch update.message.reply_text, update.effective_chat.id/
.type, update.effective_user.id, context.args, context.bot.send_message, and
(for group-admin checks) context.bot.get_chat_member -- so a full
telegram.Update is unnecessary ceremony for characterization tests.
"""

from unittest.mock import AsyncMock


class FakeMessage:
    def __init__(self):
        self.reply_text = AsyncMock()


class FakeChat:
    def __init__(self, chat_id=12345, chat_type="private"):
        self.id = chat_id
        self.type = chat_type


class FakeUser:
    def __init__(self, user_id=1):
        self.id = user_id


class FakeUpdate:
    def __init__(self, args=None, chat_id=12345, chat_type="private", user_id=1):
        self.message = FakeMessage()
        self.effective_chat = FakeChat(chat_id, chat_type)
        self.effective_user = FakeUser(user_id)


class FakeChatMember:
    def __init__(self, status="member"):
        self.status = status


class FakeBot:
    def __init__(self, chat_member_status="administrator"):
        self.send_message = AsyncMock()
        self.get_chat_member = AsyncMock(
            return_value=FakeChatMember(chat_member_status)
        )


class FakeContext:
    def __init__(self, args=None, chat_member_status="administrator"):
        self.args = args or []
        self.bot = FakeBot(chat_member_status)
