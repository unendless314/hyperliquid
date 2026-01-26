from __future__ import annotations

import time

from hyperliquid.common.models import OrderIntent, OrderResult
from hyperliquid.safety.reconcile import PositionSnapshot, reconcile_snapshots
from hyperliquid.safety.service import SafetyService
from hyperliquid.storage.persistence import DbPersistence
from hyperliquid.storage.positions import load_local_positions_from_orders
from hyperliquid.storage.safety import SafetyState


def test_load_local_positions_from_orders(db_conn) -> None:
    persistence = DbPersistence(db_conn)

    intent = OrderIntent(
        correlation_id="hl-abc-10-BTCUSDT",
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
        exchange_order_id="ex-1",
        status="FILLED",
        filled_qty=1.0,
        avg_price=100.0,
        error_code=None,
        error_message=None,
    )
    persistence.record_result(result)

    positions = load_local_positions_from_orders(db_conn)
    assert positions["BTCUSDT"] == 1.0


def test_load_local_positions_from_orders_since_ms(db_conn) -> None:
    persistence = DbPersistence(db_conn)

    intent = OrderIntent(
        correlation_id="hl-abc-11-BTCUSDT",
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
        exchange_order_id="ex-2",
        status="FILLED",
        filled_qty=1.0,
        avg_price=100.0,
        error_code=None,
        error_message=None,
    )
    persistence.record_result(result)
    db_conn.execute(
        "UPDATE order_results SET created_at_ms = ? WHERE correlation_id = ?",
        (int(time.time() * 1000) - 10000, intent.correlation_id),
    )
    db_conn.commit()

    positions = load_local_positions_from_orders(
        db_conn, since_ms=int(time.time() * 1000)
    )
    assert positions == {}


def test_reconcile_snapshot_stale() -> None:
    now_ms = int(time.time() * 1000)
    local = PositionSnapshot(source="db", positions={"BTCUSDT": 1.0}, timestamp_ms=now_ms)
    exchange = PositionSnapshot(
        source="exchange", positions={"BTCUSDT": 1.0}, timestamp_ms=now_ms - 60000
    )
    result = reconcile_snapshots(
        local_snapshot=local,
        exchange_snapshot=exchange,
        warn_threshold=0.1,
        critical_threshold=0.5,
        snapshot_max_stale_ms=30000,
        now_ms=now_ms,
    )
    assert result.mode == "ARMED_SAFE"
    assert result.reason_code == "SNAPSHOT_STALE"


def test_reconcile_missing_symbol_is_critical() -> None:
    now_ms = int(time.time() * 1000)
    local = PositionSnapshot(source="db", positions={"BTCUSDT": 1.0}, timestamp_ms=now_ms)
    exchange = PositionSnapshot(source="exchange", positions={}, timestamp_ms=now_ms)
    result = reconcile_snapshots(
        local_snapshot=local,
        exchange_snapshot=exchange,
        warn_threshold=0.1,
        critical_threshold=0.5,
        snapshot_max_stale_ms=30000,
        now_ms=now_ms,
    )
    assert result.mode == "HALT"
    assert result.reason_code == "RECONCILE_CRITICAL"


def test_reconcile_ignores_zero_positions() -> None:
    now_ms = int(time.time() * 1000)
    local = PositionSnapshot(source="db", positions={}, timestamp_ms=now_ms)
    exchange = PositionSnapshot(
        source="exchange",
        positions={"BTCUSDT": 0.0, "ETHUSDT": 0.0},
        timestamp_ms=now_ms,
    )
    result = reconcile_snapshots(
        local_snapshot=local,
        exchange_snapshot=exchange,
        warn_threshold=0.1,
        critical_threshold=0.5,
        snapshot_max_stale_ms=30000,
        now_ms=now_ms,
    )
    assert result.mode == "ARMED_LIVE"
    assert result.reason_code == "OK"


def test_reconcile_thresholds() -> None:
    now_ms = int(time.time() * 1000)
    local = PositionSnapshot(source="db", positions={"BTCUSDT": 1.0}, timestamp_ms=now_ms)
    exchange = PositionSnapshot(
        source="exchange", positions={"BTCUSDT": 1.2}, timestamp_ms=now_ms
    )
    warn = reconcile_snapshots(
        local_snapshot=local,
        exchange_snapshot=exchange,
        warn_threshold=0.1,
        critical_threshold=0.5,
        snapshot_max_stale_ms=30000,
        now_ms=now_ms,
    )
    assert warn.mode == "ARMED_SAFE"
    assert warn.reason_code == "RECONCILE_WARN"

    critical = reconcile_snapshots(
        local_snapshot=local,
        exchange_snapshot=exchange,
        warn_threshold=0.1,
        critical_threshold=0.15,
        snapshot_max_stale_ms=30000,
        now_ms=now_ms,
    )
    assert critical.mode == "HALT"
    assert critical.reason_code == "RECONCILE_CRITICAL"


def test_reconcile_policy_no_auto_promote() -> None:
    now_ms = int(time.time() * 1000)
    local = PositionSnapshot(source="db", positions={"BTCUSDT": 1.0}, timestamp_ms=now_ms)
    exchange = PositionSnapshot(
        source="exchange", positions={"BTCUSDT": 1.0}, timestamp_ms=now_ms
    )
    safety = SafetyService(safety_mode_provider=lambda: "ARMED_SAFE")
    current_state = SafetyState(
        mode="ARMED_SAFE",
        reason_code="RECONCILE_WARN",
        reason_message="Drift exceeds warning threshold",
        changed_at_ms=now_ms,
    )
    result = safety.reconcile_snapshots(
        local_snapshot=local,
        exchange_snapshot=exchange,
        warn_threshold=0.1,
        critical_threshold=0.5,
        snapshot_max_stale_ms=30000,
        current_state=current_state,
        allow_auto_promote=False,
    )
    assert result.mode == "ARMED_SAFE"
    assert result.reason_code == "RECONCILE_WARN"
