"""
Notifier with basic rate limiting, mode tagging, and optional Telegram delivery.

Defaults to structured stdout; if telegram_enabled, will POST to Telegram Bot API.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

import logging
import requests

from utils.rate_limiters import SimpleRateLimiter


class Notifier:
    def __init__(
        self,
        mode: str = "live",
        rate_limiter: Optional[SimpleRateLimiter] = None,
        telegram_enabled: bool = False,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        telegram_base_url: str = "https://api.telegram.org",
        dedup_cooldown_sec: float = 5.0,
    ):
        self.mode = mode
        self._stopped = asyncio.Event()
        self._rate_limiter = rate_limiter or SimpleRateLimiter(min_interval_sec=0.5)
        self.telegram_enabled = telegram_enabled
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.telegram_base_url = telegram_base_url.rstrip("/")
        self.dedup_cooldown_sec = dedup_cooldown_sec
        self._last_sent: dict[str, float] = {}

    async def send(self, message: str, correlation_id: Optional[str] = None):
        await self._rate_limiter.acquire()
        now = time.time()
        key = message
        last = self._last_sent.get(key, 0)
        if now - last < self.dedup_cooldown_sec:
            return
        self._last_sent[key] = now

        payload = {
            "ts": int(now),
            "mode": self.mode,
            "message": message,
        }
        if correlation_id:
            payload["correlation_id"] = correlation_id

        # Always stdout as local fallback
        print("[NOTIFY] " + json.dumps(payload, ensure_ascii=False))

        if self.telegram_enabled and self.telegram_bot_token and self.telegram_chat_id:
            await self._send_telegram(message)

    async def _send_telegram(self, message: str):
        url = f"{self.telegram_base_url}/bot{self.telegram_bot_token}/sendMessage"
        data = {"chat_id": self.telegram_chat_id, "text": message}
        try:
            # run blocking requests in thread to keep async loop free
            resp = await asyncio.to_thread(requests.post, url, data=data, timeout=10)
            if resp.status_code >= 300:
                logging.getLogger(__name__).warning(
                    "notifier_telegram_non_200", extra={"status": resp.status_code, "text": getattr(resp, "text", "")}
                )
        except Exception as exc:
            logging.getLogger(__name__).warning("notifier_telegram_error", exc_info=exc)

    async def stop(self):
        self._stopped.set()
