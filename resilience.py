"""Backoff/retry and a per-provider circuit breaker for flaky HTTP calls,
plus a helper for Telegram's own rate-limit signal (RetryAfter).

CLAUDE.md's failure semantics: "429 and 5xx: exponential backoff with
jitter, per-provider circuit breaker." "4xx other than 429: do not retry."
This module implements the mechanism; flight_api.py decides which statuses
are retryable for Aviationstack specifically.
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from telegram.error import RetryAfter

log = logging.getLogger("flight_tracker.resilience")

DEFAULT_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class CircuitOpenError(Exception):
    """Raised when a circuit breaker refuses to attempt a call at all."""


@dataclass
class CircuitBreaker:
    """A simple closed/open/half-open breaker, one instance per provider.

    Closed (normal): calls proceed; failures are counted.
    Open: calls are refused immediately (CircuitOpenError) once
    `failure_threshold` consecutive failures have happened, for
    `cooldown_seconds`.
    Half-open: after the cooldown, the next call is allowed through as a
    trial; success closes the breaker again, failure re-opens it.
    """

    name: str
    failure_threshold: int = 5
    cooldown_seconds: float = 60.0
    _consecutive_failures: int = field(default=0, init=False, repr=False)
    _opened_at: datetime | None = field(default=None, init=False, repr=False)

    def before_call(self, now: datetime | None = None) -> None:
        if self._opened_at is None:
            return
        now = now or datetime.now(UTC)
        if now - self._opened_at < timedelta(seconds=self.cooldown_seconds):
            raise CircuitOpenError(
                f"Circuit breaker '{self.name}' is open "
                f"(retry after {self.cooldown_seconds}s cooldown)"
            )
        log.info(
            "Circuit breaker %s entering half-open trial after cooldown", self.name
        )
        # Stays "open" (opened_at set) until record_success/record_failure
        # resolves the trial, so a second caller mid-trial is still refused.

    def record_success(self) -> None:
        if self._consecutive_failures or self._opened_at:
            log.info("Circuit breaker %s closed (call succeeded)", self.name)
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self, now: datetime | None = None) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._opened_at = now or datetime.now(UTC)
            log.warning(
                "Circuit breaker %s opened after %d consecutive failures",
                self.name,
                self._consecutive_failures,
            )

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None


def retry_with_backoff(
    attempt_fn,
    *,
    is_retryable,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    sleep=None,
    rand=None,
):
    """Calls attempt_fn() repeatedly until it returns a non-retryable result
    (per is_retryable(result) -> bool) or raises, or max_attempts is used up.

    Exponential backoff with full jitter: delay = base_delay * 2**attempt * rand().
    `sleep`/`rand` are injectable so tests never actually wait real seconds --
    resolved at call time (not as a default-argument value bound once at
    import time) so a test that monkeypatches resilience.time.sleep /
    resilience.random.random still takes effect even when a caller (like
    flight_api.py) never passes sleep=/rand= explicitly.
    """
    sleep = sleep if sleep is not None else time.sleep
    rand = rand if rand is not None else random.random
    result = None
    for attempt in range(max_attempts):
        result = attempt_fn()
        if not is_retryable(result):
            return result
        if attempt < max_attempts - 1:
            delay = base_delay * (2**attempt) * rand()
            log.warning(
                "Retryable failure on attempt %d/%d, backing off %.2fs",
                attempt + 1,
                max_attempts,
                delay,
            )
            sleep(delay)
    return result


async def send_with_retry(send_fn, *, max_attempts: int = 3, sleep=None):
    """Awaits send_fn() (a zero-arg async callable, e.g. a lambda wrapping
    context.bot.send_message(...)), retrying on Telegram's RetryAfter by
    waiting exactly as long as Telegram asks. CLAUDE.md: "Handle Telegram
    RetryAfter." Re-raises on the final attempt or any other exception.
    """
    sleep = sleep if sleep is not None else asyncio.sleep
    for attempt in range(max_attempts):
        try:
            return await send_fn()
        except RetryAfter as e:
            if attempt == max_attempts - 1:
                raise
            log.warning(
                "Telegram rate-limited us, retrying after %.1fs (attempt %d/%d)",
                e.retry_after,
                attempt + 1,
                max_attempts,
            )
            await sleep(e.retry_after)
    raise AssertionError("unreachable")  # pragma: no cover
