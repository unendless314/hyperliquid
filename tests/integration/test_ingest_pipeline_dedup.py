from __future__ import annotations

import tempfile
from pathlib import Path

from hyperliquid.common.settings import Settings
from hyperliquid.ingest.coordinator import IngestCoordinator
from hyperliquid.orchestrator.service import Orchestrator
from hyperliquid.storage.db import get_system_state, init_db, set_system_state


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
                "replay_policy": "allow",
            },
            "execution": {"binance": {"enabled": False, "mode": "stub"}},
            "ingest": {
                "backfill_window_ms": 600000,
                "cursor_overlap_ms": 200,
                "hyperliquid": {
                    "enabled": True,
                    "mode": "stub",
                    "stub_events": [
                        {
                            "symbol": "BTCUSDT",
                            "tx_hash": "0xdup",
                            "event_index": 1,
                            "prev_target_net_position": 0.0,
                            "next_target_net_position": 1.0,
                            "timestamp_ms": 1000,
                        },
                        {
                            "symbol": "BTCUSDT",
                            "tx_hash": "0xnew",
                            "event_index": 2,
                            "prev_target_net_position": 1.0,
                            "next_target_net_position": 2.0,
                            "timestamp_ms": 1100,
                        },
                    ],
                },
            },
        },
    )


def test_ingest_pipeline_dedup_across_backfill_and_live(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        settings = _build_settings(root)
        conn = init_db(settings.db_path)
        try:
            monkeypatch.setattr(
                "hyperliquid.ingest.coordinator.time.time",
                lambda: 1.0,
            )
            monkeypatch.setattr(
                "hyperliquid.ingest.adapters.hyperliquid.time.time",
                lambda: 1.0,
            )
            set_system_state(conn, "safety_mode", "ARMED_LIVE")
            set_system_state(conn, "last_processed_timestamp_ms", "900")
            set_system_state(conn, "last_processed_event_key", "900|0|boot|BTCUSDT")
            orchestrator = Orchestrator(settings=settings, mode="dry-run", emit_boot_event=False)
            services = orchestrator._initialize_services(conn, None)
            ingest = services["ingest"]  # type: ignore[assignment]
            pipeline = services["pipeline"]  # type: ignore[assignment]
            coordinator = IngestCoordinator.from_settings(settings, ingest)
            adapter = coordinator.adapter
            live_calls = {"count": 0, "since_ms": None, "events": []}

            def _poll_live_events(*, since_ms: int):
                live_calls["count"] += 1
                live_calls["since_ms"] = since_ms
                events = adapter._filter_stub_events(since_ms=since_ms, until_ms=None)
                live_calls["events"] = events
                return list(events)

            adapter.poll_live_events = _poll_live_events  # type: ignore[assignment]

            events = coordinator.run_once(conn, mode="live")

            assert live_calls["count"] == 1
            assert live_calls["since_ms"] == 1000
            assert {event.tx_hash for event in live_calls["events"]} == {"0xdup", "0xnew"}
            assert len(events) == 2
            results = pipeline.process_events(events)

            assert len(results) == 2
            row = conn.execute("SELECT count(*) FROM processed_txs").fetchone()
            assert row is not None
            assert int(row[0]) == 2
            dup_count = conn.execute(
                "SELECT count(*) FROM processed_txs WHERE tx_hash = ?",
                ("0xdup",),
            ).fetchone()
            assert dup_count is not None
            assert int(dup_count[0]) == 1
            row = conn.execute("SELECT count(*) FROM order_intents").fetchone()
            assert row is not None
            assert int(row[0]) == 2
            row = conn.execute("SELECT count(*) FROM order_results").fetchone()
            assert row is not None
            assert int(row[0]) == 2
            assert get_system_state(conn, "last_processed_event_key") == "1100|2|0xnew|BTCUSDT"
        finally:
            conn.close()
