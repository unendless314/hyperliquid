import asyncio
import contextlib

import pytest

from core.executor import Executor
from core.strategy import Strategy
from utils.db import init_sqlite


@pytest.mark.asyncio
async def test_strategy_executor_fixed_amount_flow():
    settings = {
        "symbol_mapping": {"BTC": "BTC/USDT"},
        "copy_mode": "fixed_amount",
        "fixed_amount_usd": 123.0,
    }
    conn = init_sqlite(":memory:")

    monitor_queue: asyncio.Queue = asyncio.Queue()
    exec_queue: asyncio.Queue = asyncio.Queue()

    strategy = Strategy(monitor_queue, exec_queue, settings)
    executor = Executor(exec_queue, conn)

    strat_task = asyncio.create_task(strategy.run())
    exec_task = asyncio.create_task(executor.run())

    fill_event = {
        "type": "fill",
        "symbol": "BTC",
        "tx_hash": "tx1",
        "event_index": 0,
    }
    await monitor_queue.put(fill_event)

    # allow pipeline to process
    await asyncio.sleep(0.05)

    await strategy.stop()
    await executor.stop()
    strat_task.cancel()
    exec_task.cancel()
    # Tasks may already be finished; suppress CancelledError to avoid flakes
    with contextlib.suppress(asyncio.CancelledError):
        await strat_task
    with contextlib.suppress(asyncio.CancelledError):
        await exec_task

    cur = conn.cursor()
    cur.execute("SELECT symbol, size, status FROM trade_history WHERE correlation_id='tx1'")
    rows = cur.fetchall()
    assert ("BTC/USDT", 123.0, "SUBMITTED") in rows
    assert ("BTC/USDT", 123.0, "FILLED") in rows
