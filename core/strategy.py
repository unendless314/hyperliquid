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
        size_native = event.get("size") or event.get("amount")
        price = event.get("price")

        symbol_mapping = self.settings.get("symbol_mapping", {})
        cex_symbol = symbol_mapping.get(hl_symbol)
        if not cex_symbol:
            logger.warning("strategy_skip_unknown_symbol", extra={"symbol": hl_symbol})
            return None

        size_usd = self._calculate_size_usd(event)
        if not size_usd:
            logger.warning("strategy_skip_size_missing", extra={"symbol": hl_symbol})
            return None

        order_qty = None
        if price is not None:
            try:
                order_qty = float(size_usd) / float(price)
            except (TypeError, ValueError, ZeroDivisionError):
                logger.error("strategy_drop_invalid_price_for_qty", extra={"price": price})
                return None

        if not self._passes_risk(event, size_usd, cex_symbol, size_native, price, order_qty):
            return None

        return {
            "type": "order_request",
            "symbol": cex_symbol,
            "side": side,
            "size_usd": size_usd,
            "size": size_native,
            "order_qty": order_qty,
            "price": price,
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

    def _passes_risk(
        self, event: dict, size_usd: float, cex_symbol: str, size_native: Any, price: Any, order_qty: Any
    ) -> bool:
        # Positive size check
        if size_usd <= 0:
            return False

        # Freshness check
        max_stale_ms = self.settings.get("max_stale_ms")
        if max_stale_ms is not None:
            ts = event.get("timestamp")
            if ts is None:
                logger.error("strategy_drop_missing_timestamp_for_freshness")
                return False
            import time

            now_ms = int(time.time() * 1000)
            if (now_ms - int(ts)) > int(max_stale_ms):
                logger.error(
                    "strategy_drop_stale_event",
                    extra={"age_ms": now_ms - int(ts), "max_stale_ms": max_stale_ms},
                )
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

        # Binance filters (MinQty, StepSize, MinNotional)
        filters = self.settings.get("binance_filters", {}).get(cex_symbol)
        if filters:
            try:
                min_qty = float(filters.get("min_qty")) if filters.get("min_qty") is not None else None
                step_size = float(filters.get("step_size")) if filters.get("step_size") is not None else None
                min_notional = float(filters.get("min_notional")) if filters.get("min_notional") is not None else None
            except (TypeError, ValueError):
                logger.error("strategy_filters_invalid", extra={"filters": filters, "symbol": cex_symbol})
                return False

            # Filters should apply to the size we plan to place, not the source fill size
            if order_qty is None:
                logger.error("strategy_drop_missing_price_for_filters", extra={"symbol": cex_symbol})
                return False

            order_qty_f = float(order_qty)
            if min_qty is not None and order_qty_f < min_qty:
                logger.error(
                    "strategy_drop_min_qty",
                    extra={"size": order_qty_f, "min_qty": min_qty, "symbol": cex_symbol},
                )
                return False
            if step_size is not None:
                # accept small floating error
                steps = order_qty_f / step_size
                if abs(round(steps) - steps) > 1e-6:
                    logger.error(
                        "strategy_drop_step_size",
                        extra={"size": order_qty_f, "step_size": step_size, "symbol": cex_symbol},
                    )
                    return False
            if min_notional is not None:
                notional = float(size_usd)
                if notional < min_notional:
                    logger.error(
                        "strategy_drop_min_notional",
                        extra={"notional": notional, "min_notional": min_notional, "symbol": cex_symbol},
                    )
                    return False

        return True
