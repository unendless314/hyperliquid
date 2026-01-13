"""
Executor (Action Layer)
Handles Order FSM, CCXT integration, smart retry with jitter, and idempotent clientOrderId.

Current implementation:
- Consumes order-like messages from exec_queue.
- Applies a simple rate limiter and backoff scaffold.
- Records FSM transitions into trade_history (stubbed exchange).
- Honors mode: backfill-only ignores orders; dry-run records DRY_RUN instead of executing.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Optional


class SimpleRateLimiter:
    """Tokenless limiter enforcing min interval between operations."""

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


class Executor:
    def __init__(self, exec_queue: asyncio.Queue, db_conn, mode: str = "live"):
        self.exec_queue = exec_queue
        self.db_conn = db_conn
        self.mode = mode
        self._stopped = asyncio.Event()
        self._rate_limiter = SimpleRateLimiter(min_interval_sec=0.1)  # ~10 rps default

    async def run(self):
        while not self._stopped.is_set():
            msg = await self.exec_queue.get()
            if msg is None:
                continue
            if msg.get("type") == "noop":
                continue
            if msg.get("type") != "order_request":
                continue

            # Respect modes
            if self.mode == "backfill-only":
                print("[EXECUTOR] backfill-only: drop order_request")
                continue

            await self._rate_limiter.acquire()

            correlation_id = msg.get("tx_hash")
            symbol = msg.get("symbol")
            side = msg.get("side", "buy")
            size = msg.get("size_usd")

            if self.mode == "dry-run":
                self._record_trade(
                    correlation_id=correlation_id,
                    symbol=symbol,
                    side=side,
                    size=size,
                    status="DRY_RUN",
                    exchange_order_id="dry-run",
                )
                continue

            await self._execute_stub_order(correlation_id, symbol, side, size)

    async def _execute_stub_order(self, correlation_id: str, symbol: str, side: str, size: float):
        """
        Stubbed order submission with simple backoff scaffold.
        """
        exchange_order_id = f"stub-{correlation_id}"

        attempt = 0
        while True:
            if self._stopped.is_set():
                return
            attempt += 1
            try:
                self._record_trade(
                    correlation_id=correlation_id,
                    symbol=symbol,
                    side=side,
                    size=size,
                    status="SUBMITTED",
                    exchange_order_id=exchange_order_id,
                )
                # Simulate success
                self._record_trade(
                    correlation_id=correlation_id,
                    symbol=symbol,
                    side=side,
                    size=size,
                    status="FILLED",
                    exchange_order_id=exchange_order_id,
                )
                print(f"[EXECUTOR] submitted stub order {exchange_order_id} {side} {size} {symbol}")
                return
            except Exception as exc:  # pragma: no cover - defensive
                backoff = min(1.0 * (2 ** (attempt - 1)), 5.0)
                jitter = random.uniform(0, 0.1)
                print(f"[EXECUTOR] error {exc}, retrying in {backoff + jitter:.2f}s")
                await asyncio.sleep(backoff + jitter)
                if self._stopped.is_set():
                    return

    async def stop(self):
        self._stopped.set()
        # wake the queue in case run() is blocked on get
        await self.exec_queue.put(None)

    def _record_trade(
        self,
        correlation_id: str,
        symbol: str,
        side: str,
        size: float,
        status: str,
        exchange_order_id: str,
    ):
        cur = self.db_conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO trade_history (correlation_id, symbol, side, size, status, exchange_order_id, tx_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (correlation_id, symbol, side, size, status, exchange_order_id, correlation_id),
            )
        finally:
            cur.close()
