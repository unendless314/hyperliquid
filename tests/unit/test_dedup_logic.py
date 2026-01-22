import sqlite3

from hyperliquid.ingest.service import IngestService, RawPositionEvent
from hyperliquid.storage.db import event_key, get_system_state


def _count_processed(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT count(*) FROM processed_txs").fetchone()
    assert row is not None
    return int(row[0])


def test_ingest_dedup_updates_cursor(db_conn) -> None:
    ingest = IngestService()

    raw = RawPositionEvent(
        symbol="BTCUSDT",
        tx_hash="0xdup",
        event_index=7,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        is_replay=0,
        timestamp_ms=1700000000123,
    )

    events = ingest.ingest_raw_events([raw, raw], db_conn)

    assert len(events) == 1
    assert _count_processed(db_conn) == 1
    assert get_system_state(db_conn, "last_processed_timestamp_ms") == str(
        raw.timestamp_ms
    )
    assert get_system_state(db_conn, "last_processed_event_key") == event_key(
        raw.timestamp_ms, raw.event_index, raw.tx_hash, raw.symbol
    )
