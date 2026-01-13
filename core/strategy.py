"""
Strategy (Processing Layer)
Performs symbol mapping, risk checks (price deviation, filters), position sizing, and produces OrderRequest objects.

Current implementation:
- Consumes events from monitor_queue.
- Emits order requests onto exec_queue for the Executor.
- Implements basic sizing for copy_mode fixed_amount/proportional; skips if insufficient data.
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
                continue

            if event.get("type") != "fill":
                continue

            order_req = self._build_order_request(event)
            if order_req:
                await self.exec_queue.put(order_req)

    async def stop(self):
        self._stopped.set()
        # wake the queue in case run() is blocked on get
        await self.monitor_queue.put(None)

    def _build_order_request(self, event: dict) -> Any:
        """
        Map Hyperliquid symbol to CEX symbol, apply sizing, and emit order request.
        """
        hl_symbol = event.get("symbol")
        side = event.get("side", "buy")

        symbol_mapping = self.settings.get("symbol_mapping", {})
        cex_symbol = symbol_mapping.get(hl_symbol)
        if not cex_symbol:
            print(f"[STRATEGY] unknown symbol mapping for {hl_symbol}, skip")
            return None

        size_usd = self._calculate_size_usd(event)
        if not size_usd:
            print("[STRATEGY] cannot determine size_usd, skip event")
            return None

        return {
            "type": "order_request",
            "symbol": cex_symbol,
            "side": side,
            "size_usd": size_usd,
            "source": "strategy",
            "tx_hash": event.get("tx_hash"),
            "event_index": event.get("event_index"),
        }

    def _calculate_size_usd(self, event: dict) -> float:
        copy_mode = self.settings.get("copy_mode", "fixed_amount")

        if copy_mode == "fixed_amount":
            return float(self.settings.get("fixed_amount_usd", 0.0))

        if copy_mode == "proportional":
            whale_notional = event.get("notional_usd")
            if whale_notional is None:
                # Fallback: derive notional if size/price are present
                qty = event.get("size") or event.get("amount")
                price = event.get("price")
                if qty is not None and price is not None:
                    whale_notional = float(qty) * float(price)
            whale_balance = float(self.settings.get("whale_estimated_balance", 0.0))
            my_balance = float(self.settings.get("my_account_balance_override", 0.0)) or whale_balance
            if not whale_notional or whale_balance <= 0:
                return 0.0
            ratio = my_balance / whale_balance
            return whale_notional * ratio

        # Kelly or others not yet implemented
        return 0.0
