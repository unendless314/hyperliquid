"""
Executor (Action Layer)
Handles Order FSM, CCXT integration, smart retry with jitter, and idempotent clientOrderId.

Current skeleton:
- Consumes order-like messages from exec_queue.
- Logs/prints placeholder handling and writes basic trade_history rows.
"""

from __future__ import annotations

import asyncio


class Executor:
    def __init__(self, exec_queue: asyncio.Queue, db_conn):
        self.exec_queue = exec_queue
        self.db_conn = db_conn
        self._stopped = asyncio.Event()

    async def run(self):
        while not self._stopped.is_set():
            msg = await self.exec_queue.get()
            if msg is None:
                continue
            if msg.get("type") == "noop":
                continue
            if msg.get("type") != "order_request":
                continue

            # Placeholder FSM: mark SUBMITTED then immediately FILLED
            correlation_id = msg.get("tx_hash")
            symbol = msg.get("symbol")
            side = msg.get("side", "buy")
            size = msg.get("size_usd")

            exchange_order_id = f"stub-{correlation_id}"
            self._record_trade(
                correlation_id=correlation_id,
                symbol=symbol,
                side=side,
                size=size,
                status="SUBMITTED",
                exchange_order_id=exchange_order_id,
            )
            self._record_trade(
                correlation_id=correlation_id,
                symbol=symbol,
                side=side,
                size=size,
                status="FILLED",
                exchange_order_id=exchange_order_id,
            )
            print(f"[EXECUTOR] submitted stub order {exchange_order_id} {side} {size} {symbol}")

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
