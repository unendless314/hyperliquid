import asyncio

import pytest

from core.monitor import Monitor
from utils.db import init_sqlite, set_system_state, get_system_state


class FakeRest:
    def __init__(self, events):
        self.events = events

    async def get_latest_cursor(self):
        # Use block_height if present, else timestamp as cursor surrogate
        return max(ev.get("block_height") or ev.get("timestamp") for ev in self.events)

    async def fetch_range(self, start_cursor: int, end_cursor: int):
        return [
            ev
            for ev in self.events
            if start_cursor <= (ev.get("block_height") or ev.get("timestamp")) <= end_cursor
        ]


@pytest.mark.asyncio
async def test_monitor_backfill_within_window_enqueues_events_and_updates_cursor():
    conn = init_sqlite(":memory:")
    set_system_state(conn, "last_processed_cursor", "5")
    queue: asyncio.Queue = asyncio.Queue()

    events = [
        {"tx_hash": "a", "event_index": 0, "symbol": "BTC", "block_height": 6, "timestamp": 1000},
        {"tx_hash": "b", "event_index": 0, "symbol": "BTC", "block_height": 7, "timestamp": 2000},
    ]
    rest = FakeRest(events)

    monitor = Monitor(
        queue,
        conn,
        settings={},
        ws_client=None,
        rest_client=rest,
        backfill_window=5,
        run_once=True,
        cleanup_interval_seconds=0,
    )

    await monitor._maybe_gap_and_backfill()

    assert queue.qsize() == 2
    hashes = {queue.get_nowait()["tx_hash"] for _ in range(2)}
    assert hashes == {"a", "b"}
    assert get_system_state(conn, "last_processed_cursor") == "7"


@pytest.mark.asyncio
async def test_monitor_halts_when_gap_exceeds_window():
    conn = init_sqlite(":memory:")
    set_system_state(conn, "last_processed_cursor", "1")
    queue: asyncio.Queue = asyncio.Queue()

    events = [
        {"tx_hash": "c", "event_index": 0, "symbol": "BTC", "block_height": 50, "timestamp": 5000},
    ]
    rest = FakeRest(events)

    monitor = Monitor(
        queue,
        conn,
        settings={},
        ws_client=None,
        rest_client=rest,
        backfill_window=3,
        run_once=True,
        cleanup_interval_seconds=0,
    )

    await monitor._maybe_gap_and_backfill()

    assert monitor._stopped.is_set()
    halt_msg = queue.get_nowait()
    assert halt_msg["type"] == "halt"
    assert halt_msg["reason"] == "gap_exceeds_window"
