"""
Notifier stub.

Provide a simple interface to send alerts (e.g., Telegram/email). For now, it logs to stdout.
"""

from __future__ import annotations

import asyncio
import time


class Notifier:
    def __init__(self):
        self._stopped = asyncio.Event()

    async def send(self, message: str):
        # TODO: integrate Telegram or other channels
        print(f"[NOTIFY] {int(time.time())} {message}")

    async def stop(self):
        self._stopped.set()
