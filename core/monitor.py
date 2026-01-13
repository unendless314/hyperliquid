"""
Monitor (Ingestion Layer)
Responsible for WebSocket connection to Hyperliquid, cursor tracking, gap detection/backfill, and dedup gatekeeping.

This module currently implements a minimal async skeleton that:
- Accepts an async queue to push normalized events downstream.
- Accepts a DB connection for dedup placeholder (no real dedup yet).
- Provides a `run()` coroutine that emits heartbeat events for now.
"""

from __future__ import annotations

import asyncio
from typing import Any


class Monitor:
    def __init__(self, queue: asyncio.Queue, db_conn):
        self.queue = queue
        self.db_conn = db_conn
        self._stopped = asyncio.Event()

    async def run(self):
        """
        Placeholder loop: periodically emits heartbeat events.
        Replace with WS ingest + gap detection/backfill + dedup logic.
        """
        while not self._stopped.is_set():
            await self.queue.put({"type": "heartbeat", "source": "monitor"})
            await asyncio.sleep(1)

    async def stop(self):
        self._stopped.set()
