"""Decides which field changes in a flight's status are worth alerting on.

Per CLAUDE.md's invariants:
1. Never alert twice for the same change (handled by storage's pending/sent
   bookkeeping, not here -- this module only decides "is this worth an
   alert", not "have we already sent it").
2. Never alert on missing data: a field going value -> null is not a change.
   Only non-null -> different non-null transitions, plus an explicit
   whitelist of status transitions, produce an alert.

This module is pure (no I/O, no storage, no Telegram) so it's exhaustively
testable without touching a database or a bot.
"""

from dataclasses import dataclass

import airports
import timezones

KEY_FIELDS = (
    "status",
    "dep_delay",
    "arr_delay",
    "dep_gate",
    "arr_gate",
    "dep_estimated",
    "arr_estimated",
)

# Statuses worth alerting on the instant they're seen, even with no prior
# non-null status to compare against -- e.g. the very first successful check
# of a flight that's already cancelled must still say so. This is the
# "explicit whitelist of status transitions" CLAUDE.md's invariant #2 allows
# as the one exception to the null-guard.
ALWAYS_ALERT_STATUSES = frozenset({"cancelled", "diverted", "landed"})

TERMINAL_STATUS_HEADLINE = {
    "cancelled": "❌ Cancelled",
    "diverted": "\U0001f500 Diverted",
    "landed": "\U0001f6ec Landed",
}

FIELD_LABELS = {
    "status": "Status",
    "dep_delay": "Departure delay",
    "arr_delay": "Arrival delay",
    "dep_gate": "Departure gate",
    "arr_gate": "Arrival gate",
    "dep_estimated": "Estimated departure",
    "arr_estimated": "Estimated arrival",
}


@dataclass(frozen=True)
class FieldChange:
    field: str
    old_value: object
    new_value: object


def detect_changes(previous: dict | None, current: dict) -> list[FieldChange]:
    """Compare two key-fields snapshots and return the subset of changes
    worth alerting on. `previous` is the last-known snapshot (never None in
    practice here -- callers skip this entirely for a flight's first-ever
    check, which only records a silent baseline, matching pre-Phase-3
    behavior)."""
    changes = []
    for field in KEY_FIELDS:
        old = previous.get(field) if previous else None
        new = current.get(field)
        if old == new:
            continue
        # Deliberately not combined into one `or` condition (ruff SIM114):
        # these are two independently-justified reasons to alert (the
        # explicit status whitelist vs. the general null-guarded rule), and
        # collapsing them would hide that distinction from a future reader.
        if field == "status" and new in ALWAYS_ALERT_STATUSES:  # noqa: SIM114
            changes.append(FieldChange(field, old, new))
        elif old is not None and new is not None:
            changes.append(FieldChange(field, old, new))
        # else: value -> null, or null -> a non-terminal value -- not a
        # change worth alerting per invariant #2.
    return changes


def _render_field(
    field: str, new_value: str | int | None, summary: dict, subscriber_tz: str | None
) -> str:
    label = FIELD_LABELS.get(field, field)
    if field == "status":
        return f"{label}: {str(new_value or 'unknown').upper()}"
    if field in ("dep_delay", "arr_delay"):
        return f"{label}: {new_value} min"
    if field in ("dep_estimated", "arr_estimated"):
        airport_iata = summary.get(
            "dep_iata" if field == "dep_estimated" else "arr_iata"
        )
        rendered = timezones.render_dual(
            str(new_value) if new_value is not None else None,
            airports.get_timezone(airport_iata),
            subscriber_tz,
        )
        return f"{label}: {rendered}"
    return f"{label}: {new_value}"


def format_alert_message(
    name: str,
    flight_iata: str,
    pending_changes: list[dict],
    summary: dict,
    subscriber_tz: str | None = None,
) -> str:
    """Compose one message covering every pending change for a flight --
    this is the "debounce into one message" behavior: whatever's pending
    (newly detected this poll, plus anything left over from a crash before a
    previous send completed) gets bundled into a single notification rather
    than one message per field.

    Cancelled/diverted/landed get a distinct headline (CLAUDE.md: "terminal
    states with their own message copy") instead of the generic "Update"
    framing, and are surfaced first regardless of change order.
    """
    terminal = next(
        (
            c
            for c in pending_changes
            if c["field"] == "status" and c["new_value"] in ALWAYS_ALERT_STATUSES
        ),
        None,
    )
    lines = []
    if terminal:
        lines.append(
            f"{TERMINAL_STATUS_HEADLINE[terminal['new_value']]}: {name} — {flight_iata}"
        )
        remaining = [c for c in pending_changes if c is not terminal]
    else:
        lines.append(f"🔔 Update: {name} — {flight_iata}")
        remaining = pending_changes

    for change in remaining:
        lines.append(
            _render_field(change["field"], change["new_value"], summary, subscriber_tz)
        )

    return "\n".join(lines)
