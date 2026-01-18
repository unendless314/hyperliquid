from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Optional

from hyperliquid.common.models import OrderIntent, OrderResult, assert_contract_version


class AdapterNotImplementedError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    base_delay_ms: int
    max_delay_ms: int
    jitter_ms: int

    def next_delay_ms(self, attempt: int) -> int:
        if attempt < 1:
            attempt = 1
        delay = self.base_delay_ms * (2 ** (attempt - 1))
        delay = min(delay, self.max_delay_ms)
        jitter = random.randint(0, max(self.jitter_ms, 0))
        return max(0, delay + jitter)


@dataclass(frozen=True)
class RateLimitPolicy:
    max_requests: int
    per_seconds: int
    cooldown_seconds: int


class RateLimiter:
    def __init__(self, policy: RateLimitPolicy) -> None:
        self._policy = policy
        self._requests: list[float] = []

    def allow(self) -> bool:
        if self._policy.max_requests <= 0 or self._policy.per_seconds <= 0:
            return True
        now = time.time()
        window_start = now - self._policy.per_seconds
        self._requests = [req for req in self._requests if req >= window_start]
        if len(self._requests) >= self._policy.max_requests:
            return False
        self._requests.append(now)
        return True

    @property
    def cooldown_seconds(self) -> int:
        return max(self._policy.cooldown_seconds, 0)


@dataclass(frozen=True)
class BinanceExecutionConfig:
    enabled: bool
    mode: str
    base_url: str
    api_key: str
    api_secret: str
    request_timeout_ms: int
    recv_window_ms: int
    rate_limit: RateLimitPolicy
    retry: RetryPolicy

    @staticmethod
    def from_settings(raw: dict) -> "BinanceExecutionConfig":
        execution = raw.get("execution", {})
        binance = execution.get("binance", {})
        rate_limit = binance.get("rate_limit", {})
        retry = binance.get("retry", {})
        return BinanceExecutionConfig(
            enabled=bool(binance.get("enabled", False)),
            mode=str(binance.get("mode", "stub")),
            base_url=str(binance.get("base_url", "https://fapi.binance.com")),
            api_key=str(binance.get("api_key", "")),
            api_secret=str(binance.get("api_secret", "")),
            request_timeout_ms=int(binance.get("request_timeout_ms", 10_000)),
            recv_window_ms=int(binance.get("recv_window_ms", 5_000)),
            rate_limit=RateLimitPolicy(
                max_requests=int(rate_limit.get("max_requests", 0)),
                per_seconds=int(rate_limit.get("per_seconds", 1)),
                cooldown_seconds=int(rate_limit.get("cooldown_seconds", 0)),
            ),
            retry=RetryPolicy(
                max_attempts=int(retry.get("max_attempts", 0)),
                base_delay_ms=int(retry.get("base_delay_ms", 250)),
                max_delay_ms=int(retry.get("max_delay_ms", 2_000)),
                jitter_ms=int(retry.get("jitter_ms", 100)),
            ),
        )


class BinanceExecutionAdapter:
    def __init__(
        self, config: BinanceExecutionConfig, logger: Optional[logging.Logger] = None
    ) -> None:
        self._config = config
        self._logger = logger or logging.getLogger("hyperliquid")
        self._rate_limiter = RateLimiter(config.rate_limit)

    @property
    def config(self) -> BinanceExecutionConfig:
        return self._config

    def execute(self, intent: OrderIntent) -> OrderResult:
        assert_contract_version(intent.contract_version)
        if not self._config.enabled:
            return self._stub_reject(intent, "ADAPTER_DISABLED")
        if self._config.mode != "stub":
            raise AdapterNotImplementedError("Binance execution adapter is not wired")
        if not self._rate_limiter.allow():
            self._logger.warning(
                "execution_rate_limited",
                extra={
                    "provider": "binance",
                    "cooldown_seconds": self._rate_limiter.cooldown_seconds,
                },
            )
            return self._stub_reject(intent, "RATE_LIMITED")
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id=None,
            status="SUBMITTED",
            filled_qty=0.0,
            avg_price=None,
            error_code=None,
            error_message=None,
        )

    def _stub_reject(self, intent: OrderIntent, code: str) -> OrderResult:
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id=None,
            status="REJECTED",
            filled_qty=0.0,
            avg_price=None,
            error_code=code,
            error_message="Binance adapter stub",
        )


__all__ = [
    "BinanceExecutionAdapter",
    "BinanceExecutionConfig",
    "RateLimitPolicy",
    "RateLimiter",
    "RetryPolicy",
]
