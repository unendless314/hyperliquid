import logging
from pathlib import Path

from hyperliquid.common.metrics import MetricsEmitter
from hyperliquid.common.settings import Settings
from hyperliquid.orchestrator.service import Orchestrator
from hyperliquid.storage.db import get_system_state
from hyperliquid.storage.safety import set_safety_state


def _build_settings(
    db_path: str,
    tmp_path,
    *,
    ingest_enabled: bool,
    stub_events=None,
    safety_overrides=None,
) -> Settings:
    safety = {"reconcile_interval_sec": 0}
    if safety_overrides:
        safety.update(safety_overrides)
    return Settings(
        config_version="0.1",
        environment="local",
        db_path=db_path,
        metrics_log_path=str(tmp_path / "metrics.log"),
        app_log_path=str(tmp_path / "app.log"),
        log_level="INFO",
        config_path=Path("config/settings.yaml"),
        raw={
            "decision": {"strategy_version": "v1"},
            "execution": {"binance": {"enabled": False, "mode": "stub"}},
            "safety": safety,
            "ingest": {
                "maintenance_skip_gap": False,
                "backfill_window_ms": 0,
                "cursor_overlap_ms": 0,
                "hyperliquid": {
                    "enabled": ingest_enabled,
                    "mode": "stub",
                    "stub_events": stub_events or [],
                },
            },
            "orchestrator": {
                "loop_idle_sleep_sec": 1,
                "loop_max_idle_sleep_sec": 4,
                "loop_active_sleep_sec": 0,
                "loop_heartbeat_sec": 1,
                "loop_tick_warn_sec": 30,
            },
        },
    )


class DummyAdapter:
    def __init__(self, positions=None, timestamp_ms: int = 0) -> None:
        self._positions = positions or {}
        self._timestamp_ms = timestamp_ms

    def fetch_positions(self):
        return self._positions, self._timestamp_ms


def test_loop_restart_does_not_rewind_cursor(db_conn, db_path, tmp_path, monkeypatch) -> None:
    stub_events = [
        {
            "symbol": "BTCUSDT",
            "tx_hash": "0xloop",
            "event_index": 0,
            "prev_target_net_position": 0.0,
            "next_target_net_position": 0.01,
            "timestamp_ms": 1000,
        }
    ]
    settings = _build_settings(
        db_path, tmp_path, ingest_enabled=True, stub_events=stub_events
    )
    logger = logging.getLogger("test_loop_restart")
    metrics = MetricsEmitter(str(tmp_path / "metrics_loop_restart.log"))
    orchestrator = Orchestrator(settings=settings, mode="dry-run", emit_boot_event=False)
    services = orchestrator._initialize_services(db_conn, logger)

    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
    orchestrator._run_loop(services, db_conn, logger, metrics, max_ticks=1)
    first_cursor = int(get_system_state(db_conn, "last_processed_timestamp_ms") or 0)

    orchestrator._run_loop(services, db_conn, logger, metrics, max_ticks=1)
    second_cursor = int(get_system_state(db_conn, "last_processed_timestamp_ms") or 0)

    assert first_cursor == 1000
    assert second_cursor >= first_cursor
    metrics.close()


def test_loop_idle_backoff_sleeps(db_conn, db_path, tmp_path, monkeypatch) -> None:
    settings = _build_settings(db_path, tmp_path, ingest_enabled=False)
    logger = logging.getLogger("test_loop_idle")
    metrics = MetricsEmitter(str(tmp_path / "metrics_loop_idle.log"))
    orchestrator = Orchestrator(settings=settings, mode="dry-run", emit_boot_event=False)
    services = orchestrator._initialize_services(db_conn, logger)

    sleeps: list[int] = []

    def _record_sleep(value: float) -> None:
        sleeps.append(int(value))

    monkeypatch.setattr("time.sleep", _record_sleep)
    orchestrator._run_loop(services, db_conn, logger, metrics, max_ticks=2)

    assert sleeps == [1, 2]
    metrics.close()


