from __future__ import annotations

import time

from hyperliquid.safety.reconcile import PositionSnapshot, reconcile_snapshots


def test_delayed_exchange_snapshot_marks_stale() -> None:
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
