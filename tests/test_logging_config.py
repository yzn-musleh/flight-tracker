"""New in Phase 5: characterizes structured JSON logging and secret
redaction (CLAUDE.md invariant #6: "Secrets never enter the repo, logs, or
error messages... redacted in every log path including exception
tracebacks")."""

import json
import logging

import logging_config


def _record(msg, *args, exc_info=None, extra=None):
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,
    )
    for k, v in (extra or {}).items():
        setattr(record, k, v)
    return record


def test_format_produces_valid_json_with_expected_fields():
    formatter = logging_config.JsonFormatter(secrets=[])
    record = _record("hello %s", "world")
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test"
    assert payload["message"] == "hello world"
    assert "timestamp" in payload


def test_secret_is_redacted_from_the_message():
    formatter = logging_config.JsonFormatter(secrets=["super-secret-token"])
    record = _record("using token %s to call the API", "super-secret-token")
    payload = json.loads(formatter.format(record))
    assert "super-secret-token" not in payload["message"]
    assert "***REDACTED***" in payload["message"]


def test_secret_is_redacted_from_exception_tracebacks():
    formatter = logging_config.JsonFormatter(secrets=["super-secret-token"])
    try:
        raise ValueError("failed with token super-secret-token")
    except ValueError:
        import sys

        record = _record("lookup failed", exc_info=sys.exc_info())
    payload = json.loads(formatter.format(record))
    assert "super-secret-token" not in payload["exception"]
    assert "***REDACTED***" in payload["exception"]


def test_none_secrets_are_ignored_without_error():
    formatter = logging_config.JsonFormatter(secrets=[None, "", "real-secret"])
    record = _record("token is real-secret")
    payload = json.loads(formatter.format(record))
    assert "real-secret" not in payload["message"]


def test_correlation_id_included_when_present():
    formatter = logging_config.JsonFormatter(secrets=[])
    record = _record("polling", extra={"correlation_id": "abc123"})
    payload = json.loads(formatter.format(record))
    assert payload["correlation_id"] == "abc123"


def test_correlation_id_omitted_when_absent():
    formatter = logging_config.JsonFormatter(secrets=[])
    record = _record("no correlation here")
    payload = json.loads(formatter.format(record))
    assert "correlation_id" not in payload


def test_with_correlation_id_adapter_tags_every_message():
    logger = logging.getLogger("test_adapter")
    logger.setLevel(logging.INFO)
    records = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record)
    logger.handlers = [handler]
    logger.propagate = False

    adapter = logging_config.with_correlation_id(logger, "cycle-42")
    adapter.info("first")
    adapter.warning("second")

    assert len(records) == 2
    assert all(r.correlation_id == "cycle-42" for r in records)


def test_configure_installs_a_json_formatter_on_root(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    logging_config.configure()
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, logging_config.JsonFormatter)
