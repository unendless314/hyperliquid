"""
Hyperliquid WebSocket adapter for Monitor.

This is a thin wrapper that turns the hyperliquid-python-sdk stream into an async iterator of fills.
If the SDK is unavailable, instantiating the adapter will raise to signal the dependency is missing.

Note: The adapter is intentionally minimal; production deployments should add reconnect/backoff and
subscription confirmation handling as needed.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional


class HyperliquidWsAdapter:
    def __init__(self, wallet: str, base_url: str = "wss://api.hyperliquid.xyz/ws"):
        try:
            from hyperliquid.info_ws import InfoStream  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("hyperliquid-python-sdk is required for WS ingest") from exc

        self.wallet = wallet
        self.base_url = base_url
        self._queue: asyncio.Queue = asyncio.Queue()
        self._stream = InfoStream(
            base_url=self.base_url,
            subscriptions=[{"type": "userFills", "user": self.wallet}],
            on_update=self._on_update,
        )

    def _on_update(self, msg: Dict[str, Any]):
        # Push raw fill events into the async queue; Monitor will normalize/dedup
        if msg:
            self._queue.put_nowait(msg)

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self._queue.get()

    async def close(self):
        close_fn = getattr(self._stream, "close", None)
        if close_fn:
            res = close_fn()
            if asyncio.iscoroutine(res):
                await res
