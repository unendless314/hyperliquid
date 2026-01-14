import sqlite3
import os
import time

from utils.db import init_sqlite, cleanup_processed_txs


def test_init_sqlite_creates_default_schema(tmp_path):
    db_path = tmp_path / "hl.db"
    conn = init_sqlite(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        assert {"processed_txs", "trade_history", "system_state"} <= tables
    finally:
        conn.close()


def test_init_sqlite_accepts_flat_filename(tmp_path):
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        conn = init_sqlite("flat.db")
        try:
            assert isinstance(conn, sqlite3.Connection)
        finally:
            conn.close()
    finally:
        os.chdir(cwd)


def test_init_sqlite_allows_memory_db():
    conn = init_sqlite(":memory:")
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        assert {"processed_txs", "trade_history", "system_state"} <= tables
    finally:
        conn.close()


def test_cleanup_processed_txs_removes_expired():
    conn = init_sqlite(":memory:")
    cur = conn.cursor()
    now = int(time.time())
    cur.execute(
        "INSERT INTO processed_txs (tx_hash, event_index, symbol, block_height, timestamp, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("old", 0, "BTC", 1, 1, now - 1000),
    )
    cur.execute(
        "INSERT INTO processed_txs (tx_hash, event_index, symbol, block_height, timestamp, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("new", 1, "BTC", 2, 2, now),
    )
    conn.commit()

    removed = cleanup_processed_txs(conn, ttl_seconds=500)
    assert removed == 1

    cur.execute("SELECT tx_hash FROM processed_txs")
    rows = {row[0] for row in cur.fetchall()}
    assert rows == {"new"}
    conn.close()
