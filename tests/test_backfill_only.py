import asyncio
import contextlib

import pytest

from core.monitor import Monitor
from utils.db import init_sqlite, get_system_state


class FakeWs:
    def __init__(self, events):
        self.events = events

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.events:
            raise StopAsyncIteration
        return self.events.pop(0)


@pytest.mark.asyncio
async def test_backfill_only_runs_monitor_and_updates_cursor_without_trades():
    conn = init_sqlite(":memory:")
    q: asyncio.Queue = asyncio.Queue()
    ws = FakeWs(
        [
            {"type": "fill", "symbol": "BTC", "tx_hash": "tx1", "event_index": 0, "timestamp": 111},
            {"type": "fill", "symbol": "ETH", "tx_hash": "tx2", "event_index": 1, "timestamp": 222},
        ]
    )

    monitor = Monitor(
        q,
        conn,
        settings={"cursor_mode": "timestamp"},
        ws_client=ws,
        backfill_window=10,
        cursor_mode="timestamp",
        run_once=True,
    )

    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(0.05)
    await monitor.stop()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    # cursor should be advanced to latest timestamp
    cursor = get_system_state(conn, "last_processed_cursor")
    assert cursor == "222"

    # no executor ran, so trade_history should be empty
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM trade_history")
    count = cur.fetchone()[0]
    assert count == 0
