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


class _DummyAdapter:
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
                "warn_threshold": 0.1,
                "critical_threshold": 0.5,
                "snapshot_max_stale_ms": 10_000,
            }
        },
    )


def test_reconcile_missing_symbols_halts() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        settings = _build_settings(root)
        conn = init_db(settings.db_path)
        try:
            persistence = DbPersistence(conn)
            intent = OrderIntent(
                correlation_id="hl-reconcile-1",
                client_order_id="hl-reconcile-1-client",
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
                    exchange_order_id="1",
                    status="FILLED",
                    filled_qty=1.0,
                    avg_price=100.0,
                    error_code=None,
                    error_message=None,
                )
            )

            adapter = _DummyAdapter({}, int(time.time() * 1000))
            safety = SafetyService(safety_mode_provider=lambda: "ARMED_LIVE")
            execution = ExecutionService(adapter=adapter)
            services = {"safety": safety, "execution": execution}

            orchestrator = Orchestrator(settings=settings, mode="dry-run")
            logger = logging.getLogger("test.reconcile")
            metrics = _DummyMetrics()

            orchestrator._run_reconcile(
                services,
                conn,
                logger,
                metrics,
                allow_auto_promote=False,
                context="startup",
            )

            assert get_system_state(conn, "safety_mode") == "HALT"
            assert get_system_state(conn, "safety_reason_code") == "RECONCILE_CRITICAL"
        finally:
            conn.close()
