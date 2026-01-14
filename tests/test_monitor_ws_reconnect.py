import asyncio
import contextlib

import pytest

from core.monitor import Monitor
from utils.db import init_sqlite, get_system_state


class CrashOnceWs:
    def __init__(self, events, crash_after=1):
        self.events = events
        self.count = 0
        self.crash_after = crash_after

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.count == self.crash_after:
            self.count += 1
            raise RuntimeError("ws crash")
        if self.count >= len(self.events):
            raise StopAsyncIteration
        ev = self.events[self.count]
        self.count += 1
        return ev


@pytest.mark.asyncio
async def test_monitor_recreates_ws_on_failure():
    conn = init_sqlite(":memory:")
    q: asyncio.Queue = asyncio.Queue()

    ws1 = CrashOnceWs([{"tx_hash": "t1", "symbol": "BTC", "event_index": 0, "timestamp": 10}], crash_after=1)
    ws2 = CrashOnceWs([{"tx_hash": "t2", "symbol": "ETH", "event_index": 0, "timestamp": 20}], crash_after=2)

    factory_calls = []

    def ws_factory():
        factory_calls.append("call")
        return ws2

    monitor = Monitor(
        q,
        conn,
        settings={"cursor_mode": "timestamp"},
        ws_client=ws1,
        ws_factory=ws_factory,
        cursor_mode="timestamp",
        run_once=False,
        ws_retry_backoff_initial=0.01,
        ws_retry_backoff_max=0.05,
    )

    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(0.8)  # enough for crash -> reconnect with tiny backoff + queue put
    await monitor.stop()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    processed = []
    while not q.empty():
        processed.append(q.get_nowait())

    assert any(ev.get("tx_hash") == "t1" for ev in processed)
    # crash should trigger ws_factory at least once (reconnect path exercised)
    assert len(factory_calls) >= 1
