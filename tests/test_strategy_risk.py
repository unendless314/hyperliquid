import asyncio
import contextlib

import pytest

from core.executor import Executor
from core.strategy import Strategy
from utils.db import init_sqlite


@pytest.mark.asyncio
async def test_strategy_drops_when_exceeds_capital_hard_limit():
    settings = {
        "symbol_mapping": {"BTC": "BTC/USDT"},
        "copy_mode": "fixed_amount",
        "fixed_amount_usd": 80.0,
        "capital_utilization_hard_limit": 0.5,  # 80 / 100 = 0.8 > 0.5 => drop
        "whale_estimated_balance": 100.0,
    }
    conn = init_sqlite(":memory:")
    monitor_queue: asyncio.Queue = asyncio.Queue()
    exec_queue: asyncio.Queue = asyncio.Queue()

    strategy = Strategy(monitor_queue, exec_queue, settings)
    executor = Executor(exec_queue, conn)

    strat_task = asyncio.create_task(strategy.run())
    exec_task = asyncio.create_task(executor.run())

    await monitor_queue.put({"type": "fill", "symbol": "BTC", "tx_hash": "risk1", "event_index": 0})
    await asyncio.sleep(0.05)

    await strategy.stop()
    await executor.stop()
    strat_task.cancel()
    exec_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await strat_task
    with contextlib.suppress(asyncio.CancelledError):
        await exec_task

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM trade_history WHERE correlation_id='risk1'")
    count = cur.fetchone()[0]
    assert count == 0
