"""New in Phase 5: characterizes resilience.py's retry/backoff, circuit
breaker, and Telegram RetryAfter handling in isolation -- no real sleeping,
no real network, no real Telegram client."""

from datetime import UTC, datetime, timedelta

import pytest

import resilience


def _fake_sleep_log():
    calls = []

    def _sleep(seconds):
        calls.append(seconds)

    return _sleep, calls


# --- retry_with_backoff ------------------------------------------------------


def test_returns_immediately_on_first_non_retryable_result():
    sleep, calls = _fake_sleep_log()
    attempts = []

    def attempt():
        attempts.append(1)
        return "ok"

    result = resilience.retry_with_backoff(
        attempt, is_retryable=lambda r: False, sleep=sleep
    )

    assert result == "ok"
    assert len(attempts) == 1
    assert calls == []


def test_retries_up_to_max_attempts_then_returns_last_result():
    sleep, calls = _fake_sleep_log()
    attempts = []

    def attempt():
        attempts.append(1)
        return "still-bad"

    result = resilience.retry_with_backoff(
        attempt,
        is_retryable=lambda r: True,
        max_attempts=3,
        sleep=sleep,
        rand=lambda: 1.0,
    )

    assert result == "still-bad"
    assert len(attempts) == 3
    assert len(calls) == 2  # slept between attempts, not after the last one


def test_stops_retrying_as_soon_as_a_good_result_appears():
    sleep, calls = _fake_sleep_log()
    results = iter(["bad", "bad", "good"])

    result = resilience.retry_with_backoff(
        lambda: next(results),
        is_retryable=lambda r: r == "bad",
        max_attempts=5,
        sleep=sleep,
        rand=lambda: 1.0,
    )

    assert result == "good"
    assert len(calls) == 2


def test_backoff_delay_grows_exponentially():
    sleep, calls = _fake_sleep_log()

    resilience.retry_with_backoff(
        lambda: "bad",
        is_retryable=lambda r: True,
        max_attempts=4,
        base_delay=1.0,
        sleep=sleep,
        rand=lambda: 1.0,  # no jitter, for a deterministic assertion
    )

    assert calls == [1.0, 2.0, 4.0]


# --- CircuitBreaker -----------------------------------------------------------


def test_circuit_stays_closed_below_failure_threshold():
    breaker = resilience.CircuitBreaker(name="test", failure_threshold=3)
    breaker.record_failure()
    breaker.record_failure()
    breaker.before_call()  # must not raise
    assert breaker.is_open is False


def test_circuit_opens_at_failure_threshold_and_refuses_calls():
    breaker = resilience.CircuitBreaker(
        name="test", failure_threshold=2, cooldown_seconds=60
    )
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.is_open is True
    with pytest.raises(resilience.CircuitOpenError):
        breaker.before_call()


def test_circuit_half_opens_after_cooldown():
    breaker = resilience.CircuitBreaker(
        name="test", failure_threshold=1, cooldown_seconds=30
    )
    now = datetime(2026, 8, 5, tzinfo=UTC)
    breaker.record_failure(now=now)

    with pytest.raises(resilience.CircuitOpenError):
        breaker.before_call(now=now + timedelta(seconds=10))

    breaker.before_call(
        now=now + timedelta(seconds=31)
    )  # cooldown elapsed, must not raise


def test_circuit_closes_again_on_success():
    breaker = resilience.CircuitBreaker(name="test", failure_threshold=1)
    breaker.record_failure()
    assert breaker.is_open is True

    breaker.record_success()

    assert breaker.is_open is False
    breaker.before_call()  # must not raise


# --- send_with_retry ----------------------------------------------------------


async def test_send_with_retry_returns_on_first_success():
    async def send():
        return "sent"

    result = await resilience.send_with_retry(send)
    assert result == "sent"


async def test_send_with_retry_waits_exactly_what_telegram_asks(monkeypatch):
    from telegram.error import RetryAfter

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    attempts = iter([RetryAfter(5), "sent"])

    async def send():
        item = next(attempts)
        if isinstance(item, Exception):
            raise item
        return item

    result = await resilience.send_with_retry(send, sleep=fake_sleep)

    assert result == "sent"
    assert sleeps == [5]


async def test_send_with_retry_gives_up_after_max_attempts():
    from telegram.error import RetryAfter

    async def always_rate_limited():
        raise RetryAfter(1)

    async def fake_sleep(seconds):
        pass

    with pytest.raises(RetryAfter):
        await resilience.send_with_retry(
            always_rate_limited, max_attempts=2, sleep=fake_sleep
        )


async def test_send_with_retry_propagates_other_exceptions_immediately():
    async def boom():
        raise ConnectionError("nope")

    with pytest.raises(ConnectionError):
        await resilience.send_with_retry(boom)
