"""Shared resilience utilities: retry, rate-limit, circuit-breaker."""
from __future__ import annotations

import asyncio
import logging
import time
from functools import wraps

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger("remotejob-bot.resilience")
_scraper_retry_attempts = 3
_scraper_retry_max_wait = 30.0


# ---------------------------------------------------------------------------
# Retry helpers
# ---------------------------------------------------------------------------

def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient HTTP errors that should be retried."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout,
                        httpx.ReadTimeout, httpx.WriteTimeout,
                        httpx.PoolTimeout)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or 500 <= code < 600
    return False


def _log_retry(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "RETRY attempt=%d fn=%s err=%s",
        retry_state.attempt_number,
        getattr(retry_state.fn, "__qualname__", "?"),
        repr(exc)[:200] if exc else "?",
    )


def configure_scraper_retry(max_attempts: int, max_wait: float) -> None:
    """Set runtime defaults used by scraper decorators without rebuilding clients."""
    global _scraper_retry_attempts, _scraper_retry_max_wait
    _scraper_retry_attempts = max(1, int(max_attempts))
    _scraper_retry_max_wait = max(0.0, float(max_wait))
    logger.info(
        "SCRAPER_RETRY_CONFIG attempts=%s max_wait_seconds=%s",
        _scraper_retry_attempts,
        _scraper_retry_max_wait,
    )


def scraper_retry(*, max_attempts: int | None = None, max_wait: float | None = None):
    """Tenacity decorator whose omitted values are resolved from runtime config."""
    def decorator(fn):
        @wraps(fn)
        async def wrapped(*args, **kwargs):
            attempts = _scraper_retry_attempts if max_attempts is None else max(1, int(max_attempts))
            wait_cap = _scraper_retry_max_wait if max_wait is None else max(0.0, float(max_wait))
            retrying = AsyncRetrying(
                stop=stop_after_attempt(attempts),
                wait=wait_exponential(multiplier=2, max=wait_cap),
                retry=retry_if_exception(_is_retryable),
                before_sleep=_log_retry,
                reraise=True,
            )
            return await retrying(fn, *args, **kwargs)

        return wrapped

    return decorator


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

def create_rate_limiter(max_rate: float, time_period: float = 1.0) -> AsyncLimiter:
    """Create an async leaky-bucket rate limiter."""
    return AsyncLimiter(max_rate=max(0.1, max_rate), time_period=time_period)


# ---------------------------------------------------------------------------
# Lightweight circuit breaker (no external dependency)
# ---------------------------------------------------------------------------

class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Circuit breaker '{name}' is OPEN")


class SimpleCircuitBreaker:
    """Minimal async-compatible circuit breaker.

    States:
        CLOSED  — normal operation, failures counted.
        OPEN    — all calls rejected immediately with CircuitOpenError.
        HALF_OPEN — one probe call allowed; success → CLOSED, failure → OPEN.
    """

    def __init__(self, name: str, fail_max: int = 5, reset_timeout: float = 60.0):
        self.name = name
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self._fail_count = 0
        self._opened_at: float = 0.0
        self._state = "closed"  # closed | open | half_open
        self._last_call_was_half_open = False
        self._fail_count_before_call = 0
        # H10 fix: asyncio.Lock for coroutine-safe state mutation
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        if self._state == "open":
            if time.monotonic() - self._opened_at >= self.reset_timeout:
                self._state = "half_open"
        return self._state

    def record_success(self) -> None:
        self._fail_count = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._fail_count += 1
        if self._fail_count >= self.fail_max:
            self._state = "open"
            self._opened_at = time.monotonic()
            logger.warning("CIRCUIT_OPEN name=%s failures=%d", self.name, self._fail_count)

    def record_soft_failure(self) -> None:
        """Count a client-reported failure that was returned as an empty result.

        Several scrapers intentionally catch transport/parsing exceptions and expose
        them through ``last_error``.  Their async context therefore exits without an
        exception and records a success first; this explicit signal restores the
        failure count.  A failed HALF_OPEN probe must reopen immediately.
        """
        self._fail_count = max(self._fail_count, self._fail_count_before_call)
        if self._last_call_was_half_open:
            self._fail_count = max(self._fail_count, self.fail_max - 1)
        self.record_failure()
        self._last_call_was_half_open = False

    async def __aenter__(self):
        await self._lock.acquire()
        st = self.state
        if st == "open":
            self._lock.release()
            raise CircuitOpenError(self.name)
        self._fail_count_before_call = self._fail_count
        self._last_call_was_half_open = st == "half_open"
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.record_success()
            elif exc_type is not CircuitOpenError:
                self.record_failure()
        finally:
            self._lock.release()
        return False  # do not suppress
