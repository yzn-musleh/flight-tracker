"""Backoff/retry for flaky HTTP calls, plus a helper for Telegram's own
rate-limit signal (RetryAfter).

CLAUDE.md's failure semantics: "429 and 5xx: exponential backoff with
jitter." "4xx other than 429: do not retry." This module implements the
mechanism; flight_api.py decides which statuses are retryable for
Aviationstack specifically.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta

from telegram.error import RetryAfter

log = logging.getLogger("flight_tracker.resilience")

DEFAULT_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


def retry_with_backoff[T](
    attempt_fn: Callable[[], T],
    *,
    is_retryable: Callable[[T], bool],
    max_attempts: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] | None = None,
    rand: Callable[[], float] | None = None,
) -> T:
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
    result: T = attempt_fn()
    for attempt in range(max_attempts - 1):
        if not is_retryable(result):
            return result
        delay = base_delay * (2**attempt) * rand()
        log.warning(
            "Retryable failure on attempt %d/%d, backing off %.2fs",
            attempt + 1,
            max_attempts,
            delay,
        )
        sleep(delay)
        result = attempt_fn()
    return result


async def send_with_retry[R](
    send_fn: Callable[[], Awaitable[R]],
    *,
    max_attempts: int = 3,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> R:
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
            # RetryAfter.retry_after is int | timedelta (python-telegram-bot
            # 22+); normalize to seconds for the injectable float-based sleep.
            retry_after = (
                e.retry_after.total_seconds()
                if isinstance(e.retry_after, timedelta)
                else float(e.retry_after)
            )
            log.warning(
                "Telegram rate-limited us, retrying after %.1fs (attempt %d/%d)",
                retry_after,
                attempt + 1,
                max_attempts,
            )
            await sleep(retry_after)
    raise AssertionError("unreachable")  # pragma: no cover
