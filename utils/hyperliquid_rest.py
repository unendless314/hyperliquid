"""
Hyperliquid REST adapter for Monitor backfill/gap detection.

Uses the public Hyperliquid info endpoint to fetch user fills by wallet.
Implements the minimal surface Monitor expects:
    - get_latest_cursor() -> int
    - fetch_range(start_cursor, end_cursor) -> list[dict]

Cursor semantics:
- When using cursor_mode="timestamp", cursor corresponds to Hyperliquid fill `time` (ms).
- Block heights are not available via the public fills API; prefer cursor_mode="timestamp" when enabling this adapter.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import requests


class HyperliquidRestError(RuntimeError):
    pass


def _post_sync(base_url: str, payload: dict) -> dict:
    resp = requests.post(base_url, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise HyperliquidRestError(f"unexpected response shape: {data!r}")
    return data


async def _post(base_url: str, payload: dict) -> dict:
    # run blocking requests in a thread to avoid blocking the event loop
    return await asyncio.to_thread(_post_sync, base_url, payload)


class HyperliquidRestAdapter:
    def __init__(self, wallet: str, base_url: str = "https://api.hyperliquid.xyz/info"):
        self.wallet = wallet
        self.base_url = base_url.rstrip("/")

    async def get_latest_cursor(self) -> Optional[int]:
        """
        Fetch the most recent fill and return its timestamp (ms).
        Returns None if no fills are found.
        """
        payload = {"type": "userFills", "user": self.wallet, "limit": 1}
        data = await _post(self.base_url, payload)
        fills = data.get("userFills") or []
        if not fills:
            return None
        latest_ts = max(int(fill.get("time")) for fill in fills if fill.get("time") is not None)
        return latest_ts

    async def fetch_range(self, start_cursor: int, end_cursor: int) -> List[Dict[str, Any]]:
        """
        Fetch fills whose timestamps fall within [start_cursor, end_cursor].
        Returns a list of raw events compatible with Monitor._handle_raw_event.
        """
        payload = {
            "type": "userFills",
            "user": self.wallet,
            "startTime": int(start_cursor),
            "endTime": int(end_cursor),
        }
        data = await _post(self.base_url, payload)
        fills = data.get("userFills") or []
        # Normalize fields to those expected by Monitor
        normalized = []
        for fill in fills:
            normalized.append(
                {
                    "tx_hash": fill.get("txHash") or fill.get("hash"),
                    "event_index": fill.get("eventId") or fill.get("event_index", 0),
                    "symbol": fill.get("coin") or fill.get("symbol"),
                    "block_height": fill.get("block"),  # likely None; cursor_mode should be timestamp
                    "timestamp": fill.get("time"),
                    "price": fill.get("px") or fill.get("price"),
                    "size": fill.get("sz") or fill.get("size"),
                    "side": fill.get("side"),
                    "quoteQuantity": fill.get("quoteQuantity"),
                    "orderId": fill.get("oid") or fill.get("orderId"),
                    "clientOrderId": fill.get("clientOrderId"),
                }
            )
        return normalized
