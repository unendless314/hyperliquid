from __future__ import annotations

import logging
import random
import time
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Deque, Iterable, List, Optional

from hyperliquid.ingest.service import RawPositionEvent


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
        self._requests: Deque[float] = deque()

    def allow(self) -> bool:
        if self._policy.max_requests <= 0 or self._policy.per_seconds <= 0:
            return True
        now = time.time()
        window_start = now - self._policy.per_seconds
        while self._requests and self._requests[0] < window_start:
            self._requests.popleft()
        if len(self._requests) >= self._policy.max_requests:
            return False
        self._requests.append(now)
        return True

    @property
    def cooldown_seconds(self) -> int:
        return max(self._policy.cooldown_seconds, 0)


@dataclass(frozen=True)
class HyperliquidIngestConfig:
    enabled: bool
    mode: str
    target_wallet: str
    rest_url: str
    ws_url: str
    request_timeout_ms: int
    backfill_window_ms: int
    cursor_overlap_ms: int
    rate_limit: RateLimitPolicy
    retry: RetryPolicy
    stub_events: List[RawPositionEvent] = field(default_factory=list)

    @staticmethod
    def from_settings(raw: dict) -> "HyperliquidIngestConfig":
        ingest = raw.get("ingest", {})
        hyperliquid = ingest.get("hyperliquid", {})
        rate_limit = hyperliquid.get("rate_limit", {})
        retry = hyperliquid.get("retry", {})
        stub_events = [
            RawPositionEvent(
                symbol=str(item["symbol"]),
                tx_hash=str(item["tx_hash"]),
                event_index=int(item["event_index"]),
                prev_target_net_position=float(item["prev_target_net_position"]),
                next_target_net_position=float(item["next_target_net_position"]),
                is_replay=int(item.get("is_replay", 0)),
                timestamp_ms=(int(item["timestamp_ms"]) if "timestamp_ms" in item else None),
                open_component=(
                    float(item["open_component"])
                    if "open_component" in item
                    else None
                ),
                close_component=(
                    float(item["close_component"])
                    if "close_component" in item
                    else None
                ),
            )
            for item in hyperliquid.get("stub_events", [])
        ]
        return HyperliquidIngestConfig(
            enabled=bool(hyperliquid.get("enabled", False)),
            mode=str(hyperliquid.get("mode", "stub")),
            target_wallet=str(hyperliquid.get("target_wallet", "")),
            rest_url=str(hyperliquid.get("rest_url", "https://api.hyperliquid.xyz/info")),
            ws_url=str(hyperliquid.get("ws_url", "")),
            request_timeout_ms=int(hyperliquid.get("request_timeout_ms", 10_000)),
            backfill_window_ms=int(ingest.get("backfill_window_ms", 0)),
            cursor_overlap_ms=int(ingest.get("cursor_overlap_ms", 0)),
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
            stub_events=stub_events,
        )


class HyperliquidIngestAdapter:
    def __init__(
        self, config: HyperliquidIngestConfig, logger: Optional[logging.Logger] = None
    ) -> None:
        self._config = config
        self._logger = logger or logging.getLogger("hyperliquid")
        self._rate_limiter = RateLimiter(config.rate_limit)

    @property
    def config(self) -> HyperliquidIngestConfig:
        return self._config

    def fetch_backfill(self, *, since_ms: int, until_ms: int) -> List[RawPositionEvent]:
        if not self._config.enabled:
            return []
        if self._config.mode != "stub":
            raise NotImplementedError("Hyperliquid REST backfill adapter is not wired")
        if not self._rate_limiter.allow():
            self._logger.warning(
                "ingest_rate_limited",
                extra={
                    "provider": "hyperliquid",
                    "cooldown_seconds": self._rate_limiter.cooldown_seconds,
                },
            )
            return []
        return self._filter_stub_events(since_ms=since_ms, until_ms=until_ms)

    def poll_live_events(self, *, since_ms: int) -> List[RawPositionEvent]:
        if not self._config.enabled:
            return []
        if self._config.mode != "stub":
            raise NotImplementedError("Hyperliquid WS adapter is not wired")
        if not self._rate_limiter.allow():
            self._logger.warning(
                "ingest_rate_limited",
                extra={
                    "provider": "hyperliquid",
                    "cooldown_seconds": self._rate_limiter.cooldown_seconds,
                },
            )
            return []
        return self._filter_stub_events(since_ms=since_ms, until_ms=None)

    def _filter_stub_events(
        self, *, since_ms: int, until_ms: Optional[int]
    ) -> List[RawPositionEvent]:
        now_ms = int(time.time() * 1000)
        events: List[RawPositionEvent] = []
        for event in self._config.stub_events:
            timestamp_ms = (
                event.timestamp_ms if event.timestamp_ms is not None else now_ms
            )
            if timestamp_ms < since_ms:
                continue
            if until_ms is not None and timestamp_ms > until_ms:
                continue
            events.append(replace(event, timestamp_ms=timestamp_ms))
        return events

    def close(self) -> None:
        return None


__all__ = [
    "HyperliquidIngestAdapter",
    "HyperliquidIngestConfig",
    "RateLimitPolicy",
    "RateLimiter",
    "RetryPolicy",
]
