from pathlib import Path

from hyperliquid.common.settings import Settings
from hyperliquid.ingest.coordinator import IngestCoordinator, IngestRuntimeConfig
from hyperliquid.ingest.service import IngestService, RawPositionEvent
from hyperliquid.storage.db import set_system_state


class _FakeAdapter:
    def __init__(self, events):
        self.events = events
        self.since_ms = None
        self.until_ms = None
        self.live_since_ms = None

    def fetch_backfill(self, *, since_ms: int, until_ms: int):
        self.since_ms = since_ms
        self.until_ms = until_ms
        return list(self.events)

    def poll_live_events(self, *, since_ms: int):
        self.live_since_ms = since_ms
        return []


def _build_settings(db_path: str) -> Settings:
    return Settings(
        config_version="0.1",
        environment="local",
        db_path=db_path,
        metrics_log_path="logs/metrics.log",
        app_log_path="logs/app.log",
        log_level="INFO",
        config_path=Path("config/settings.yaml"),
        raw={
            "config_version": "0.1",
            "environment": "local",
            "db_path": db_path,
            "metrics_log_path": "logs/metrics.log",
            "app_log_path": "logs/app.log",
            "log_level": "INFO",
            "ingest": {
                "maintenance_skip_gap": False,
                "backfill_window_ms": 600000,
                "cursor_overlap_ms": 200,
                "hyperliquid": {
                    "enabled": False,
                    "mode": "stub",
                },
            },
        },
    )


def test_backfill_uses_overlap_and_marks_replay(db_conn, db_path, monkeypatch) -> None:
    settings = _build_settings(db_path)
    ingest = IngestService()
    runtime = IngestRuntimeConfig.from_settings(settings)

    raw_event = RawPositionEvent(
        symbol="BTCUSDT",
        tx_hash="0xoverlap",
        event_index=1,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        is_replay=0,
        timestamp_ms=1700000000000,
    )
    adapter = _FakeAdapter([raw_event])
    coordinator = IngestCoordinator(
        ingest_service=ingest,
        adapter=adapter,
        runtime=runtime,
    )

    fixed_now = 1700000001000
    monkeypatch.setattr("hyperliquid.ingest.coordinator.time.time", lambda: fixed_now / 1000.0)
    set_system_state(db_conn, "last_processed_timestamp_ms", "1700000000500")

    events = coordinator.run_once(db_conn, mode="live")

    assert adapter.since_ms == 1700000000500 - runtime.cursor_overlap_ms
    assert adapter.until_ms == fixed_now
    assert len(events) == 1
    assert events[0].is_replay == 1
