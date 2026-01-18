import tempfile
from pathlib import Path

from hyperliquid.common.settings import Settings
from hyperliquid.ingest.coordinator import IngestCoordinator
from hyperliquid.ingest.service import IngestService
from hyperliquid.storage.db import get_system_state, init_db, set_system_state


def _build_settings(db_path: str, *, maintenance_skip_gap: bool) -> Settings:
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
                "maintenance_skip_gap": maintenance_skip_gap,
                "backfill_window_ms": 600000,
                "cursor_overlap_ms": 5000,
                "hyperliquid": {
                    "enabled": False,
                    "mode": "stub",
                },
            },
        },
    )


def test_maintenance_skip_applies_only_for_gap_halt() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        conn = init_db(tmp.name)
        settings = _build_settings(tmp.name, maintenance_skip_gap=True)
        ingest = IngestService()
        coordinator = IngestCoordinator.from_settings(settings, ingest)

        set_system_state(conn, "safety_mode", "HALT")
        set_system_state(conn, "safety_reason_code", "BACKFILL_WINDOW_EXCEEDED")
        set_system_state(conn, "last_processed_timestamp_ms", "0")

        events = coordinator.run_once(conn, mode="live")

        assert events == []
        assert get_system_state(conn, "safety_mode") == "ARMED_SAFE"
        assert get_system_state(conn, "safety_reason_code") == "MAINTENANCE_SKIP_GAP"
        event_key = get_system_state(conn, "last_processed_event_key")
        assert event_key is not None and "maintenance" in event_key


def test_maintenance_skip_does_not_bypass_non_gap_halt() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        conn = init_db(tmp.name)
        settings = _build_settings(tmp.name, maintenance_skip_gap=True)
        ingest = IngestService()
        coordinator = IngestCoordinator.from_settings(settings, ingest)

        set_system_state(conn, "safety_mode", "HALT")
        set_system_state(conn, "safety_reason_code", "SCHEMA_VERSION_MISMATCH")
        set_system_state(conn, "last_processed_timestamp_ms", "0")

        events = coordinator.run_once(conn, mode="live")

        assert events == []
        assert get_system_state(conn, "safety_mode") == "HALT"
        assert get_system_state(conn, "safety_reason_code") == "SCHEMA_VERSION_MISMATCH"
        assert get_system_state(conn, "last_processed_event_key") is None
