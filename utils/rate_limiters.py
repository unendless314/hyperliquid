"""
Rate limiting and circuit breaker primitives shared across services.

These are intentionally simple (dependency-free) and coroutine-friendly so
they can be reused by Monitor/Executor/Notifier pipelines without pulling in
external libs.
"""

from __future__ import annotations

import asyncio
import time


class SimpleRateLimiter:
    """Tokenless limiter enforcing a minimum interval between operations."""

    def __init__(self, min_interval_sec: float = 0.2):
        self.min_interval = min_interval_sec
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


class CircuitBreaker:
    """Minimal circuit breaker with failure threshold and cooldown."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 5.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failures = 0
        self.open_until = 0.0

    def allow(self) -> bool:
        return time.monotonic() >= self.open_until

    def record_success(self):
        self.failures = 0

    def record_failure(self):
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.open_until = time.monotonic() + self.cooldown_seconds
            self.failures = 0

    @property
    def cooldown_remaining(self) -> float:
        return max(self.open_until - time.monotonic(), 0.0)
