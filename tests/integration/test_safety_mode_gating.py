from __future__ import annotations

import tempfile
from pathlib import Path

from hyperliquid.common.models import OrderIntent, OrderResult
from hyperliquid.common.settings import Settings
from hyperliquid.ingest.coordinator import IngestCoordinator
from hyperliquid.orchestrator.service import Orchestrator
from hyperliquid.storage.db import init_db, set_system_state
from hyperliquid.storage.persistence import DbPersistence


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
            "decision": {"strategy_version": "v1"},
            "execution": {"binance": {"enabled": False, "mode": "stub"}},
            "ingest": {
                "backfill_window_ms": 600000,
                "cursor_overlap_ms": 0,
                "hyperliquid": {
                    "enabled": True,
                    "mode": "stub",
                    "stub_events": [
                        {
                            "symbol": "BTCUSDT",
                            "tx_hash": "0xinc",
                            "event_index": 1,
                            "prev_target_net_position": 0.0,
                            "next_target_net_position": 1.0,
                            "timestamp_ms": 1000,
                        },
                        {
                            "symbol": "BTCUSDT",
                            "tx_hash": "0xdec",
                            "event_index": 2,
                            "prev_target_net_position": 1.0,
                            "next_target_net_position": 0.0,
                            "timestamp_ms": 1100,
                        },
                        {
                            "symbol": "BTCUSDT",
                            "tx_hash": "0xinc2",
                            "event_index": 3,
                            "prev_target_net_position": 0.0,
                            "next_target_net_position": 1.0,
                            "timestamp_ms": 1200,
                        },
                    ],
                },
            },
        },
    )


def test_safety_mode_gating_reduce_only_and_halt(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        settings = _build_settings(root)
        conn = init_db(settings.db_path)
        try:
            monkeypatch.setattr(
                "hyperliquid.ingest.coordinator.time.time",
                lambda: 1.05,
            )
            set_system_state(conn, "last_processed_timestamp_ms", "0")
            set_system_state(conn, "last_processed_event_key", "")

            orchestrator = Orchestrator(settings=settings, mode="dry-run", emit_boot_event=False)
            services = orchestrator._initialize_services(conn, None)
            ingest = services["ingest"]  # type: ignore[assignment]
            pipeline = services["pipeline"]  # type: ignore[assignment]
            coordinator = IngestCoordinator.from_settings(settings, ingest)

            persistence = DbPersistence(conn)
            intent = OrderIntent(
                correlation_id="hl-seed-1-BTCUSDT",
                client_order_id="hl-seed-1-BTCUSDT-deadbeef",
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
                    correlation_id=intent.correlation_id,
                    exchange_order_id="ex-1",
                    status="FILLED",
                    filled_qty=1.0,
                    avg_price=100.0,
                    error_code=None,
                    error_message=None,
                )
            )

            set_system_state(conn, "safety_mode", "ARMED_SAFE")
            events = coordinator.run_once(conn, mode="live")
            results = pipeline.process_events(events)

            assert [result.correlation_id for result in results] == ["hl-0xdec-2-BTCUSDT"]

            set_system_state(conn, "safety_mode", "HALT")
            events = coordinator.run_once(conn, mode="live")
            results = pipeline.process_events(events)

            assert results == []
        finally:
            conn.close()