def test_loop_handles_keyboard_interrupt(db_conn, db_path, tmp_path, monkeypatch) -> None:
    settings = _build_settings(db_path, tmp_path, ingest_enabled=False)
    logger = logging.getLogger("test_loop_interrupt")
    metrics = MetricsEmitter(str(tmp_path / "metrics_loop_interrupt.log"))
    orchestrator = Orchestrator(settings=settings, mode="dry-run", emit_boot_event=False)
    services = orchestrator._initialize_services(db_conn, logger)

    def _raise_interrupt(_value: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", _raise_interrupt)
    orchestrator._run_loop(services, db_conn, logger, metrics, max_ticks=5)
    metrics.close()


def test_halt_auto_recovery_backfill_window(db_conn, db_path, tmp_path, monkeypatch) -> None:
    settings = _build_settings(
        db_path,
        tmp_path,
        ingest_enabled=False,
        safety_overrides={
            "reconcile_interval_sec": 1,
            "warn_threshold": 0.1,
            "critical_threshold": 1.0,
            "snapshot_max_stale_ms": 100000,
        },
    )
    settings.raw["ingest"]["maintenance_skip_gap"] = True
    logger = logging.getLogger("test_halt_auto_recovery_stale")
    metrics = MetricsEmitter(str(tmp_path / "metrics_loop_recovery.log"))
    orchestrator = Orchestrator(settings=settings, mode="dry-run", emit_boot_event=False)
    services = orchestrator._initialize_services(db_conn, logger)

    set_safety_state(
        db_conn,
        mode="HALT",
        reason_code="BACKFILL_WINDOW_EXCEEDED",
        reason_message="test",
    )
    from hyperliquid.storage.db import set_system_state

    set_system_state(db_conn, "maintenance_skip_applied_ms", "1000")

    clock = {"t": 1000.0}

    def _fake_time() -> float:
        clock["t"] += 2.0
        return clock["t"]

    monkeypatch.setattr("time.time", _fake_time)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
    services["execution"].adapter = DummyAdapter(timestamp_ms=int(clock["t"] * 1000))

    orchestrator._run_loop(services, db_conn, logger, metrics, max_ticks=1)
    assert get_system_state(db_conn, "safety_mode") == "ARMED_SAFE"
    assert get_system_state(db_conn, "safety_reason_code") == "HALT_RECOVERY_AUTO"
    metrics.close()


def test_halt_auto_recovery_requires_consecutive_ok(db_conn, db_path, tmp_path, monkeypatch) -> None:
    settings = _build_settings(
        db_path,
        tmp_path,
        ingest_enabled=False,
        safety_overrides={
            "reconcile_interval_sec": 1,
            "warn_threshold": 0.1,
            "critical_threshold": 1.0,
            "snapshot_max_stale_ms": 100000,
        },
    )
    logger = logging.getLogger("test_halt_auto_recovery_count")
    metrics = MetricsEmitter(str(tmp_path / "metrics_loop_recovery_count.log"))
    orchestrator = Orchestrator(settings=settings, mode="dry-run", emit_boot_event=False)
    services = orchestrator._initialize_services(db_conn, logger)

    set_safety_state(
        db_conn,
        mode="HALT",
        reason_code="RECONCILE_CRITICAL",
        reason_message="test",
    )

    clock = {"t": 2000.0}

    def _fake_time() -> float:
        clock["t"] += 2.0
        return clock["t"]

    monkeypatch.setattr("time.time", _fake_time)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
    services["execution"].adapter = DummyAdapter(timestamp_ms=int(clock["t"] * 1000))

    orchestrator._run_loop(services, db_conn, logger, metrics, max_ticks=3)
    assert get_system_state(db_conn, "safety_mode") == "ARMED_SAFE"
    assert get_system_state(db_conn, "safety_reason_code") == "HALT_RECOVERY_AUTO"
    metrics.close()
