from __future__ import annotations

import tempfile
from pathlib import Path

from hyperliquid.common.settings import Settings
from hyperliquid.ingest.coordinator import IngestCoordinator
from hyperliquid.ingest.service import IngestService
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
            "ingest": {
                "backfill_window_ms": 600000,
                "cursor_overlap_ms": 200,
                "hyperliquid": {
                    "enabled": True,
                    "mode": "live",
                    "rest_url": "https://example.invalid",
                    "ws_url": "",
                    "symbol_map": {"BTC": "BTCUSDT"},
                    "rate_limit": {"max_requests": 0},
                    "retry": {"max_attempts": 1},
                },
            }
        },
    )


def test_ws_reconnect_backfill_overlap_dedup(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        settings = _build_settings(root)
        monkeypatch.setenv("HYPERLIQUID_TARGET_WALLET", "0xtest")
        monkeypatch.setattr(
            "hyperliquid.ingest.adapters.hyperliquid.time.time",
            lambda: 40.0,
        )
        monkeypatch.setattr(
            "hyperliquid.ingest.coordinator.time.time",
            lambda: 40.0,
        )

        conn = init_db(settings.db_path)
        try:
            set_system_state(conn, "last_processed_timestamp_ms", "1000")
            ingest = IngestService()
            coordinator = IngestCoordinator.from_settings(settings, ingest)
            adapter = coordinator.adapter

            fills = [
                {
                    "coin": "BTC",
                    "startPosition": 0.0,
                    "sz": 1.0,
                    "side": "B",
                    "hash": "0xdup",
                    "tid": 1,
                    "time": 1000,
                },
            ]
            backfill_responses = [list(fills), []]
            live_fills = [
                {
                    "coin": "BTC",
                    "startPosition": 0.0,
                    "sz": 1.0,
                    "side": "B",
                    "hash": "0xdup",
                    "tid": 1,
                    "time": 1000,
                },
                {
                    "coin": "BTC",
                    "startPosition": 1.0,
                    "sz": 1.0,
                    "side": "B",
                    "hash": "0xnew",
                    "tid": 2,
                    "time": 1100,
                },
            ]

            def _post_json(_payload):
                return backfill_responses.pop(0)

            live_rest_called = {"value": False}

            def _poll_live_rest(*, since_ms: int):
                live_rest_called["value"] = True
                events = adapter._fills_to_events(live_fills)
                return [event for event in events if (event.timestamp_ms or 0) >= since_ms]

            monkeypatch.setattr(adapter, "_post_json", _post_json)
            monkeypatch.setattr(adapter, "_poll_live_rest", _poll_live_rest)
            adapter._ws_enabled = True
            adapter._last_ws_message_ms = 0

            events = coordinator.run_once(conn, mode="live")

            assert live_rest_called["value"] is True
            assert len(events) == 2
            assert get_system_state(conn, "last_processed_event_key") == "1100|2|0xnew|BTCUSDT"
            row = conn.execute("SELECT count(*) FROM processed_txs").fetchone()
            assert row is not None
            assert int(row[0]) == 2
            replay_row = conn.execute(
                "SELECT is_replay FROM processed_txs WHERE tx_hash = ? AND event_index = ? AND symbol = ?",
                ("0xdup", 1, "BTCUSDT"),
            ).fetchone()
            assert replay_row is not None
            assert int(replay_row[0]) == 1
        finally:
            conn.close()
