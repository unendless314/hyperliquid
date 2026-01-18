from __future__ import annotations

from pathlib import Path
from typing import List

from hyperliquid.common.settings import Settings
from hyperliquid.ingest.adapters.hyperliquid import HyperliquidIngestAdapter, HyperliquidIngestConfig
from hyperliquid.ingest.service import RawPositionEvent


def _settings_with_symbol_map(symbol_map: dict[str, str]) -> Settings:
    return Settings(
        config_version="0.1",
        environment="local",
        db_path=":memory:",
        metrics_log_path="logs/metrics.log",
        app_log_path="logs/app.log",
        log_level="INFO",
        config_path=Path("config/settings.yaml"),
        raw={
            "config_version": "0.1",
            "environment": "local",
            "db_path": ":memory:",
            "metrics_log_path": "logs/metrics.log",
            "app_log_path": "logs/app.log",
            "log_level": "INFO",
            "ingest": {
                "backfill_window_ms": 0,
                "cursor_overlap_ms": 0,
                "hyperliquid": {
                    "enabled": True,
                    "mode": "live",
                    "target_wallet": "0xabc",
                    "rest_url": "https://example.test/info",
                    "ws_url": "",
                    "request_timeout_ms": 10000,
                    "symbol_map": symbol_map,
                },
            },
        },
    )


def test_unmapped_and_spot_coins_are_skipped() -> None:
    settings = _settings_with_symbol_map({"BTC": "BTCUSDT"})
    adapter = HyperliquidIngestAdapter(HyperliquidIngestConfig.from_settings(settings.raw))

    fills = [
        {"coin": "ETH", "startPosition": 0, "sz": 1, "side": "B", "time": 1, "tid": 10},
        {"coin": "@107", "startPosition": 0, "sz": 1, "side": "B", "time": 2, "tid": 11},
        {"coin": "BTC", "startPosition": 0, "sz": 1, "side": "B", "time": 3, "tid": 12},
    ]
    events = adapter._fills_to_events(fills)

    assert len(events) == 1
    assert events[0].symbol == "BTCUSDT"


def test_live_poll_uses_backfill_method() -> None:
    settings = _settings_with_symbol_map({"BTC": "BTCUSDT"})
    adapter = HyperliquidIngestAdapter(HyperliquidIngestConfig.from_settings(settings.raw))

    called: dict[str, int] = {"count": 0}

    def _fake_fetch_backfill(*, since_ms: int, until_ms: int) -> List[RawPositionEvent]:
        _ = since_ms, until_ms
        called["count"] += 1
        return []

    adapter._fetch_backfill_live = _fake_fetch_backfill  # type: ignore[assignment]
    adapter._poll_live_rest(since_ms=123)

    assert called["count"] == 1
