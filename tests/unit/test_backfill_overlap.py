from __future__ import annotations

import tempfile
from pathlib import Path

from hyperliquid.common.settings import Settings
from hyperliquid.ingest.coordinator import IngestCoordinator
from hyperliquid.ingest.service import IngestService, RawPositionEvent
from hyperliquid.storage.db import init_db, set_system_state


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
            "ingest": {
                "backfill_window_ms": 600000,
                "cursor_overlap_ms": 200,
                "hyperliquid": {"enabled": True, "mode": "stub"},
            }
        },
    )


def test_backfill_overlap_marks_replay_and_dedups(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        settings = _build_settings(root)
        monkeypatch.setattr(
            "hyperliquid.ingest.coordinator.time.time",
            lambda: 2.0,
        )

        conn = init_db(settings.db_path)
        try:
            set_system_state(conn, "last_processed_timestamp_ms", "1000")
            ingest = IngestService()
            coordinator = IngestCoordinator.from_settings(settings, ingest)

            backfill_events = [
                RawPositionEvent(
                    symbol="BTCUSDT",
                    tx_hash="0xdup",
                    event_index=1,
                    prev_target_net_position=0.0,
                    next_target_net_position=1.0,
                    timestamp_ms=1000,
                ),
                RawPositionEvent(
                    symbol="BTCUSDT",
                    tx_hash="0xnew",
                    event_index=2,
                    prev_target_net_position=1.0,
                    next_target_net_position=2.0,
                    timestamp_ms=1100,
                ),
            ]
            monkeypatch.setattr(
                coordinator.adapter,
                "fetch_backfill",
                lambda *, since_ms, until_ms: list(backfill_events),
            )

            first = coordinator.run_once(conn, mode="backfill-only")
            assert len(first) == 2
            assert all(event.is_replay == 1 for event in first)

            second = coordinator.run_once(conn, mode="backfill-only")
            assert second == []
        finally:
            conn.close()
