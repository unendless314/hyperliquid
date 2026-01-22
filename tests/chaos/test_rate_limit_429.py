from __future__ import annotations

from hyperliquid.common.models import OrderIntent
from hyperliquid.execution.adapters import binance


def _build_live_config() -> binance.BinanceExecutionConfig:
    return binance.BinanceExecutionConfig(
        enabled=True,
        mode="live",
        base_url="https://example.test",
        api_key="key",
        api_secret="secret",
        request_timeout_ms=1000,
        recv_window_ms=5000,
        exchange_info_enabled=False,
        exchange_info_ttl_sec=300,
        rate_limit=binance.RateLimitPolicy(
            max_requests=0,
            per_seconds=1,
            cooldown_seconds=0,
        ),
        retry=binance.RetryPolicy(
            max_attempts=1,
            base_delay_ms=0,
            max_delay_ms=0,
            jitter_ms=0,
        ),
    )


def _build_intent() -> OrderIntent:
    return OrderIntent(
        correlation_id="hl-chaos-2-BTCUSDT",
        client_order_id="hl-chaos-2-BTCUSDT-deadbeef",
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        qty=1.0,
        price=None,
        reduce_only=0,
        time_in_force="IOC",
        is_replay=0,
        risk_notes=None,
    )


def test_rate_limit_maps_to_unknown() -> None:
    adapter = binance.BinanceExecutionAdapter(_build_live_config())
    adapter._client.place_order = lambda intent: (_ for _ in ()).throw(
        binance.BinanceRateLimitError("rate limit")
    )
    result = adapter.execute(_build_intent())
    assert result.status == "UNKNOWN"
    assert result.error_code == "RATE_LIMITED"
