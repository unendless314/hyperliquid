"""
Reconciler (Safety Layer)
Periodically compares exchange state vs DB state and emits alerts/actions.
Implements warn/critical thresholds and optional auto-close.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional, Dict, Any


class Reconciler:
    def __init__(
        self,
        db_conn,
        ccxt_client: Optional[object] = None,
        notifier: Optional[object] = None,
        interval_sec: float = 60.0,
        warn_threshold: float = 0.01,  # 1% drift
        critical_threshold: float = 0.05,  # 5% drift
        auto_resolve_mode: str = "off",  # off | alert-only | auto-close
    ):
        self.db_conn = db_conn
        self.ccxt_client = ccxt_client
        self.notifier = notifier
        self.interval_sec = interval_sec
        self.warn_threshold = warn_threshold
        self.critical_threshold = critical_threshold
        self.auto_resolve_mode = auto_resolve_mode
        self._stopped = asyncio.Event()

    async def run(self):
        while not self._stopped.is_set():
            try:
                await self._reconcile_once()
            except Exception as exc:  # pragma: no cover - defensive
                print(f"[RECONCILER] error: {exc}")
            await asyncio.sleep(self.interval_sec)

    async def _reconcile_once(self):
        db_positions = self._load_db_positions()
        ex_positions = await self._fetch_exchange_positions()
        if ex_positions is None:
            return

        for symbol, db_pos in db_positions.items():
            ex = ex_positions.get(symbol, {"notional": 0.0, "base": None, "mark_price": None})
            ex_notional = ex.get("notional", 0.0)
            drift = ex_notional - db_pos
            denom = max(abs(ex_notional), abs(db_pos), 1e-9)
            drift_pct = abs(drift) / denom

            if drift_pct < self.warn_threshold:
                continue

            level = "critical" if drift_pct >= self.critical_threshold else "warn"
            msg = f"[RECONCILE][{level.upper()}] {symbol} drift={drift} (ex_notional={ex_notional}, db={db_pos})"
            print(msg)
            if self.notifier:
                await self.notifier.send(msg)

            if level == "critical" and self.auto_resolve_mode == "auto-close" and ex_notional != 0 and self.ccxt_client:
                await self._auto_close(symbol, ex)

    def _load_db_positions(self) -> Dict[str, float]:
        cur = self.db_conn.cursor()
        cur.execute(
            """
            SELECT symbol, SUM(CASE WHEN side='buy' THEN size ELSE -size END) AS net_notional
            FROM trade_history
            GROUP BY symbol
            """
        )
        rows = cur.fetchall()
        cur.close()
        return {row[0]: float(row[1]) for row in rows}

    async def _fetch_exchange_positions(self) -> Optional[Dict[str, Dict[str, float]]]:
        if not self.ccxt_client:
            return {}
        try:
            positions = await self.ccxt_client.fetch_positions()
        except Exception:
            return None
        result: Dict[str, Dict[str, float]] = {}
        for p in positions:
            sym = p.get("symbol")
            notional = float(p.get("notional", 0.0) or 0.0)
            base = None
            for key in ("contracts", "positionAmt", "amount", "size"):
                if p.get(key) is not None:
                    try:
                        base = float(p[key])
                        break
                    except (TypeError, ValueError):
                        pass
            mark_price = None
            for key in ("markPrice", "mark_price", "entryPrice", "entry_price", "price"):
                if p.get(key) is not None:
                    try:
                        mark_price = float(p[key])
                        break
                    except (TypeError, ValueError):
                        pass
            result[sym] = {"notional": notional, "base": base, "mark_price": mark_price}
        return result

    async def _auto_close(self, symbol: str, ex_position: Dict[str, float]):
        notional = ex_position.get("notional", 0.0)
        base = ex_position.get("base")
        mark_price = ex_position.get("mark_price")
        side = "sell" if notional > 0 else "buy"

        if base is None:
            if mark_price and mark_price != 0:
                base = abs(notional) / mark_price
            else:
                # cannot derive size safely
                if self.notifier:
                    await self.notifier.send(f"[RECONCILE][AUTO-CLOSE][SKIP] missing base size for {symbol}")
                return
        amount = abs(base)
        try:
            await self.ccxt_client.create_order(symbol, type="market", side=side, amount=amount)
            if self.notifier:
                await self.notifier.send(f"[RECONCILE][AUTO-CLOSE] {symbol} {side} {amount}")
        except Exception as exc:
            if self.notifier:
                await self.notifier.send(f"[RECONCILE][AUTO-CLOSE][FAIL] {symbol} {exc}")

    async def stop(self):
        self._stopped.set()
