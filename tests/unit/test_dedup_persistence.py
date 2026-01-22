from hyperliquid.ingest.service import IngestService, RawPositionEvent
from hyperliquid.storage.db import event_key, get_system_state


def test_ingest_persists_replay_flag_and_cursor(db_conn) -> None:
    ingest = IngestService()

    raw = RawPositionEvent(
        symbol="ETHUSDT",
        tx_hash="0xreplay",
        event_index=3,
        prev_target_net_position=0.0,
        next_target_net_position=2.0,
        is_replay=1,
        timestamp_ms=1700000002000,
    )

    events = ingest.ingest_raw_events([raw], db_conn)

    assert len(events) == 1
    row = db_conn.execute(
        "SELECT is_replay FROM processed_txs WHERE tx_hash = ? AND event_index = ? AND symbol = ?",
        (raw.tx_hash, raw.event_index, raw.symbol),
    ).fetchone()
    assert row is not None
    assert int(row[0]) == 1
    assert get_system_state(db_conn, "last_processed_event_key") == event_key(
        raw.timestamp_ms, raw.event_index, raw.tx_hash, raw.symbol
    )
