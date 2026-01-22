from __future__ import annotations

import json
import tempfile
from pathlib import Path

from hyperliquid.common.models import OrderIntent, OrderResult
from hyperliquid.common.settings import Settings
from hyperliquid.ingest.service import IngestService
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
            "execution": {"binance": {"enabled": False, "mode": "stub"}},
        },
    )


def test_partial_fill_close_qty_uses_local_position() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        settings = _build_settings(root)
        conn = init_db(settings.db_path)
        try:
            set_system_state(conn, "safety_mode", "ARMED_LIVE")

            persistence = DbPersistence(conn)
            seed_intent = OrderIntent(
                correlation_id="hl-seed-partial-1-BTCUSDT",
                client_order_id="hl-seed-partial-1-BTCUSDT-deadbeef",
                symbol="BTCUSDT",
                side="BUY",
                order_type="MARKET",
                qty=1.0,
                price=None,
                reduce_only=0,
                time_in_force="IOC",
                is_replay=0,
            )
            persistence.record_intent(seed_intent)
            persistence.record_result(
                OrderResult(
                    correlation_id=seed_intent.correlation_id,
                    exchange_order_id="ex-1",
                    status="PARTIALLY_FILLED",
                    filled_qty=0.4,
                    avg_price=100.0,
                    error_code=None,
                    error_message=None,
                )
            )

            orchestrator = Orchestrator(settings=settings, mode="dry-run", emit_boot_event=False)
            services = orchestrator._initialize_services(conn, None)
            pipeline = services["pipeline"]  # type: ignore[assignment]

            ingest = IngestService()
            event = ingest.build_position_delta_event(
                symbol="BTCUSDT",
                tx_hash="0xclose",
                event_index=1,
                prev_target_net_position=1.0,
                next_target_net_position=0.0,
                is_replay=0,
                timestamp_ms=1000,
            )

            results = pipeline.process_single_event(event)

            assert len(results) == 1
            assert results[0].status == "SUBMITTED"
            row = conn.execute(
                "SELECT intent_payload FROM order_intents WHERE correlation_id = ?",
                ("hl-0xclose-1-BTCUSDT",),
            ).fetchone()
            assert row is not None
            payload = json.loads(row[0])
            assert payload["correlation_id"] == "hl-0xclose-1-BTCUSDT"
            assert payload["reduce_only"] == 1
            assert abs(float(payload["qty"]) - 0.4) < 1e-9
        finally:
            conn.close()
