from hyperliquid.ingest.coordinator import IngestCoordinator, IngestRuntimeConfig
from hyperliquid.ingest.service import IngestService, RawPositionEvent
from hyperliquid.storage.db import event_key, get_system_state, set_system_state


class _FakeAdapter:
    def __init__(self, *, backfill_events, live_events):
        self.backfill_events = list(backfill_events)
        self.live_events = list(live_events)
        self.backfill_since_ms = None
        self.backfill_until_ms = None
        self.live_since_ms = None

    def fetch_backfill(self, *, since_ms: int, until_ms: int):
        self.backfill_since_ms = since_ms
        self.backfill_until_ms = until_ms
        return list(self.backfill_events)

    def poll_live_events(self, *, since_ms: int):
        self.live_since_ms = since_ms
        return list(self.live_events)


def test_ws_reconnect_backfill_overlap_dedup(db_conn, monkeypatch) -> None:
    ingest = IngestService()
    runtime = IngestRuntimeConfig(
        backfill_window_ms=600000,
        cursor_overlap_ms=200,
        maintenance_skip_gap=False,
    )

    duplicate = RawPositionEvent(
        symbol="BTCUSDT",
        tx_hash="0xdup",
        event_index=1,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        is_replay=0,
        timestamp_ms=1700000001000,
    )
    live_only = RawPositionEvent(
        symbol="BTCUSDT",
        tx_hash="0xnew",
        event_index=2,
        prev_target_net_position=1.0,
        next_target_net_position=2.0,
        is_replay=0,
        timestamp_ms=1700000001100,
    )
    adapter = _FakeAdapter(
        backfill_events=[duplicate],
        live_events=[duplicate, live_only],
    )
    coordinator = IngestCoordinator(
        ingest_service=ingest,
        adapter=adapter,
        runtime=runtime,
    )

    monkeypatch.setattr(
        "hyperliquid.ingest.coordinator.time.time", lambda: 1700000001200 / 1000.0
    )
    set_system_state(db_conn, "last_processed_timestamp_ms", "1700000000500")

    events = coordinator.run_once(db_conn, mode="live")

    assert adapter.backfill_since_ms == 1700000000500 - runtime.cursor_overlap_ms
    assert adapter.backfill_until_ms == 1700000001200
    assert adapter.live_since_ms == duplicate.timestamp_ms
    assert len(events) == 2
    assert [event.tx_hash for event in events].count("0xdup") == 1
    assert [event.tx_hash for event in events].count("0xnew") == 1
    assert get_system_state(db_conn, "last_processed_event_key") == event_key(
        live_only.timestamp_ms, live_only.event_index, live_only.tx_hash, live_only.symbol
    )
    row = db_conn.execute(
        "SELECT is_replay FROM processed_txs WHERE tx_hash = ? AND event_index = ? AND symbol = ?",
        (duplicate.tx_hash, duplicate.event_index, duplicate.symbol),
    ).fetchone()
    assert row is not None
    assert int(row[0]) == 1
