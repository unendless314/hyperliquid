import asyncio

import pytest

from core.monitor import Monitor
from utils.db import init_sqlite


@pytest.mark.asyncio
async def test_monitor_dedup_inserts_once_and_updates_cursor():
    conn = init_sqlite(":memory:")
    queue: asyncio.Queue = asyncio.Queue()
    monitor = Monitor(queue, conn, settings={}, ws_client=None, rest_client=None, run_once=True)

    event = {
        "tx_hash": "abc",
        "event_index": 0,
        "symbol": "BTC",
        "block_height": 10,
        "timestamp": 1,
    }
    await monitor._handle_raw_event(event)
    await monitor._handle_raw_event(event)  # duplicate

    # Another event with same tx_hash but different event_index should pass
    event2 = dict(event, event_index=1)
    await monitor._handle_raw_event(event2)

    # queue should have two fills (index 0 and 1)
    assert queue.qsize() == 2
    msg1 = queue.get_nowait()
    msg2 = queue.get_nowait()
    indexes = sorted([msg1["event_index"], msg2["event_index"]])
    assert indexes == [0, 1]

    # cursor updated
    cur = conn.cursor()
    cur.execute("SELECT value FROM system_state WHERE key='last_processed_cursor'")
    val = cur.fetchone()[0]
    assert val == "10"
