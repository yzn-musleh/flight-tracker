"""Structured (JSON) logging with secret redaction.

CLAUDE.md invariant #6: "Secrets never enter the repo, logs, or error
messages. Tokens are redacted in every log path including exception
tracebacks." Redaction happens on the fully-rendered message/traceback
string (not on raw %-args, which can be non-strings and would make
substitution fragile), so it applies regardless of how a log call was made.
"""

import json
import logging
import os


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets: list[str | None]):
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def _redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "***REDACTED***")
        return text

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": self._redact(record.getMessage()),
        }
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id:
            payload["correlation_id"] = correlation_id
        if record.exc_info:
            payload["exception"] = self._redact(self.formatException(record.exc_info))
        return json.dumps(payload)


def configure(level: int = logging.INFO) -> None:
    """Replaces the root logger's handlers with a single JSON, redacting one.
    Call once at process startup, before anything else logs."""
    secrets = [
        os.environ.get("TELEGRAM_BOT_TOKEN"),
        os.environ.get("AVIATIONSTACK_API_KEY"),
    ]
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(secrets))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def with_correlation_id(
    logger: logging.Logger, correlation_id: str
) -> logging.LoggerAdapter:
    """A per-poll-cycle logger (CLAUDE.md: "a correlation id per poll
    cycle") -- every message logged through the adapter carries
    correlation_id without each call site needing to pass extra= itself."""
    return logging.LoggerAdapter(logger, {"correlation_id": correlation_id})
