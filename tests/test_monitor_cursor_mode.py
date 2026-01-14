import asyncio

import pytest

from core.monitor import Monitor
from utils.db import init_sqlite, set_system_state, get_system_state


class FakeRestLatestOnly:
    def __init__(self, latest):
        self.latest = latest

    async def get_latest_cursor(self):
        return self.latest


class FakeRestEmptyRange(FakeRestLatestOnly):
    def __init__(self, latest):
        super().__init__(latest)
        self.calls = 0

    async def fetch_range(self, start_cursor: int, end_cursor: int):
        self.calls += 1
        return []


@pytest.mark.asyncio
async def test_cursor_unit_mismatch_halts():
    conn = init_sqlite(":memory:")
    # Persist a timestamp-like cursor (ms) while latest is small block height
    set_system_state(conn, "last_processed_cursor", str(1_700_000_000_000))
    queue: asyncio.Queue = asyncio.Queue()

    rest = FakeRestLatestOnly(latest=100)
    monitor = Monitor(
        queue,
        conn,
        settings={},
        rest_client=rest,
        ws_client=None,
        cursor_mode="block",
        backfill_window=10,
        run_once=True,
        cleanup_interval_seconds=0,
    )

    await monitor._maybe_gap_and_backfill()

    assert monitor._stopped.is_set()
    halt_msg = queue.get_nowait()
    assert halt_msg["type"] == "halt"
    assert halt_msg["reason"] == "cursor_unit_mismatch"


@pytest.mark.asyncio
async def test_backfill_advances_cursor_when_no_events_returned():
    conn = init_sqlite(":memory:")
    set_system_state(conn, "last_processed_cursor", "5")
    queue: asyncio.Queue = asyncio.Queue()

    rest = FakeRestEmptyRange(latest=7)
    monitor = Monitor(
        queue,
        conn,
        settings={},
        rest_client=rest,
        ws_client=None,
        cursor_mode="block",
        backfill_window=10,
        run_once=True,
        cleanup_interval_seconds=0,
    )

    await monitor._maybe_gap_and_backfill()

    # No events enqueued, but cursor should advance
    assert queue.qsize() == 0
    assert get_system_state(conn, "last_processed_cursor") == "7"
    assert rest.calls == 1


@pytest.mark.asyncio
async def test_latest_non_numeric_halts():
    conn = init_sqlite(":memory:")
    set_system_state(conn, "last_processed_cursor", "5")
    queue: asyncio.Queue = asyncio.Queue()

    class RestNonNumeric:
        async def get_latest_cursor(self):
            return "abc"

    monitor = Monitor(
        queue,
        conn,
        settings={},
        rest_client=RestNonNumeric(),
        ws_client=None,
        cursor_mode="block",
        backfill_window=10,
        run_once=True,
        cleanup_interval_seconds=0,
    )

    await monitor._maybe_gap_and_backfill()

    assert monitor._stopped.is_set()
    halt_msg = queue.get_nowait()
    assert halt_msg["reason"] == "cursor_unit_mismatch"
