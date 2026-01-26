from __future__ import annotations

import time

from hyperliquid.common.models import OrderIntent, OrderResult
from hyperliquid.storage.baseline import insert_baseline
from hyperliquid.storage.persistence import DbPersistence
from hyperliquid.storage.positions import load_local_positions


def test_load_local_positions_includes_baseline(db_conn) -> None:
    persistence = DbPersistence(db_conn)
    insert_baseline(
        db_conn,
        positions={"BTCUSDT": 0.5},
        operator="tester",
        reason_message="baseline",
        replace=True,
    )

    intent = OrderIntent(
        correlation_id="hl-abc-12-BTCUSDT",
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
    persistence.ensure_intent(intent)
    result = OrderResult(
        correlation_id=intent.correlation_id,
        exchange_order_id="ex-3",
        status="FILLED",
        filled_qty=1.0,
        avg_price=100.0,
        error_code=None,
        error_message=None,
    )
    persistence.record_result(result)
    db_conn.execute(
        "UPDATE order_results SET created_at_ms = ? WHERE correlation_id = ?",
        (int(time.time() * 1000) + 1000, intent.correlation_id),
    )
    db_conn.commit()

    positions = load_local_positions(db_conn)
    assert positions["BTCUSDT"] == 1.5
