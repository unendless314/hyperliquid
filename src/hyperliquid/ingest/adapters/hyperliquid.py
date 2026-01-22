from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Deque, Iterable, List, Optional
from urllib import error as url_error
from urllib import request as url_request

try:
    import websocket
except ImportError:  # pragma: no cover - optional runtime dependency
    websocket = None

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
    symbol_map: dict[str, str]
    rate_limit: RateLimitPolicy
    retry: RetryPolicy
    stub_events: List[RawPositionEvent] = field(default_factory=list)

    @staticmethod
    def from_settings(raw: dict) -> "HyperliquidIngestConfig":
        ingest = raw.get("ingest", {})
        hyperliquid = ingest.get("hyperliquid", {})
        rate_limit = hyperliquid.get("rate_limit", {})
        retry = hyperliquid.get("retry", {})
        target_wallet = os.getenv("HYPERLIQUID_TARGET_WALLET", "")
        enabled = bool(hyperliquid.get("enabled", False))
        mode = str(hyperliquid.get("mode", "stub"))
        if enabled and mode == "live" and not target_wallet:
            raise ValueError("HYPERLIQUID_TARGET_WALLET required for live mode")
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
                expected_price=(
                    float(item["expected_price"])
                    if "expected_price" in item
                    else None
                ),
                expected_price_timestamp_ms=(
                    int(item["expected_price_timestamp_ms"])
                    if "expected_price_timestamp_ms" in item
                    else None
                ),
            )
            for item in hyperliquid.get("stub_events", [])
        ]
        return HyperliquidIngestConfig(
            enabled=enabled,
            mode=mode,
            target_wallet=target_wallet,
            rest_url=str(hyperliquid.get("rest_url", "https://api.hyperliquid.xyz/info")),
            ws_url=str(hyperliquid.get("ws_url", "")),
            request_timeout_ms=int(hyperliquid.get("request_timeout_ms", 10_000)),
            backfill_window_ms=int(ingest.get("backfill_window_ms", 0)),
            cursor_overlap_ms=int(ingest.get("cursor_overlap_ms", 0)),
            symbol_map={str(k): str(v) for k, v in hyperliquid.get("symbol_map", {}).items()},
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
        self._ws_app = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_buffer: Deque[dict] = deque(maxlen=10_000)
        self._ws_lock = threading.Lock()
        self._ws_enabled = False
        self._last_ws_message_ms: Optional[int] = None
        self._last_ws_reconnect_ms: Optional[int] = None
        if self._should_start_ws():
            self._start_ws()

    @property
    def config(self) -> HyperliquidIngestConfig:
        return self._config

    def fetch_backfill(self, *, since_ms: int, until_ms: int) -> List[RawPositionEvent]:
        if not self._config.enabled:
            return []
        if not self._rate_limiter.allow():
            self._logger.warning(
                "ingest_rate_limited",
                extra={
                    "provider": "hyperliquid",
                    "cooldown_seconds": self._rate_limiter.cooldown_seconds,
                },
            )
            return []
        if self._config.mode == "stub":
            return self._filter_stub_events(since_ms=since_ms, until_ms=until_ms)
        if self._config.mode == "live":
            return self._fetch_backfill_live(since_ms=since_ms, until_ms=until_ms)
        raise NotImplementedError(f"Unsupported ingest mode: {self._config.mode}")

    def poll_live_events(self, *, since_ms: int) -> List[RawPositionEvent]:
        if not self._config.enabled:
            return []
        if not self._rate_limiter.allow():
            self._logger.warning(
                "ingest_rate_limited",
                extra={
                    "provider": "hyperliquid",
                    "cooldown_seconds": self._rate_limiter.cooldown_seconds,
                },
            )
            return []
        if self._config.mode == "stub":
            return self._filter_stub_events(since_ms=since_ms, until_ms=None)
        if self._config.mode == "live":
            if self._ws_enabled and self._ws_recent():
                return self._poll_live_ws(since_ms=since_ms)
            return self._poll_live_rest(since_ms=since_ms)
        raise NotImplementedError(f"Unsupported ingest mode: {self._config.mode}")

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

    def _fetch_backfill_live(self, *, since_ms: int, until_ms: int) -> List[RawPositionEvent]:
        if not self._config.target_wallet:
            self._logger.warning("ingest_missing_target_wallet")
            return []
        events: List[RawPositionEvent] = []
        end_time = until_ms
        while end_time >= since_ms:
            payload = {
                "type": "userFillsByTime",
                "user": self._config.target_wallet,
                "startTime": since_ms,
                "endTime": end_time,
                "aggregateByTime": False,
            }
            fills = self._post_json(payload)
            if not fills:
                break
            batch = self._fills_to_events(fills)
            events.extend(batch)
            oldest = self._oldest_fill_time(fills)
            if oldest is None or oldest <= since_ms:
                break
            end_time = oldest - 1
        return events

    def _poll_live_rest(self, *, since_ms: int) -> List[RawPositionEvent]:
        if not self._config.target_wallet:
            self._logger.warning("ingest_missing_target_wallet")
            return []
        now_ms = int(time.time() * 1000)
        return self._fetch_backfill_live(since_ms=since_ms, until_ms=now_ms)

    def _poll_live_ws(self, *, since_ms: int) -> List[RawPositionEvent]:
        fills = self._drain_ws_fills()
        if not fills:
            return []
        events = self._fills_to_events(fills)
        return [event for event in events if (event.timestamp_ms or 0) >= since_ms]

    def _post_json(self, payload: dict) -> List[dict]:
        body = json.dumps(payload).encode("utf-8")
        req = url_request.Request(
            self._config.rest_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout = max(self._config.request_timeout_ms / 1000.0, 1.0)
        attempt = 0
        while True:
            attempt += 1
            try:
                with url_request.urlopen(req, timeout=timeout) as resp:
                    data = resp.read().decode("utf-8")
                parsed = json.loads(data)
                if isinstance(parsed, list):
                    return parsed
                self._logger.warning("ingest_unexpected_response", extra={"payload": payload})
                return []
            except (url_error.URLError, json.JSONDecodeError) as exc:
                if attempt >= max(self._config.retry.max_attempts, 1):
                    self._logger.error(
                        "ingest_rest_failed",
                        extra={"error": str(exc), "attempts": attempt},
                    )
                    return []
                delay_ms = self._config.retry.next_delay_ms(attempt)
                time.sleep(delay_ms / 1000.0)

    def _fills_to_events(self, fills: Iterable[dict]) -> List[RawPositionEvent]:
        events: List[RawPositionEvent] = []
        for fill in fills:
            event = self._fill_to_raw(fill)
            if event is not None:
                events.append(event)
        return events

    def _fill_to_raw(self, fill: dict) -> Optional[RawPositionEvent]:
        try:
            coin = str(fill["coin"])
            if coin.startswith("@") or coin not in self._config.symbol_map:
                self._logger.warning(
                    "ingest_unmapped_symbol",
                    extra={"coin": coin},
                )
                return None
            symbol = self._config.symbol_map[coin]
            start_pos = float(fill.get("startPosition", 0.0))
            size = float(fill.get("sz", 0.0))
            side = str(fill.get("side", "")).upper()
            delta = size if side == "B" else -size
            next_pos = start_pos + delta
            tx_hash = str(fill.get("hash") or f"tid-{fill.get('tid', '')}")
            event_index = int(fill.get("tid", 0))
            timestamp_ms = int(fill.get("time", 0))
            open_component = None
            close_component = None
            if start_pos > 0 > next_pos or start_pos < 0 < next_pos:
                close_component = abs(start_pos)
                open_component = abs(next_pos)
            return RawPositionEvent(
                symbol=symbol,
                tx_hash=tx_hash,
                event_index=event_index,
                prev_target_net_position=start_pos,
                next_target_net_position=next_pos,
                timestamp_ms=timestamp_ms,
                open_component=open_component,
                close_component=close_component,
            )
        except (KeyError, ValueError, TypeError) as exc:
            self._logger.warning("ingest_fill_parse_failed", extra={"error": str(exc)})
            return None

    @staticmethod
    def _oldest_fill_time(fills: Iterable[dict]) -> Optional[int]:
        times = [int(fill.get("time", 0)) for fill in fills if "time" in fill]
        if not times:
            return None
        return min(times)

    def _should_start_ws(self) -> bool:
        if self._config.mode != "live":
            return False
        if not self._config.enabled or not self._config.ws_url:
            return False
        if not self._config.target_wallet:
            return False
        if websocket is None:
            self._logger.warning("ingest_ws_missing_dependency")
            return False
        return True

    def _start_ws(self) -> None:
        self._ws_app = websocket.WebSocketApp(
            self._config.ws_url,
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
        )
        self._ws_thread = threading.Thread(
            target=self._ws_app.run_forever,
            kwargs={"ping_interval": 20, "ping_timeout": 10},
            daemon=True,
        )
        self._ws_thread.start()

    def _on_ws_open(self, _ws) -> None:
        subscription = {
            "method": "subscribe",
            "subscription": {
                "type": "userFills",
                "user": self._config.target_wallet,
                "aggregateByTime": False,
            },
        }
        try:
            _ws.send(json.dumps(subscription))
            self._ws_enabled = True
            self._last_ws_message_ms = int(time.time() * 1000)
        except Exception as exc:
            self._logger.error("ingest_ws_subscribe_failed", extra={"error": str(exc)})

    def _on_ws_message(self, _ws, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            self._logger.warning("ingest_ws_bad_json")
            return
        self._last_ws_message_ms = int(time.time() * 1000)
        if payload.get("isSnapshot") is True:
            return
        if payload.get("channel") != "userFills":
            return
        data = payload.get("data")
        if isinstance(data, dict) and data.get("isSnapshot") is True:
            return
        fills: List[dict] = []
        if isinstance(data, list):
            fills = data
        elif isinstance(data, dict):
            if "fills" in data and isinstance(data["fills"], list):
                fills = data["fills"]
            elif "data" in data and isinstance(data["data"], list):
                fills = data["data"]
        if not fills:
            return
        with self._ws_lock:
            before = len(self._ws_buffer)
            self._ws_buffer.extend(fills)
            after = len(self._ws_buffer)
            if after < before + len(fills):
                self._logger.warning("ingest_ws_buffer_dropped")
        self._last_ws_message_ms = int(time.time() * 1000)

    def _on_ws_error(self, _ws, error) -> None:
        self._logger.warning("ingest_ws_error", extra={"error": str(error)})
        self._schedule_ws_reconnect()

    def _on_ws_close(self, _ws, status_code, msg) -> None:
        self._ws_enabled = False
        self._logger.warning(
            "ingest_ws_closed",
            extra={"status_code": status_code, "message": msg},
        )
        self._schedule_ws_reconnect()

    def _drain_ws_fills(self) -> List[dict]:
        with self._ws_lock:
            if not self._ws_buffer:
                return []
            fills = list(self._ws_buffer)
            self._ws_buffer.clear()
            return fills

    def _ws_recent(self) -> bool:
        if self._last_ws_message_ms is None:
            return False
        return int(time.time() * 1000) - self._last_ws_message_ms <= 30_000

    def _schedule_ws_reconnect(self) -> None:
        if not self._should_start_ws():
            return
        now_ms = int(time.time() * 1000)
        if self._last_ws_reconnect_ms and now_ms - self._last_ws_reconnect_ms < 5_000:
            return
        self._last_ws_reconnect_ms = now_ms
        threading.Thread(target=self._start_ws, daemon=True).start()

    def close(self) -> None:
        if self._ws_app is not None:
            try:
                self._ws_app.close()
            except Exception:
                return None
        return None


__all__ = [
    "HyperliquidIngestAdapter",
    "HyperliquidIngestConfig",
    "RateLimitPolicy",
    "RateLimiter",
    "RetryPolicy",
]
