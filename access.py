"""Access control: which chats may use the bot at all, and how a new chat
gets approved.

Per CLAUDE.md invariant #5, chat_id is the tenant boundary. This module
decides *whether* a chat may act; per-chat data scoping itself lives in
storage.py's chat_id-parameterized functions, not here. Deliberately
free of any python-telegram-bot import -- business logic never imports from
telegram/ (CLAUDE.md's coding standards).
"""

import os

import storage

ALLOWED_CHAT_IDS = frozenset(
    c.strip() for c in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if c.strip()
)


def is_admin(chat_id: str) -> bool:
    """Admins are exactly the chats pre-approved via ALLOWED_CHAT_IDS -- the
    operator's own chat(s), set once at deploy time. They can /approve or
    /deny other chats' access requests."""
    return chat_id in ALLOWED_CHAT_IDS


def is_approved(chat_id: str) -> bool:
    if chat_id in ALLOWED_CHAT_IDS:
        return True
    return storage.get_chat_access_status(chat_id) == "approved"


def is_denied(chat_id: str) -> bool:
    return storage.get_chat_access_status(chat_id) == "denied"


def request_access(chat_id: str) -> str:
    """Records an access request unless one's already been decided (or is
    already pending). Returns the resulting status: 'approved' (already
    allowlisted or previously approved), 'denied' (previously denied -- not
    reset by asking again), or 'pending'."""
    if chat_id in ALLOWED_CHAT_IDS:
        return "approved"
    existing = storage.get_chat_access_status(chat_id)
    if existing in ("approved", "denied", "pending"):
        return existing
    storage.request_chat_access(chat_id)
    return "pending"
