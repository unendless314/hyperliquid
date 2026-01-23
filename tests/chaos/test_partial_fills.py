from __future__ import annotations

from hyperliquid.common.models import OrderIntent, OrderResult
from hyperliquid.storage.persistence import DbPersistence
from hyperliquid.storage.positions import load_local_positions_from_orders


def test_partial_fill_uses_filled_qty_for_positions(db_conn) -> None:
    persistence = DbPersistence(db_conn)
    intent = OrderIntent(
        correlation_id="hl-chaos-partial-1-BTCUSDT",
        client_order_id="hl-chaos-partial-1-BTCUSDT-deadbeef",
        strategy_version="v1",
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
    persistence.record_result(
        OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id="ex-1",
            status="PARTIALLY_FILLED",
            filled_qty=0.4,
            avg_price=100.0,
            error_code=None,
            error_message=None,
        )
    )
    positions = load_local_positions_from_orders(db_conn)
    assert abs(positions.get("BTCUSDT", 0.0) - 0.4) < 1e-9
