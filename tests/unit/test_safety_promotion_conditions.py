from __future__ import annotations

from hyperliquid.safety.service import SafetyService
from hyperliquid.safety.reconcile import PositionSnapshot
from hyperliquid.storage.safety import SafetyState


def _safety_mode_provider() -> str:
    return "ARMED_SAFE"


def _snapshots(now_ms: int):
    local = PositionSnapshot(
        source="local",
        positions={"BTCUSDT": 1.0},
        timestamp_ms=now_ms,
    )
    exchange = PositionSnapshot(
        source="exchange",
        positions={"BTCUSDT": 1.0},
        timestamp_ms=now_ms,
    )
    return local, exchange


def test_promote_to_armed_live_when_allowed(monkeypatch) -> None:
    service = SafetyService(safety_mode_provider=_safety_mode_provider)
    monkeypatch.setattr("hyperliquid.safety.reconcile.time.time", lambda: 10.0)
    local, exchange = _snapshots(10000)
    current = SafetyState(
        mode="ARMED_SAFE",
        reason_code="RECONCILE_WARN",
        reason_message="Drift exceeds warning threshold",
        changed_at_ms=9999,
    )
    result = service.reconcile_snapshots(
        local_snapshot=local,
        exchange_snapshot=exchange,
        warn_threshold=0.1,
        critical_threshold=1.0,
        snapshot_max_stale_ms=1000,
        current_state=current,
        allow_auto_promote=True,
    )
    assert result.mode == "ARMED_LIVE"
    assert result.reason_code == "OK"


def test_stays_armed_safe_when_auto_promote_disabled(monkeypatch) -> None:
    service = SafetyService(safety_mode_provider=_safety_mode_provider)
    monkeypatch.setattr("hyperliquid.safety.reconcile.time.time", lambda: 10.0)
    local, exchange = _snapshots(10000)
    current = SafetyState(
        mode="ARMED_SAFE",
        reason_code="RECONCILE_WARN",
        reason_message="Drift exceeds warning threshold",
        changed_at_ms=9999,
    )
    result = service.reconcile_snapshots(
        local_snapshot=local,
        exchange_snapshot=exchange,
        warn_threshold=0.1,
        critical_threshold=1.0,
        snapshot_max_stale_ms=1000,
        current_state=current,
        allow_auto_promote=False,
    )
    assert result.mode == "ARMED_SAFE"
    assert result.reason_code == "RECONCILE_WARN"
