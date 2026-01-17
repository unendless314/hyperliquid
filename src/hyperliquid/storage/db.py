from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

DB_SCHEMA_VERSION = "1"


def _now_ms() -> int:
    return int(time.time() * 1000)


def init_db(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON;")
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS processed_txs (
            tx_hash TEXT NOT NULL,
            event_index INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            timestamp_ms INTEGER NOT NULL,
            is_replay INTEGER NOT NULL DEFAULT 0,
            created_at_ms INTEGER NOT NULL,
            PRIMARY KEY (tx_hash, event_index, symbol)
        );

        CREATE INDEX IF NOT EXISTS idx_processed_txs_created_at_ms
            ON processed_txs(created_at_ms);
        CREATE INDEX IF NOT EXISTS idx_processed_txs_timestamp_ms
            ON processed_txs(timestamp_ms);

        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            correlation_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            size REAL NOT NULL,
            price REAL NOT NULL,
            pnl REAL,
            status TEXT NOT NULL,
            exchange_order_id TEXT,
            tx_hash TEXT,
            created_at_ms INTEGER NOT NULL,
            UNIQUE (correlation_id)
        );

        CREATE INDEX IF NOT EXISTS idx_trade_history_correlation_id
            ON trade_history(correlation_id);
        CREATE INDEX IF NOT EXISTS idx_trade_history_tx_hash
            ON trade_history(tx_hash);
        CREATE INDEX IF NOT EXISTS idx_trade_history_exchange_order_id
            ON trade_history(exchange_order_id);

        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_intents (
            correlation_id TEXT PRIMARY KEY,
            intent_payload TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_results (
            correlation_id TEXT PRIMARY KEY,
            exchange_order_id TEXT,
            status TEXT NOT NULL,
            filled_qty REAL NOT NULL,
            avg_price REAL,
            error_code TEXT,
            error_message TEXT,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_order_results_status
            ON order_results(status);
        CREATE INDEX IF NOT EXISTS idx_order_results_exchange_order_id
            ON order_results(exchange_order_id);
        """
    )
    conn.commit()


def ensure_schema_version(conn: sqlite3.Connection) -> str:
    existing = get_system_state(conn, "schema_version")
    if existing is None:
        set_system_state(conn, "schema_version", DB_SCHEMA_VERSION)
        conn.commit()
        return DB_SCHEMA_VERSION
    return existing


def assert_schema_version(conn: sqlite3.Connection) -> None:
    existing = ensure_schema_version(conn)
    if existing != DB_SCHEMA_VERSION:
        raise RuntimeError("SCHEMA_VERSION_MISMATCH")


def _set_system_state_if_missing(conn: sqlite3.Connection, key: str, value: str) -> None:
    existing = get_system_state(conn, key)
    if existing is None:
        set_system_state(conn, key, value)


def get_system_state(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute(
        "SELECT value FROM system_state WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    return str(row[0])


def set_system_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO system_state(key, value, updated_at_ms) "
        "VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at_ms=excluded.updated_at_ms",
        (key, value, _now_ms()),
    )
    conn.commit()
