from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from hyperliquid.common.models import OrderIntent, OrderResult
from hyperliquid.common.metrics import MetricsEmitter
from hyperliquid.common.settings import Settings
from hyperliquid.orchestrator.service import Orchestrator
from hyperliquid.storage.db import get_system_state, init_db
from hyperliquid.storage.persistence import DbPersistence
from hyperliquid.storage.safety import set_safety_state


class AdapterStub:
    def __init__(self) -> None:
        self.positions = {"BTCUSDT": 1.0}

    def fetch_positions(self):
        return self.positions, int(__import__("time").time() * 1000)


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
            "decision": {
                "strategy_version": "v1",
                "replay_policy": "close_only",
            },
            "execution": {"binance": {"enabled": False, "mode": "stub"}},
            "safety": {
                "reconcile_interval_sec": 1,
                "warn_threshold": 0.1,
                "critical_threshold": 1.0,
                "snapshot_max_stale_ms": 120000,
                "halt_recovery_noncritical_required": 3,
                "halt_recovery_window_sec": 60,
            },
            "ingest": {
                "backfill_window_ms": 600000,
                "cursor_overlap_ms": 0,
                "hyperliquid": {
                    "enabled": True,
                    "mode": "stub",
                    "stub_events": [
                        {
                            "symbol": "BTCUSDT",
                            "tx_hash": "0xreduce",
                            "event_index": 1,
                            "prev_target_net_position": 1.0,
                            "next_target_net_position": 0.0,
                            "timestamp_ms": 5000,
                        }
                    ],
                },
            },
            "orchestrator": {
                "loop_idle_sleep_sec": 1,
                "loop_max_idle_sleep_sec": 2,
                "loop_active_sleep_sec": 0,
                "loop_heartbeat_sec": 1,
                "loop_tick_warn_sec": 30,
            },
        },
    )


def test_halt_auto_recovery_allows_reduce_only(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        settings = _build_settings(root)
        conn = init_db(settings.db_path)
        try:
            persistence = DbPersistence(conn)
            intent = OrderIntent(
                correlation_id="seed-1",
                client_order_id=None,
                strategy_version="v1",
                symbol="BTCUSDT",
                side="BUY",
                order_type="MARKET",
                qty=1.0,
                price=None,
                reduce_only=0,
                time_in_force="IOC",
                is_replay=0,
            )
            persistence.record_intent(intent)
            persistence.record_result(
                OrderResult(
                    correlation_id="seed-1",
                    exchange_order_id=None,
                    status="FILLED",
                    filled_qty=1.0,
                    avg_price=100.0,
                    error_code=None,
                    error_message=None,
                )
            )

            set_safety_state(
                conn,
                mode="HALT",
                reason_code="RECONCILE_CRITICAL",
                reason_message="test",
            )

            orchestrator = Orchestrator(settings=settings, mode="dry-run", emit_boot_event=False)
            services = orchestrator._initialize_services(conn, None)
            services["execution"].adapter = AdapterStub()
            logger = logging.getLogger("test_halt_auto_recovery_reduce_only")
            metrics = MetricsEmitter(str(root / "metrics_loop.log"))

            clock = {"t": 1000.0}

            def _fake_time() -> float:
                clock["t"] += 2.0
                return clock["t"]

            monkeypatch.setattr("time.time", _fake_time)
            monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
            monkeypatch.setattr("hyperliquid.ingest.adapters.hyperliquid.time.time", _fake_time)

            orchestrator._run_loop(services, conn, logger, metrics, max_ticks=4)

            assert get_system_state(conn, "safety_mode") == "ARMED_SAFE"
            row = conn.execute(
                "SELECT intent_payload FROM order_intents WHERE correlation_id = ?",
                ("hl-0xreduce-1-BTCUSDT",),
            ).fetchone()
            assert row is not None
            payload = json.loads(row[0])
            assert payload["reduce_only"] == 1
            metrics.close()
        finally:
            conn.close()
