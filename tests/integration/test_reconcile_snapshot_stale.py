from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

from hyperliquid.common.settings import Settings
from hyperliquid.execution.service import ExecutionService
from hyperliquid.orchestrator.service import Orchestrator
from hyperliquid.safety.service import SafetyService
from hyperliquid.storage.db import get_system_state, init_db


class _DummyMetrics:
    def emit(self, name: str, value: float, tags=None) -> None:
        _ = (name, value, tags)


class _StaleAdapter:
    def __init__(self, timestamp_ms: int) -> None:
        self._timestamp_ms = timestamp_ms

    def fetch_positions(self) -> tuple[dict[str, float], int]:
        return {}, self._timestamp_ms


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
                "snapshot_max_stale_ms": 1_000,
            }
        },
    )


def test_reconcile_stale_snapshot_sets_armed_safe() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        settings = _build_settings(root)
        conn = init_db(settings.db_path)
        try:
            stale_ts = int(time.time() * 1000) - 10_000
            adapter = _StaleAdapter(stale_ts)
            safety = SafetyService(safety_mode_provider=lambda: "ARMED_LIVE")
            execution = ExecutionService(adapter=adapter)
            services = {"safety": safety, "execution": execution}

            orchestrator = Orchestrator(settings=settings, mode="dry-run")
            logger = logging.getLogger("test.stale_snapshot")
            metrics = _DummyMetrics()

            orchestrator._run_reconcile(
                services,
                conn,
                logger,
                metrics,
                allow_auto_promote=False,
                context="startup",
            )

            assert get_system_state(conn, "safety_mode") == "ARMED_SAFE"
            assert get_system_state(conn, "safety_reason_code") == "SNAPSHOT_STALE"
        finally:
            conn.close()
