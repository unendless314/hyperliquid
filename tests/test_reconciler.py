import asyncio
import contextlib

import pytest

from core.reconciler import Reconciler
from utils.db import init_sqlite


class StubCcxt:
    def __init__(self, positions):
        self.positions = positions
        self.created = []

    async def fetch_positions(self):
        return self.positions

    async def create_order(self, symbol, type, side, amount):
        self.created.append((symbol, side, amount))
        return {"id": f"close-{symbol}"}


class StubNotifier:
    def __init__(self):
        self.msgs = []

    async def send(self, msg: str):
        self.msgs.append(msg)


def seed_trades(conn, symbol, notional):
    cur = conn.cursor()
    side = "buy" if notional >= 0 else "sell"
    cur.execute(
        "INSERT INTO trade_history (correlation_id, symbol, side, size, status, exchange_order_id, tx_hash) VALUES (?, ?, ?, ?, 'FILLED', 'stub', ?)",
        ("seed", symbol, side, abs(notional), "seed"),
    )
    conn.commit()
    cur.close()


@pytest.mark.asyncio
async def test_reconciler_warn_and_critical_auto_close_uses_base_size():
    conn = init_sqlite(":memory:")
    seed_trades(conn, "BTC/USDT", 10.0)  # db thinks +10 notional

    notifier = StubNotifier()
    ccxt = StubCcxt(
        [
            {
                "symbol": "BTC/USDT",
                "notional": 200.0,  # USD
                "contracts": 0.01,  # base size
                "markPrice": 20000.0,
            }
        ]
    )  # exchange has +0.01 BTC (~200 USD), drift ~190 => critical

    reconciler = Reconciler(
        conn,
        ccxt_client=ccxt,
        notifier=notifier,
        interval_sec=0.01,
        warn_threshold=0.01,
        critical_threshold=0.05,
        auto_resolve_mode="auto-close",
    )

    task = asyncio.create_task(reconciler.run())
    await asyncio.sleep(0.05)
    await reconciler.stop()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert any("CRITICAL" in m for m in notifier.msgs)
    # auto-close invoked with base size (0.01), not USD notional
    assert len(ccxt.created) >= 1
    assert ccxt.created[0] == ("BTC/USDT", "sell", 0.01)


@pytest.mark.asyncio
async def test_reconciler_warn_only_no_auto_close():
    conn = init_sqlite(":memory:")
    seed_trades(conn, "ETH/USDT", 1.0)
    notifier = StubNotifier()
    ccxt = StubCcxt([{"symbol": "ETH/USDT", "notional": 0.9}])  # small drift

    reconciler = Reconciler(
        conn,
        ccxt_client=ccxt,
        notifier=notifier,
        interval_sec=0.01,
        warn_threshold=0.01,
        critical_threshold=0.2,
        auto_resolve_mode="alert-only",
    )
    task = asyncio.create_task(reconciler.run())
    await asyncio.sleep(0.05)
    await reconciler.stop()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert any("WARN" in m for m in notifier.msgs)
    assert not ccxt.created
