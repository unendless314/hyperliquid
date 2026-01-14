import asyncio
import contextlib

import pytest

from core.executor import Executor
from utils.db import init_sqlite


class FlakyCcxt:
    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls = 0

    async def create_order(self, symbol, type, side, amount, params):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise Exception("transient")
        return {"id": f"ex-{symbol}-{self.calls}", "status": "open"}

    async def fetch_order(self, order_id, symbol=None):
        return {"status": "closed"}


@pytest.mark.asyncio
async def test_executor_retries_ccxt_submit_and_succeeds():
    conn = init_sqlite(":memory:")
    exec_queue: asyncio.Queue = asyncio.Queue()
    ccxt = FlakyCcxt(fail_times=2)
    executor = Executor(exec_queue, conn, ccxt_client=ccxt, max_submit_retries=3, base_retry_backoff=0.01, max_retry_backoff=0.02)

    task = asyncio.create_task(executor.run())

    await exec_queue.put(
        {
            "type": "order_request",
            "symbol": "BTC/USDT",
            "side": "buy",
            "size_usd": 100.0,
            "order_qty": 1.0,
            "price": 100.0,
            "tx_hash": "tx-retry",
            "event_index": 0,
        }
    )

    await asyncio.sleep(0.2)
    await executor.stop()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    cur = conn.cursor()
    cur.execute("SELECT status FROM trade_history WHERE correlation_id='tx-retry'")
    statuses = {row[0] for row in cur.fetchall()}
    assert statuses >= {"SUBMITTED", "FILLED"}
    assert ccxt.calls == 3
