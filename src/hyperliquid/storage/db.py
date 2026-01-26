from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

DB_SCHEMA_VERSION = "4"


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
            contract_version TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_order_results_status
            ON order_results(status);
        CREATE INDEX IF NOT EXISTS idx_order_results_exchange_order_id
            ON order_results(exchange_order_id);

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_ms INTEGER NOT NULL,
            category TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT,
            reason_code TEXT,
            reason_message TEXT,
            event_id TEXT,
            metadata TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_audit_log_category
            ON audit_log(category);
        CREATE INDEX IF NOT EXISTS idx_audit_log_entity_id
            ON audit_log(entity_id);
        CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp_ms
            ON audit_log(timestamp_ms);

        CREATE TABLE IF NOT EXISTS baseline_snapshots (
            baseline_id TEXT PRIMARY KEY,
            created_at_ms INTEGER NOT NULL,
            operator TEXT,
            reason_message TEXT,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS baseline_positions (
            baseline_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            qty REAL NOT NULL,
            PRIMARY KEY (baseline_id, symbol)
        );

        CREATE INDEX IF NOT EXISTS idx_baseline_snapshots_active
            ON baseline_snapshots(active, created_at_ms);
        CREATE INDEX IF NOT EXISTS idx_baseline_positions_baseline_id
            ON baseline_positions(baseline_id);
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


def set_system_state(
    conn: sqlite3.Connection, key: str, value: str, *, commit: bool = True
) -> None:
    conn.execute(
        "INSERT INTO system_state(key, value, updated_at_ms) "
        "VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at_ms=excluded.updated_at_ms",
        (key, value, _now_ms()),
    )
    if commit:
        conn.commit()


def event_key(timestamp_ms: int, event_index: int, tx_hash: str, symbol: str) -> str:
    return f"{timestamp_ms}|{event_index}|{tx_hash}|{symbol}"


def has_processed_tx(
    conn: sqlite3.Connection, tx_hash: str, event_index: int, symbol: str
) -> bool:
    row = conn.execute(
        "SELECT 1 FROM processed_txs WHERE tx_hash = ? AND event_index = ? AND symbol = ?",
        (tx_hash, event_index, symbol),
    ).fetchone()
    return row is not None


def record_processed_tx(
    conn: sqlite3.Connection,
    *,
    tx_hash: str,
    event_index: int,
    symbol: str,
    timestamp_ms: int,
    is_replay: int,
    commit: bool = True,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO processed_txs("
        "tx_hash, event_index, symbol, timestamp_ms, is_replay, created_at_ms"
        ") VALUES(?, ?, ?, ?, ?, ?)",
        (tx_hash, event_index, symbol, timestamp_ms, is_replay, _now_ms()),
    )
    if commit:
        conn.commit()


def cleanup_processed_txs(conn: sqlite3.Connection, *, dedup_ttl_seconds: int) -> int:
    if dedup_ttl_seconds < 0:
        raise ValueError("dedup_ttl_seconds must be >= 0")
    threshold_ms = _now_ms() - int(dedup_ttl_seconds) * 1000
    cursor = conn.execute(
        "DELETE FROM processed_txs WHERE created_at_ms < ?",
        (threshold_ms,),
    )
    conn.commit()
    return cursor.rowcount

def update_cursor(
    conn: sqlite3.Connection,
    *,
    timestamp_ms: int,
    event_index: int,
    tx_hash: str,
    symbol: str,
    commit: bool = True,
) -> None:
    set_system_state(
        conn, "last_processed_timestamp_ms", str(timestamp_ms), commit=False
    )
    set_system_state(
        conn,
        "last_processed_event_key",
        event_key(timestamp_ms, event_index, tx_hash, symbol),
        commit=False,
    )
    if commit:
        conn.commit()


def should_advance_cursor(
    current_key: Optional[str],
    *,
    timestamp_ms: int,
    event_index: int,
    tx_hash: str,
    symbol: str,
) -> bool:
    if not current_key:
        return True
    current_parts = current_key.split("|", 3)
    if len(current_parts) != 4:
        return True
    current_ts = int(current_parts[0])
    current_index = int(current_parts[1])
    current_tx = current_parts[2]
    current_symbol = current_parts[3]
    current_tuple = (current_ts, current_index, current_tx, current_symbol)
    next_tuple = (timestamp_ms, event_index, tx_hash, symbol)
    return next_tuple > current_tuple


def advance_cursor_if_newer(
    conn: sqlite3.Connection,
    *,
    timestamp_ms: int,
    event_index: int,
    tx_hash: str,
    symbol: str,
    commit: bool = True,
) -> bool:
    current_key = get_system_state(conn, "last_processed_event_key")
    if should_advance_cursor(
        current_key,
        timestamp_ms=timestamp_ms,
        event_index=event_index,
        tx_hash=tx_hash,
        symbol=symbol,
    ):
        update_cursor(
            conn,
            timestamp_ms=timestamp_ms,
            event_index=event_index,
            tx_hash=tx_hash,
            symbol=symbol,
            commit=commit,
        )
        return True
    return False
