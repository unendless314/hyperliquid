from __future__ import annotations

from hyperliquid.common.models import OrderIntent
from hyperliquid.execution.adapters import binance


def _build_intent(correlation_id: str) -> OrderIntent:
    return OrderIntent(
        correlation_id=correlation_id,
        client_order_id=f"{correlation_id}-client",
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


def _build_live_config(*, max_requests: int = 0) -> binance.BinanceExecutionConfig:
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
            max_requests=max_requests,
            per_seconds=60,
            cooldown_seconds=0,
        ),
        retry=binance.RetryPolicy(
            max_attempts=1,
            base_delay_ms=0,
            max_delay_ms=0,
            jitter_ms=0,
        ),
    )


def test_live_rate_limit_returns_unknown() -> None:
    adapter = binance.BinanceExecutionAdapter(_build_live_config(max_requests=1))
    adapter._client.place_order = lambda intent: {"status": "NEW"}

    first = adapter.execute(_build_intent("hl-rate-1"))
    second = adapter.execute(_build_intent("hl-rate-2"))

    assert first.status == "SUBMITTED"
    assert second.status == "UNKNOWN"
    assert second.error_code == "RATE_LIMITED"


def test_live_timeout_maps_to_unknown() -> None:
    adapter = binance.BinanceExecutionAdapter(_build_live_config())
    adapter._client.place_order = lambda intent: (_ for _ in ()).throw(
        binance.BinanceTimeoutError("Request timeout")
    )

    result = adapter.execute(_build_intent("hl-timeout-1"))

    assert result.status == "UNKNOWN"
    assert result.error_code == "TIMEOUT"


def test_live_duplicate_order_queries_status() -> None:
    adapter = binance.BinanceExecutionAdapter(_build_live_config())
    adapter._client.place_order = lambda intent: (_ for _ in ()).throw(
        binance.BinanceApiError(
            code=-2010, message="Duplicate order sent.", status_code=400
        )
    )
    adapter._client.query_order = lambda intent: {
        "status": "FILLED",
        "executedQty": "1.0",
        "avgPrice": "101.5",
        "orderId": "12345",
    }

    result = adapter.execute(_build_intent("hl-dup-1"))

    assert result.status == "FILLED"
    assert result.exchange_order_id == "12345"
