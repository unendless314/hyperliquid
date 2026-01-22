import pytest

from hyperliquid.storage.db import init_db


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "test.db")


@pytest.fixture
def db_conn(db_path):
    conn = init_db(db_path)
    try:
        yield conn
    finally:
        conn.close()
