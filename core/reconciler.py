"""
Reconciler (Safety Layer)
Periodically compares exchange state vs DB state and emits alerts/actions.

Current skeleton:
- Runs a periodic loop with configurable interval.
- Placeholder comparison that just logs a heartbeat.
"""

from __future__ import annotations

import asyncio
import time


class Reconciler:
    def __init__(self, db_conn, interval_sec: float = 10.0):
        self.db_conn = db_conn
        self.interval_sec = interval_sec
        self._stopped = asyncio.Event()

    async def run(self):
        while not self._stopped.is_set():
            # TODO: fetch positions from exchange + DB and compute drift
            print(f"[RECONCILER] heartbeat {int(time.time())}")
            await asyncio.sleep(self.interval_sec)

    async def stop(self):
        self._stopped.set()
