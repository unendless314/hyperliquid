import asyncio
import contextlib

import pytest

from core.monitor import Monitor
from utils.db import init_sqlite


class FiniteWs:
    def __init__(self, events):
        self.events = events
        self._iter = iter(self.events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.asyncio
async def test_monitor_consumes_ws_events_and_dedups():
    conn = init_sqlite(":memory:")
    queue: asyncio.Queue = asyncio.Queue()
    events = [
        {"tx_hash": "a", "event_index": 0, "symbol": "BTC", "timestamp": 1},
        {"tx_hash": "a", "event_index": 0, "symbol": "BTC", "timestamp": 1},  # dup
        {"tx_hash": "b", "event_index": 0, "symbol": "ETH", "timestamp": 2},
    ]
    ws = FiniteWs(events)
    monitor = Monitor(queue, conn, settings={}, ws_client=ws, rest_client=None, run_once=True, cleanup_interval_seconds=0)

    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(0.05)
    await monitor.stop()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert queue.qsize() == 2
    msgs = [queue.get_nowait() for _ in range(2)]
    hashes = {m["tx_hash"] for m in msgs}
    assert hashes == {"a", "b"}

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM processed_txs")
    assert cur.fetchone()[0] == 2
