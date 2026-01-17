import sqlite3
import time

from hyperliquid.storage.db import cleanup_processed_txs, record_processed_tx


def test_cleanup_processed_txs_removes_old_rows() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE processed_txs ("
        "tx_hash TEXT NOT NULL,"
        "event_index INTEGER NOT NULL,"
        "symbol TEXT NOT NULL,"
        "timestamp_ms INTEGER NOT NULL,"
        "is_replay INTEGER NOT NULL DEFAULT 0,"
        "created_at_ms INTEGER NOT NULL,"
        "PRIMARY KEY (tx_hash, event_index, symbol)"
        ")"
    )

    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO processed_txs(tx_hash, event_index, symbol, timestamp_ms, is_replay, created_at_ms) "
        "VALUES(?, ?, ?, ?, ?, ?)",
        ("old", 1, "BTCUSDT", now_ms - 10_000, 0, now_ms - 10_000),
    )
    record_processed_tx(
        conn,
        tx_hash="new",
        event_index=2,
        symbol="BTCUSDT",
        timestamp_ms=now_ms,
        is_replay=0,
    )

    removed = cleanup_processed_txs(conn, dedup_ttl_seconds=5)
    remaining = conn.execute("SELECT count(*) FROM processed_txs").fetchone()[0]

    assert removed == 1
    assert remaining == 1
