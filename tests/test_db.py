import sqlite3
import os

from utils.db import init_sqlite


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
