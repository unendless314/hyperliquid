import sqlite3
import tempfile
import time

from hyperliquid.common.models import OrderIntent, OrderResult
from hyperliquid.storage.db import init_db
from hyperliquid.storage.persistence import DbPersistence


def _fetch_one(conn: sqlite3.Connection, query: str, params: tuple) -> tuple:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row


def test_db_persistence_intent_is_immutable() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        conn = init_db(tmp.name)
        persistence = DbPersistence(conn)

        intent = OrderIntent(
            correlation_id="hl-abc-1-BTCUSDT",
            client_order_id=None,
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            qty=1.0,
            price=None,
            reduce_only=0,
            time_in_force="IOC",
            is_replay=0,
            risk_notes=None,
        )

        persistence.record_intent(intent)
        created_at_first = _fetch_one(
            conn,
            "SELECT created_at_ms FROM order_intents WHERE correlation_id = ?",
            (intent.correlation_id,),
        )[0]

        time.sleep(0.01)
        persistence.record_intent(intent)
        created_at_second = _fetch_one(
            conn,
            "SELECT created_at_ms FROM order_intents WHERE correlation_id = ?",
            (intent.correlation_id,),
        )[0]

        assert created_at_first == created_at_second


def test_db_persistence_result_updates() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        conn = init_db(tmp.name)
        persistence = DbPersistence(conn)

        result_submitted = OrderResult(
            correlation_id="hl-abc-2-BTCUSDT",
            exchange_order_id="ex-1",
            status="SUBMITTED",
            filled_qty=0.0,
            avg_price=None,
            error_code=None,
            error_message=None,
        )
        persistence.record_result(result_submitted)

        created_first, updated_first, status_first = _fetch_one(
            conn,
            "SELECT created_at_ms, updated_at_ms, status FROM order_results WHERE correlation_id = ?",
            (result_submitted.correlation_id,),
        )

        time.sleep(0.01)
        result_filled = OrderResult(
            correlation_id="hl-abc-2-BTCUSDT",
            exchange_order_id="ex-1",
            status="FILLED",
            filled_qty=1.0,
            avg_price=100.0,
            error_code=None,
            error_message=None,
        )
        persistence.record_result(result_filled)

        created_second, updated_second, status_second = _fetch_one(
            conn,
            "SELECT created_at_ms, updated_at_ms, status FROM order_results WHERE correlation_id = ?",
            (result_submitted.correlation_id,),
        )

        assert created_first == created_second
        assert updated_second >= updated_first
        assert status_first == "SUBMITTED"
        assert status_second == "FILLED"


def test_db_persistence_ensure_intent_reuses_client_order_id() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        conn = init_db(tmp.name)
        persistence = DbPersistence(conn)

        intent = OrderIntent(
            correlation_id="hl-abc-3-BTCUSDT",
            client_order_id=None,
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            qty=1.0,
            price=None,
            reduce_only=0,
            time_in_force="IOC",
            is_replay=0,
            risk_notes=None,
        )

        first = persistence.ensure_intent(intent)
        assert first.client_order_id is not None

        second_intent = OrderIntent(
            correlation_id="hl-abc-3-BTCUSDT",
            client_order_id=None,
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            qty=1.0,
            price=None,
            reduce_only=0,
            time_in_force="IOC",
            is_replay=0,
            risk_notes=None,
        )
        second = persistence.ensure_intent(second_intent)
        assert second.client_order_id == first.client_order_id


def test_db_persistence_backfills_missing_client_order_id() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        conn = init_db(tmp.name)
        persistence = DbPersistence(conn)

        intent = OrderIntent(
            correlation_id="hl-abc-4-BTCUSDT",
            client_order_id=None,
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            qty=1.0,
            price=None,
            reduce_only=0,
            time_in_force="IOC",
            is_replay=0,
            risk_notes=None,
        )
        persistence.record_intent(intent)

        updated = persistence.ensure_intent(intent)
        assert updated.client_order_id is not None

        loaded = persistence.get_intent(intent.correlation_id)
        assert loaded is not None
        assert loaded.client_order_id == updated.client_order_id


def test_db_persistence_ensure_intent_mismatch_raises() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        conn = init_db(tmp.name)
        persistence = DbPersistence(conn)

        original = OrderIntent(
            correlation_id="hl-abc-5-BTCUSDT",
            client_order_id=None,
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            qty=1.0,
            price=None,
            reduce_only=0,
            time_in_force="IOC",
            is_replay=0,
            risk_notes=None,
        )
        persistence.ensure_intent(original)

        modified = OrderIntent(
            correlation_id="hl-abc-5-BTCUSDT",
            client_order_id=None,
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            qty=2.0,
            price=None,
            reduce_only=0,
            time_in_force="IOC",
            is_replay=0,
            risk_notes=None,
        )

        try:
            persistence.ensure_intent(modified)
        except ValueError as exc:
            assert "Intent payload mismatch" in str(exc)
        else:
            raise AssertionError("Expected mismatch to raise ValueError")
