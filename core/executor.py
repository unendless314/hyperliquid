"""
Executor (Action Layer)
Handles Order FSM, CCXT integration, smart retry with jitter, and idempotent clientOrderId.

Current skeleton:
- Consumes order-like messages from exec_queue.
- Logs/prints placeholder handling.
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
            print(f"[EXECUTOR] received: {msg}")
            # TODO: implement FSM and exchange interactions

    async def stop(self):
        self._stopped.set()
