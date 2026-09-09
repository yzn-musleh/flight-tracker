"""Access control: which chats may use the bot at all.

Per CLAUDE.md invariant #5, chat_id is the tenant boundary. This module
decides *whether* a chat may act; per-chat data scoping itself lives in
storage.py's chat_id-parameterized functions, not here. Deliberately
free of any python-telegram-bot import -- business logic never imports from
telegram/ (CLAUDE.md's coding standards).

A fixed allowlist, not a self-service approval workflow: this is a family
bot with a handful of known chat IDs, set once in .env by the operator.
"""

import os

ALLOWED_CHAT_IDS = frozenset(
    c.strip() for c in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if c.strip()
)


def is_approved(chat_id: str) -> bool:
    return chat_id in ALLOWED_CHAT_IDS
