"""
Executor (Action Layer)
Handles Order FSM, CCXT integration, smart retry with jitter, idempotent clientOrderId, and timeout -> UNKNOWN handoff to Reconciler.
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


class CircuitBreaker:
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


class Executor:
    def __init__(
        self,
        exec_queue: asyncio.Queue,
        db_conn,
        mode: str = "live",
        ccxt_client: Optional[object] = None,
        submit_timeout_sec: float = 5.0,
        poll_interval_sec: float = 1.0,
    ):
        self.exec_queue = exec_queue
        self.db_conn = db_conn
        self.mode = mode
        self.ccxt_client = ccxt_client
        self.submit_timeout_sec = submit_timeout_sec
        self.poll_interval_sec = poll_interval_sec
        self._stopped = asyncio.Event()
        self._rate_limiter = SimpleRateLimiter(min_interval_sec=0.1)  # ~10 rps default
        self._breaker = CircuitBreaker()

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
            client_order_id = self._build_client_order_id(msg)
            symbol = msg.get("symbol")
            side = msg.get("side", "buy")
            size_usd = msg.get("size_usd")
            order_qty = msg.get("order_qty")
            price = msg.get("price")

            if self.mode == "dry-run":
                self._record_trade(
                    correlation_id=correlation_id,
                    symbol=symbol,
                    side=side,
                    size=size_usd,
                    status="DRY_RUN",
                    exchange_order_id="dry-run",
                    price=price,
                    client_order_id=client_order_id,
                )
                continue

            await self._execute_order(correlation_id, client_order_id, symbol, side, size_usd, order_qty, price)

    async def _execute_order(
        self, correlation_id: str, client_order_id: str, symbol: str, side: str, size_usd: float, order_qty, price
    ):
        if order_qty is None:
            self._record_trade(
                correlation_id,
                symbol,
                side,
                size_usd,
                status="FAILED",
                exchange_order_id="order-qty-missing",
                price=price,
                client_order_id=client_order_id,
                order_qty=None,
            )
            return

        if not self._breaker.allow():
            cooldown = max(self._breaker.open_until - time.monotonic(), 0)
            print(f"[EXECUTOR] circuit open, dropping order_request; cooldown_remaining={cooldown:.2f}s")
            self._record_trade(
                correlation_id,
                symbol,
                side,
                size_usd,
                status="FAILED",
                exchange_order_id="circuit-open",
                price=price,
                client_order_id=client_order_id,
                order_qty=order_qty,
            )
            return

        try:
            exchange_order_id, already_recorded = await self._submit_order(
                correlation_id, symbol, side, size_usd, order_qty, price, client_order_id
            )
            self._breaker.record_success()
        except Exception as exc:  # pragma: no cover - defensive
            self._breaker.record_failure()
            self._record_trade(
                correlation_id,
                symbol,
                side,
                size_usd,
                status="FAILED",
                exchange_order_id="submit-failed",
                price=price,
                client_order_id=client_order_id,
                order_qty=order_qty,
            )
            print(f"[EXECUTOR] submit failed: {exc}")
            return

        if not already_recorded:
            self._record_trade(
                correlation_id,
                symbol,
                side,
                size_usd,
                status="SUBMITTED",
                exchange_order_id=exchange_order_id,
                price=price,
                client_order_id=client_order_id,
                order_qty=order_qty,
            )

        # Poll for fill status (stubbed or real)
        final_status = await self._poll_status(exchange_order_id, symbol, side, size_usd, price)
        self._record_trade(
            correlation_id,
            symbol,
            side,
            size_usd,
            status=final_status,
            exchange_order_id=exchange_order_id,
            price=price,
            client_order_id=client_order_id,
            order_qty=order_qty,
        )

    async def _submit_order(
        self, correlation_id: str, symbol: str, side: str, size_usd: float, order_qty, price, client_order_id: str
    ) -> tuple[str, bool]:
        """
        Submit order via ccxt if provided, else stub.
        """
        if self.ccxt_client:
            params = {"clientOrderId": client_order_id}
            # Assume linear futures market order; adapt as needed
            order = await self.ccxt_client.create_order(symbol, type="market", side=side, amount=order_qty, params=params)
            return order.get("id") or client_order_id, False

        # Stub path
        exchange_order_id = f"stub-{client_order_id}"
        self._record_trade(
            correlation_id=correlation_id,
            symbol=symbol,
            side=side,
            size=size_usd,
            status="SUBMITTED",
            exchange_order_id=exchange_order_id,
            price=price,
            client_order_id=client_order_id,
            order_qty=order_qty,
        )
        # Simulate immediate fill
        return exchange_order_id, True

    async def _poll_status(self, exchange_order_id: str, symbol: str, side: str, size_usd: float, price) -> str:
        if not self.ccxt_client:
            return "FILLED"

        deadline = time.monotonic() + self.submit_timeout_sec
        while time.monotonic() < deadline and not self._stopped.is_set():
            try:
                order = await self.ccxt_client.fetch_order(exchange_order_id, symbol=symbol)
                status = (order.get("status") or "").upper()
                if status in {"CLOSED", "FILLED"}:
                    return "FILLED"
                if status in {"CANCELED", "CANCELLED"}:
                    return "CANCELED"
                if status in {"EXPIRED", "REJECTED"}:
                    return status
            except Exception:  # pragma: no cover - defensive
                pass
            await asyncio.sleep(self.poll_interval_sec)
        return "UNKNOWN"

    def _build_client_order_id(self, msg: dict) -> str:
        tx_hash = msg.get("tx_hash") or "unknown"
        event_index = msg.get("event_index") or 0
        return f"hl-{tx_hash}-{event_index}"

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
        price: Optional[float],
        client_order_id: Optional[str] = None,
        order_qty: Optional[float] = None,
    ):
        cur = self.db_conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO trade_history (correlation_id, symbol, side, size, order_qty, status, exchange_order_id, tx_hash, price, client_order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    correlation_id,
                    symbol,
                    side,
                    size,
                    order_qty,
                    status,
                    exchange_order_id,
                    correlation_id,
                    price,
                    client_order_id,
                ),
            )
        finally:
            cur.close()
