"""
Strategy (Processing Layer)
Performs symbol mapping, risk checks (price deviation, filters), position sizing, and produces OrderRequest objects.

Current skeleton:
- Consumes events from monitor_queue.
- Emits order requests onto exec_queue for the Executor.
- No real sizing/risk yet; only passes through heartbeat for observability.
"""

from __future__ import annotations

import asyncio
from typing import Any


class Strategy:
    def __init__(self, monitor_queue: asyncio.Queue, exec_queue: asyncio.Queue, settings: dict):
        self.monitor_queue = monitor_queue
        self.exec_queue = exec_queue
        self.settings = settings
        self._stopped = asyncio.Event()

    async def run(self):
        while not self._stopped.is_set():
            event = await self.monitor_queue.get()
            if event is None:
                continue

            if event.get("type") == "heartbeat":
                # Pass through as a no-op order placeholder to keep the pipe warm
                await self.exec_queue.put({"type": "noop", "source": "strategy"})
            # TODO: implement real mapping, risk checks, position sizing, freshness checks

    async def stop(self):
        self._stopped.set()
