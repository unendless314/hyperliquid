from __future__ import annotations

import os
from pathlib import Path
from typing import List

import pytest

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


@pytest.fixture(autouse=True)
def _set_hyperliquid_target_wallet_env() -> None:
    os.environ["HYPERLIQUID_TARGET_WALLET"] = "0xabc"


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


def test_fills_are_aggregated_by_hash_and_coin() -> None:
    settings = _settings_with_symbol_map({"BTC": "BTCUSDT", "ETH": "ETHUSDT"})
    adapter = HyperliquidIngestAdapter(HyperliquidIngestConfig.from_settings(settings.raw))

    fills = [
        {
            "coin": "BTC",
            "hash": "0xabc",
            "startPosition": 1.0,
            "sz": 2.0,
            "side": "B",
            "time": 20,
            "tid": 2,
        },
        {
            "coin": "BTC",
            "hash": "0xabc",
            "startPosition": 0.0,
            "sz": 1.0,
            "side": "B",
            "time": 10,
            "tid": 1,
        },
        {
            "coin": "ETH",
            "hash": "0xabc",
            "startPosition": 0.0,
            "sz": 3.0,
            "side": "B",
            "time": 15,
            "tid": 3,
        },
    ]

    events = adapter._fills_to_events(fills)

    assert len(events) == 2
    btc_event = next(event for event in events if event.symbol == "BTCUSDT")
    eth_event = next(event for event in events if event.symbol == "ETHUSDT")

    assert btc_event.tx_hash == "0xabc"
    assert btc_event.event_index == 2
    assert btc_event.timestamp_ms == 20
    assert btc_event.prev_target_net_position == 0.0
    assert btc_event.next_target_net_position == 3.0

    assert eth_event.tx_hash == "0xabc"
    assert eth_event.event_index == 3
    assert eth_event.prev_target_net_position == 0.0
    assert eth_event.next_target_net_position == 3.0


def test_single_hash_single_symbol_aggregates_into_one_event() -> None:
    settings = _settings_with_symbol_map({"BTC": "BTCUSDT"})
    adapter = HyperliquidIngestAdapter(HyperliquidIngestConfig.from_settings(settings.raw))

    fills = [
        {
            "coin": "BTC",
            "hash": "0xdef",
            "startPosition": 0.0,
            "sz": 0.5,
            "side": "B",
            "time": 100,
            "tid": 10,
        },
        {
            "coin": "BTC",
            "hash": "0xdef",
            "startPosition": 0.5,
            "sz": 1.5,
            "side": "B",
            "time": 200,
            "tid": 11,
        },
    ]

    events = adapter._fills_to_events(fills)

    assert len(events) == 1
    event = events[0]
    assert event.symbol == "BTCUSDT"
    assert event.tx_hash == "0xdef"
    assert event.event_index == 11
    assert event.timestamp_ms == 200
    assert event.prev_target_net_position == 0.0
    assert event.next_target_net_position == 2.0
