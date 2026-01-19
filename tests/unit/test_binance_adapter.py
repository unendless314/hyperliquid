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


def test_map_exchange_status() -> None:
    assert binance._map_exchange_status("NEW") == "SUBMITTED"
    assert binance._map_exchange_status("PARTIALLY_FILLED") == "PARTIALLY_FILLED"
    assert binance._map_exchange_status("FILLED") == "FILLED"
    assert binance._map_exchange_status("CANCELED") == "CANCELED"
    assert binance._map_exchange_status("EXPIRED") == "EXPIRED"
    assert binance._map_exchange_status("REJECTED") == "REJECTED"
    assert binance._map_exchange_status("PENDING_CANCEL") == "UNKNOWN"


def test_normalize_binance_symbol() -> None:
    assert binance._normalize_binance_symbol("BTCUSDT") == "BTCUSDT"
    assert binance._normalize_binance_symbol("BTC-USDT") == "BTCUSDT"
    assert binance._normalize_binance_symbol("BTC_USDT") == "BTCUSDT"


def test_duplicate_error_detection() -> None:
    err = binance.BinanceApiError(code=-2010, message="Duplicate order sent.", status_code=400)
    assert binance._is_duplicate_error(err)
    err = binance.BinanceApiError(code=-2010, message="Client order id already exists", status_code=400)
    assert binance._is_duplicate_error(err)
    err = binance.BinanceApiError(code=-2010, message="Account has insufficient balance", status_code=400)
    assert not binance._is_duplicate_error(err)


def test_map_error_to_result() -> None:
    intent = OrderIntent(
        correlation_id="hl-abc-20-BTCUSDT",
        client_order_id="hl-abc-20-BTCUSDT-deadbeef",
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
    insufficient = binance.BinanceApiError(
        code=-2010, message="Account has insufficient balance", status_code=400
    )
    result = binance._map_error_to_result(intent, insufficient)
    assert result.status == "REJECTED"
    assert result.error_code == "INSUFFICIENT_BALANCE"

    server_error = binance.BinanceApiError(
        code=-1000, message="Internal error", status_code=500
    )
    result = binance._map_error_to_result(intent, server_error)
    assert result.status == "UNKNOWN"
    assert result.error_code == "EXCHANGE_ERROR"


def test_fetch_positions_uses_max_update_time() -> None:
    adapter = binance.BinanceExecutionAdapter(_build_live_config())
    payload = [
        {"symbol": "BTC-USDT", "positionAmt": "0.5", "updateTime": 1000},
        {"symbol": "ETHUSDT", "positionAmt": "-0.1", "updateTime": 2000},
        {"symbol": "BTC-USDT", "positionAmt": "0.25", "updateTime": 1500},
    ]
    adapter._client.fetch_positions = lambda: payload
    positions, timestamp_ms = adapter.fetch_positions()
    assert timestamp_ms == 2000
    assert positions["BTCUSDT"] == 0.75
    assert positions["ETHUSDT"] == -0.1


def test_fetch_positions_missing_update_time_returns_zero_timestamp() -> None:
    adapter = binance.BinanceExecutionAdapter(_build_live_config())
    payload = [{"symbol": "BTCUSDT", "positionAmt": "0.1", "updateTime": 0}]
    adapter._client.fetch_positions = lambda: payload
    positions, timestamp_ms = adapter.fetch_positions()
    assert positions["BTCUSDT"] == 0.1
    assert timestamp_ms == 0


def test_parse_exchange_info_filters() -> None:
    payload = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                    {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                ],
            }
        ]
    }
    parsed = binance._parse_exchange_info(payload)
    assert "BTCUSDT" in parsed
    filters = parsed["BTCUSDT"]
    assert str(filters.min_qty) == "0.001"
    assert str(filters.step_size) == "0.001"
    assert str(filters.min_notional) == "5"
    assert str(filters.tick_size) == "0.1"


def test_validate_intent_filters_min_qty() -> None:
    filters = {
        "BTCUSDT": binance.BinanceSymbolFilters(
            min_qty=binance._decimal_from("0.01"),
            step_size=binance._decimal_from("0.01"),
            min_notional=binance._decimal_from("5"),
            tick_size=binance._decimal_from("0.1"),
        )
    }
    intent = OrderIntent(
        correlation_id="hl-abc-30-BTCUSDT",
        client_order_id="hl-abc-30-BTCUSDT-deadbeef",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        qty=0.001,
        price=100.0,
        reduce_only=0,
        time_in_force="IOC",
        is_replay=0,
        risk_notes=None,
    )
    try:
        binance._validate_intent_filters(intent, filters)
        assert False, "expected min qty violation"
    except ValueError as exc:
        assert "qty_below_min_qty" in str(exc)


def test_validate_market_notional_uses_safety_factor() -> None:
    intent = OrderIntent(
        correlation_id="hl-abc-31-BTCUSDT",
        client_order_id="hl-abc-31-BTCUSDT-deadbeef",
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        qty=0.0001,
        price=None,
        reduce_only=0,
        time_in_force="IOC",
        is_replay=0,
        risk_notes=None,
    )
    try:
        binance._validate_market_notional(
            intent=intent,
            min_notional=binance._decimal_from("5"),
            mark_price=binance._decimal_from("50000"),
            safety_factor=binance._decimal_from("1.02"),
        )
        assert False, "expected min notional violation"
    except ValueError as exc:
        assert "min_notional_violation" in str(exc)


def test_execute_market_notional_rejected() -> None:
    config = binance.BinanceExecutionConfig(
        enabled=True,
        mode="live",
        base_url="https://example.test",
        api_key="key",
        api_secret="secret",
        request_timeout_ms=1000,
        recv_window_ms=5000,
        exchange_info_enabled=True,
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
    adapter = binance.BinanceExecutionAdapter(config)
    adapter._client.fetch_exchange_info = lambda: {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                    {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                ],
            }
        ]
    }
    adapter._client.fetch_mark_price = lambda symbol: binance._decimal_from("50000")
    adapter._client.place_order = lambda intent: {"status": "NEW"}
    intent = OrderIntent(
        correlation_id="hl-abc-32-BTCUSDT",
        client_order_id="hl-abc-32-BTCUSDT-deadbeef",
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        qty=0.00005,
        price=None,
        reduce_only=0,
        time_in_force="IOC",
        is_replay=0,
        risk_notes=None,
    )
    result = adapter.execute(intent)
    assert result.status == "REJECTED"
    assert result.error_code == "FILTER_REJECTED"


def test_execute_exchange_info_missing_filters_rejected() -> None:
    config = binance.BinanceExecutionConfig(
        enabled=True,
        mode="live",
        base_url="https://example.test",
        api_key="key",
        api_secret="secret",
        request_timeout_ms=1000,
        recv_window_ms=5000,
        exchange_info_enabled=True,
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
    adapter = binance.BinanceExecutionAdapter(config)
    adapter._client.fetch_exchange_info = lambda: {}
    adapter._client.place_order = lambda intent: {"status": "NEW"}
    intent = OrderIntent(
        correlation_id="hl-abc-33-BTCUSDT",
        client_order_id="hl-abc-33-BTCUSDT-deadbeef",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        qty=0.01,
        price=100.0,
        reduce_only=0,
        time_in_force="IOC",
        is_replay=0,
        risk_notes=None,
    )
    result = adapter.execute(intent)
    assert result.status == "REJECTED"
    assert result.error_code == "FILTER_REJECTED"
