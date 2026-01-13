"""
Strategy (Processing Layer)
Performs symbol mapping, risk checks (price deviation, filters), position sizing, and produces OrderRequest objects.

Current implementation:
- Consumes events from monitor_queue.
- Emits order requests onto exec_queue for the Executor.
- Implements basic sizing for copy_mode fixed_amount/proportional; skips if insufficient data.
- Adds lightweight risk gates: symbol mapping presence, positive size, optional capital utilization and price deviation checks.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


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
            logger.warning("strategy_skip_unknown_symbol", extra={"symbol": hl_symbol})
            return None

        size_usd = self._calculate_size_usd(event)
        if not size_usd:
            logger.warning("strategy_skip_size_missing", extra={"symbol": hl_symbol})
            return None

        if not self._passes_risk(event, size_usd):
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

    def _passes_risk(self, event: dict, size_usd: float) -> bool:
        # Positive size check
        if size_usd <= 0:
            return False

        # Capital utilization check
        hard = self.settings.get("capital_utilization_hard_limit")
        balance = self.settings.get("my_account_balance_override") or self.settings.get("whale_estimated_balance")
        if hard is not None and balance:
            if size_usd / balance > float(hard):
                logger.error(
                    "strategy_drop_hard_capital_limit",
                    extra={
                        "size_usd": size_usd,
                        "balance": balance,
                        "ratio": size_usd / balance,
                        "hard_limit": float(hard),
                    },
                )
                return False

        soft = self.settings.get("capital_utilization_soft_limit")
        if soft is not None and balance:
            if size_usd / balance > float(soft):
                logger.warning(
                    "strategy_warn_soft_capital_limit",
                    extra={
                        "size_usd": size_usd,
                        "balance": balance,
                        "ratio": size_usd / balance,
                        "soft_limit": float(soft),
                    },
                )

        # Price deviation checks (only if both prices present)
        ref_price = event.get("reference_price")
        trade_price = event.get("price")
        if ref_price is not None and trade_price is not None:
            pct = abs(trade_price - ref_price) / ref_price
            pct_limit = self.settings.get("price_deviation_pct")
            abs_limit = self.settings.get("price_deviation_usd")
            if pct_limit is not None and pct > float(pct_limit):
                logger.error(
                    "strategy_drop_price_deviation_pct",
                    extra={
                        "pct": pct,
                        "pct_limit": float(pct_limit),
                        "price": trade_price,
                        "reference_price": ref_price,
                    },
                )
                return False
            if abs_limit is not None and abs(trade_price - ref_price) > float(abs_limit):
                logger.error(
                    "strategy_drop_price_deviation_abs",
                    extra={
                        "abs_diff": abs(trade_price - ref_price),
                        "abs_limit": float(abs_limit),
                        "price": trade_price,
                        "reference_price": ref_price,
                    },
                )
                return False

        return True
