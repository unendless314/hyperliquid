from hyperliquid.ingest.service import IngestService, RawPositionEvent


def test_dedup_drops_duplicate_events(db_conn) -> None:
    ingest = IngestService()
    raw = RawPositionEvent(
        symbol="BTCUSDT",
        tx_hash="0xdup",
        event_index=1,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        is_replay=0,
        timestamp_ms=1700000000000,
    )
    events = ingest.ingest_raw_events([raw, raw], db_conn)
    assert len(events) == 1
    assert events[0].tx_hash == "0xdup"


def test_dedup_backfill_overlap_drops_processed_events(db_conn) -> None:
    ingest = IngestService()
    first = RawPositionEvent(
        symbol="BTCUSDT",
        tx_hash="0xoverlap",
        event_index=1,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        is_replay=0,
        timestamp_ms=1700000000000,
    )
    overlap = RawPositionEvent(
        symbol="BTCUSDT",
        tx_hash="0xoverlap",
        event_index=1,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        is_replay=1,
        timestamp_ms=1700000000000,
    )
    events = ingest.ingest_raw_events([first], db_conn)
    assert len(events) == 1
    backfill_events = ingest.ingest_raw_events([overlap], db_conn)
    assert backfill_events == []
