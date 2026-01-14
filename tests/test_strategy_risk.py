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


@pytest.mark.asyncio
async def test_strategy_drops_when_min_notional_not_met():
    settings = {
        "symbol_mapping": {"BTC": "BTC/USDT"},
        "copy_mode": "fixed_amount",
        "fixed_amount_usd": 10.0,
        "capital_utilization_hard_limit": 1.0,
        "whale_estimated_balance": 1000.0,
        "binance_filters": {"BTC/USDT": {"min_notional": 50, "min_qty": 0.001, "step_size": 0.001}},
    }
    conn = init_sqlite(":memory:")
    monitor_queue: asyncio.Queue = asyncio.Queue()
    exec_queue: asyncio.Queue = asyncio.Queue()

    strategy = Strategy(monitor_queue, exec_queue, settings)
    executor = Executor(exec_queue, conn)

    strat_task = asyncio.create_task(strategy.run())
    exec_task = asyncio.create_task(executor.run())

    await monitor_queue.put(
        {"type": "fill", "symbol": "BTC", "tx_hash": "risk2", "event_index": 0, "price": 100, "size": 0.004}
    )
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
    cur.execute("SELECT COUNT(*) FROM trade_history WHERE correlation_id='risk2'")
    assert cur.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_strategy_drops_on_step_size_violation():
    settings = {
        "symbol_mapping": {"ETH": "ETH/USDT"},
        "copy_mode": "fixed_amount",
        "fixed_amount_usd": 50.0,
        "capital_utilization_hard_limit": 1.0,
        "whale_estimated_balance": 1000.0,
        "binance_filters": {"ETH/USDT": {"step_size": 0.01}},
    }
    conn = init_sqlite(":memory:")
    monitor_queue: asyncio.Queue = asyncio.Queue()
    exec_queue: asyncio.Queue = asyncio.Queue()

    strategy = Strategy(monitor_queue, exec_queue, settings)
    executor = Executor(exec_queue, conn)

    strat_task = asyncio.create_task(strategy.run())
    exec_task = asyncio.create_task(executor.run())

    await monitor_queue.put(
        {"type": "fill", "symbol": "ETH", "tx_hash": "risk3", "event_index": 0, "price": 2000, "size": 0.005}
    )
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
    cur.execute("SELECT COUNT(*) FROM trade_history WHERE correlation_id='risk3'")
    assert cur.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_strategy_respects_filters_using_target_order_qty():
    settings = {
        "symbol_mapping": {"BTC": "BTC/USDT"},
        "copy_mode": "fixed_amount",
        "fixed_amount_usd": 100.0,  # will produce order_qty=1 at price=100
        "capital_utilization_hard_limit": 1.0,
        "whale_estimated_balance": 1000.0,
        "binance_filters": {"BTC/USDT": {"min_notional": 50, "min_qty": 0.001, "step_size": 0.001}},
    }
    conn = init_sqlite(":memory:")
    monitor_queue: asyncio.Queue = asyncio.Queue()
    exec_queue: asyncio.Queue = asyncio.Queue()

    strategy = Strategy(monitor_queue, exec_queue, settings)
    executor = Executor(exec_queue, conn)

    strat_task = asyncio.create_task(strategy.run())
    exec_task = asyncio.create_task(executor.run())

    # HL fill is tiny, but target order derived from fixed_amount should pass filters
    await monitor_queue.put(
        {"type": "fill", "symbol": "BTC", "tx_hash": "risk5", "event_index": 0, "price": 100, "size": 0.004}
    )
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
    cur.execute("SELECT COUNT(*) FROM trade_history WHERE correlation_id='risk5'")
    assert cur.fetchone()[0] == 2  # SUBMITTED + FILLED recorded by executor stub


@pytest.mark.asyncio
async def test_strategy_drops_on_stale_event():
    settings = {
        "symbol_mapping": {"SOL": "SOL/USDT"},
        "copy_mode": "fixed_amount",
        "fixed_amount_usd": 20.0,
        "capital_utilization_hard_limit": 1.0,
        "whale_estimated_balance": 1000.0,
        "max_stale_ms": 1,  # extremely small to force drop
    }
    conn = init_sqlite(":memory:")
    monitor_queue: asyncio.Queue = asyncio.Queue()
    exec_queue: asyncio.Queue = asyncio.Queue()

    strategy = Strategy(monitor_queue, exec_queue, settings)
    executor = Executor(exec_queue, conn)

    strat_task = asyncio.create_task(strategy.run())
    exec_task = asyncio.create_task(executor.run())

    await monitor_queue.put(
        {"type": "fill", "symbol": "SOL", "tx_hash": "risk4", "event_index": 0, "timestamp": 0}
    )
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
    cur.execute("SELECT COUNT(*) FROM trade_history WHERE correlation_id='risk4'")
    assert cur.fetchone()[0] == 0
