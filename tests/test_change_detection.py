"""New in Phase 3: characterizes change_detection.py's alert-worthiness
rules in isolation -- no storage, no bot, no network. This is the
fixed-and-tested replacement for the null-transition bug documented in
FINDINGS.md #5."""

import change_detection


def test_no_change_detected_when_nothing_differs():
    snapshot = {"status": "scheduled", "dep_delay": None}
    assert change_detection.detect_changes(snapshot, dict(snapshot)) == []


def test_non_null_to_different_non_null_is_a_change():
    previous = {"dep_delay": 5}
    current = {"dep_delay": 15}
    changes = change_detection.detect_changes(previous, current)
    assert changes == [change_detection.FieldChange("dep_delay", 5, 15)]


def test_non_null_to_null_is_not_a_change():
    """The bug fixed in Phase 3 -- see FINDINGS.md #5."""
    previous = {"dep_gate": "12"}
    current = {"dep_gate": None}
    assert change_detection.detect_changes(previous, current) == []


def test_null_to_non_terminal_value_is_not_a_change():
    """A gate being assigned for the first time after the baseline doesn't
    alert either -- CLAUDE.md's invariant #2 excludes both directions of a
    null transition for ordinary fields, only exempting the status
    whitelist below."""
    previous = {"dep_gate": None}
    current = {"dep_gate": "12"}
    assert change_detection.detect_changes(previous, current) == []


def test_null_to_whitelisted_status_is_always_a_change():
    for status in ("cancelled", "diverted", "landed"):
        previous = {"status": None}
        current = {"status": status}
        assert change_detection.detect_changes(previous, current) == [
            change_detection.FieldChange("status", None, status)
        ]


def test_null_to_non_whitelisted_status_is_not_a_change():
    previous = {"status": None}
    current = {"status": "active"}
    assert change_detection.detect_changes(previous, current) == []


def test_non_null_status_change_between_ordinary_values_is_a_change():
    previous = {"status": "scheduled"}
    current = {"status": "active"}
    assert change_detection.detect_changes(previous, current) == [
        change_detection.FieldChange("status", "scheduled", "active")
    ]


def test_multiple_fields_changing_at_once_are_all_reported():
    previous = {"status": "scheduled", "dep_gate": "10", "dep_delay": 5}
    current = {"status": "active", "dep_gate": "12", "dep_delay": 20}
    changes = change_detection.detect_changes(previous, current)
    assert {c.field for c in changes} == {"status", "dep_gate", "dep_delay"}


def test_first_check_has_no_prior_snapshot():
    current = {"status": "cancelled"}
    changes = change_detection.detect_changes(None, current)
    assert changes == [change_detection.FieldChange("status", None, "cancelled")]


def test_format_alert_message_uses_terminal_headline_for_cancelled():
    pending = [{"field": "status", "old_value": "scheduled", "new_value": "cancelled"}]
    text = change_detection.format_alert_message("Mom", "RJ264", pending, {})
    assert text.startswith("❌ Cancelled: Mom — RJ264")


def test_format_alert_message_uses_generic_headline_for_non_terminal_changes():
    pending = [{"field": "dep_gate", "old_value": "10", "new_value": "12"}]
    text = change_detection.format_alert_message("Mom", "RJ264", pending, {})
    assert text.startswith("🔔 Update: Mom — RJ264")
    assert "Departure gate: 12" in text


def test_format_alert_message_bundles_multiple_pending_changes_into_one_text():
    pending = [
        {"field": "status", "old_value": "scheduled", "new_value": "active"},
        {"field": "dep_gate", "old_value": "10", "new_value": "12"},
        {"field": "dep_delay", "old_value": "5", "new_value": "20"},
    ]
    text = change_detection.format_alert_message("Mom", "RJ264", pending, {})
    assert "Status: ACTIVE" in text
    assert "Departure gate: 12" in text
    assert "Departure delay: 20 min" in text


def test_format_alert_message_puts_terminal_headline_first_regardless_of_order():
    pending = [
        {"field": "dep_gate", "old_value": "10", "new_value": "12"},
        {"field": "status", "old_value": "active", "new_value": "landed"},
    ]
    text = change_detection.format_alert_message("Mom", "RJ264", pending, {})
    lines = text.splitlines()
    assert lines[0].startswith("\U0001f6ec Landed")
    assert "Departure gate: 12" in text
