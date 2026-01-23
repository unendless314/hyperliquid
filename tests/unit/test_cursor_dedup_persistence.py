from hyperliquid.ingest.service import IngestService, RawPositionEvent
from hyperliquid.storage.db import get_system_state, has_processed_tx


def test_cursor_persists_newest_event(db_conn) -> None:
    ingest = IngestService()
    newer = RawPositionEvent(
        symbol="BTCUSDT",
        tx_hash="0xnewer",
        event_index=2,
        prev_target_net_position=1.0,
        next_target_net_position=2.0,
        timestamp_ms=2000,
    )
    older = RawPositionEvent(
        symbol="BTCUSDT",
        tx_hash="0xolder",
        event_index=1,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        timestamp_ms=1500,
    )
    events = ingest.ingest_raw_events([newer, older], db_conn)
    assert len(events) == 2
    assert get_system_state(db_conn, "last_processed_timestamp_ms") == "2000"
    assert (
        get_system_state(db_conn, "last_processed_event_key")
        == "2000|2|0xnewer|BTCUSDT"
    )


def test_dedup_persistence_blocks_replay(db_conn) -> None:
    ingest = IngestService()
    raw = RawPositionEvent(
        symbol="BTCUSDT",
        tx_hash="0xpersist",
        event_index=1,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        timestamp_ms=1700,
    )
    first = ingest.ingest_raw_events([raw], db_conn)
    assert len(first) == 1
    assert has_processed_tx(db_conn, raw.tx_hash, raw.event_index, raw.symbol) is True
    second = ingest.ingest_raw_events([raw], db_conn)
    assert second == []
