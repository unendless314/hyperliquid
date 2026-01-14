import asyncio
import contextlib
import json

import pytest

from core.monitor import Monitor
from utils.db import init_sqlite


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
async def test_monitor_records_poison_and_continues():
    conn = init_sqlite(":memory:")
    q: asyncio.Queue = asyncio.Queue()
    class Unserializable:
        def __repr__(self):
            return "<unserializable>"

    ws = FakeWs(
        [
            {"type": "fill", "symbol": "BTC", "tx_hash": "ok", "event_index": 0, "timestamp": 1},
            {"type": "fill", "symbol": None, "tx_hash": None, "event_index": 1, "timestamp": 2, "obj": Unserializable()},
            {"type": "fill", "symbol": "ETH", "tx_hash": "ok2", "event_index": 2, "timestamp": 3},
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

    # Poison should be recorded
    cur = conn.cursor()
    cur.execute("SELECT reason, raw_event FROM poison_messages")
    rows = cur.fetchall()
    assert len(rows) == 1
    reason, raw = rows[0]
    assert reason == "missing_fields"
    assert json.loads(raw)["event_index"] == 1

    # Valid events still processed
    assert q.qsize() >= 2
