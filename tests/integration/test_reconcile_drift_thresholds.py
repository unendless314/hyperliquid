from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

from hyperliquid.common.models import OrderIntent, OrderResult
from hyperliquid.common.settings import Settings
from hyperliquid.execution.service import ExecutionService
from hyperliquid.orchestrator.service import Orchestrator
from hyperliquid.safety.service import SafetyService
from hyperliquid.storage.db import get_system_state, init_db
from hyperliquid.storage.persistence import DbPersistence


class _DummyMetrics:
    def emit(self, name: str, value: float, tags=None) -> None:
        _ = (name, value, tags)


class _PositionAdapter:
    def __init__(self, positions: dict[str, float], timestamp_ms: int) -> None:
        self._positions = positions
        self._timestamp_ms = timestamp_ms

    def fetch_positions(self) -> tuple[dict[str, float], int]:
        return self._positions, self._timestamp_ms


def _build_settings(root: Path) -> Settings:
    return Settings(
        config_version="test",
        environment="test",
        db_path=str(root / "test.db"),
        metrics_log_path=str(root / "metrics.log"),
        app_log_path=str(root / "app.log"),
        log_level="INFO",
        config_path=root / "settings.yaml",
        raw={
            "safety": {
                "warn_threshold": 0.2,
                "critical_threshold": 0.5,
                "snapshot_max_stale_ms": 10_000,
            }
        },
    )


def _seed_local_position(conn, *, qty: float) -> None:
    persistence = DbPersistence(conn)
    intent = OrderIntent(
        correlation_id="hl-local-1-BTCUSDT",
        client_order_id="hl-local-1-BTCUSDT-deadbeef",
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        qty=qty,
        price=None,
        reduce_only=0,
        time_in_force="IOC",
        is_replay=0,
    )
    persistence.record_intent(intent)
    persistence.record_result(
        OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id="ex-1",
            status="FILLED",
            filled_qty=qty,
            avg_price=100.0,
            error_code=None,
            error_message=None,
        )
    )


def _run_reconcile(conn, settings: Settings, *, exchange_positions: dict[str, float]) -> None:
    adapter = _PositionAdapter(exchange_positions, int(time.time() * 1000))
    safety = SafetyService(safety_mode_provider=lambda: "ARMED_LIVE")
    execution = ExecutionService(adapter=adapter)
    services = {"safety": safety, "execution": execution}
    orchestrator = Orchestrator(settings=settings, mode="dry-run")
    logger = logging.getLogger("test.drift_thresholds")
    metrics = _DummyMetrics()
    orchestrator._run_reconcile(
        services,
        conn,
        logger,
        metrics,
        allow_auto_promote=False,
        context="startup",
    )


def test_reconcile_drift_warn_sets_armed_safe() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        settings = _build_settings(root)
        conn = init_db(settings.db_path)
        try:
            _seed_local_position(conn, qty=1.0)
            _run_reconcile(conn, settings, exchange_positions={"BTCUSDT": 0.7})

            assert get_system_state(conn, "safety_mode") == "ARMED_SAFE"
            assert get_system_state(conn, "safety_reason_code") == "RECONCILE_WARN"
        finally:
            conn.close()


def test_reconcile_drift_critical_sets_halt() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        settings = _build_settings(root)
        conn = init_db(settings.db_path)
        try:
            _seed_local_position(conn, qty=1.0)
            _run_reconcile(conn, settings, exchange_positions={"BTCUSDT": 0.4})

            assert get_system_state(conn, "safety_mode") == "HALT"
            assert get_system_state(conn, "safety_reason_code") == "RECONCILE_CRITICAL"
        finally:
            conn.close()
