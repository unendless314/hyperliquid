"""
SQLite helpers for schema setup and connection management.

This keeps SQLite-specific details (PRAGMA, table DDL, indexes) in one place so
the orchestrator can call `init_sqlite` during startup.
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Optional

DEFAULT_DB_PATH = "data/hyperliquid.db"
DEFAULT_DEDUP_TTL_SECONDS = 24 * 60 * 60  # 24h


def init_sqlite(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Open (and create if missing) the SQLite database, apply pragmatic defaults,
    and ensure required tables/indexes exist.
    """
    path = db_path or DEFAULT_DB_PATH
    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)

    conn = sqlite3.connect(path, timeout=5.0, isolation_level=None)  # autocommit
    _apply_pragmas(conn)
    _ensure_schema(conn)
    return conn


def cleanup_processed_txs(conn: sqlite3.Connection, ttl_seconds: int = DEFAULT_DEDUP_TTL_SECONDS) -> int:
    """
    Delete dedup cache entries older than `ttl_seconds`.

    Returns number of rows removed. Uses SQLite epoch seconds to match created_at default.
    """
    cutoff = int(time.time()) - int(ttl_seconds)
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM processed_txs WHERE created_at < ?", (cutoff,))
        return cur.rowcount
    finally:
        cur.close()


def set_system_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO system_state (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
    finally:
        cur.close()


def get_system_state(conn: sqlite3.Connection, key: str) -> Optional[str]:
    cur = conn.cursor()
    try:
        cur.execute("SELECT value FROM system_state WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        cur.close()


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA busy_timeout=5000;
        PRAGMA foreign_keys=ON;
        """
    )
    cur.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS processed_txs (
            tx_hash TEXT,
            event_index INTEGER,
            symbol TEXT,
            block_height INTEGER,
            timestamp INTEGER,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_processed_pk ON processed_txs(tx_hash, event_index);
        CREATE INDEX IF NOT EXISTS idx_processed_created_at ON processed_txs(created_at);

        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            correlation_id TEXT,
            symbol TEXT,
            side TEXT,
            size REAL,
            price REAL,
            pnl REAL,
            status TEXT,
            exchange_order_id TEXT,
            tx_hash TEXT,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_trade_corr ON trade_history(correlation_id);
        CREATE INDEX IF NOT EXISTS idx_trade_tx ON trade_history(tx_hash);

        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    cur.close()
