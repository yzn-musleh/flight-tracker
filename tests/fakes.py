"""Minimal stand-ins for python-telegram-bot objects.

bot.py's handlers only ever touch update.message.reply_text,
update.effective_chat.id, context.args, and context.bot.send_message -- so a
full telegram.Update is unnecessary ceremony for characterization tests.
"""

from unittest.mock import AsyncMock


class FakeMessage:
    def __init__(self):
        self.reply_text = AsyncMock()


class FakeChat:
    def __init__(self, chat_id=12345):
        self.id = chat_id


class FakeUpdate:
    def __init__(self, args=None, chat_id=12345):
        self.message = FakeMessage()
        self.effective_chat = FakeChat(chat_id)


class FakeBot:
    def __init__(self):
        self.send_message = AsyncMock()


class FakeContext:
    def __init__(self, args=None):
        self.args = args or []
        self.bot = FakeBot()
