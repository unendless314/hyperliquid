"""
Notifier with basic rate limiting and mode tagging.

Ready for future Telegram/Email backends; currently emits structured stdout lines.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

from utils.rate_limiters import SimpleRateLimiter


class Notifier:
    def __init__(self, mode: str = "live", rate_limiter: Optional[SimpleRateLimiter] = None):
        self.mode = mode
        self._stopped = asyncio.Event()
        self._rate_limiter = rate_limiter or SimpleRateLimiter(min_interval_sec=0.5)

    async def send(self, message: str, correlation_id: Optional[str] = None):
        await self._rate_limiter.acquire()
        payload = {
            "ts": int(time.time()),
            "mode": self.mode,
            "message": message,
        }
        if correlation_id:
            payload["correlation_id"] = correlation_id
        # Placeholder backend: stdout; swap to Telegram/email as needed.
        print("[NOTIFY]" + json.dumps(payload, ensure_ascii=False))

    async def stop(self):
        self._stopped.set()
