from hyperliquid.common.filters import SymbolFilters, validate_intent_filters
from hyperliquid.common.models import OrderIntent


def _intent(price: float | None) -> OrderIntent:
    return OrderIntent(
        correlation_id="hl-abc-1-BTCUSDT",
        client_order_id="hl-abc-1-BTCUSDT-deadbeef",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        qty=0.001,
        price=price,
        reduce_only=0,
        time_in_force="IOC",
        is_replay=0,
        risk_notes=None,
    )


def test_filter_min_qty_rejects() -> None:
    filters = SymbolFilters(min_qty=0.01, step_size=0.001, min_notional=0.0, tick_size=0.01)
    try:
        validate_intent_filters(_intent(price=100.0), filters, price_override=None)
        assert False, "expected min qty violation"
    except ValueError as exc:
        assert "filter_min_qty" in str(exc)


def test_filter_step_size_rejects() -> None:
    filters = SymbolFilters(min_qty=0.0, step_size=0.002, min_notional=0.0, tick_size=0.01)
    try:
        validate_intent_filters(_intent(price=100.0), filters, price_override=None)
        assert False, "expected step size violation"
    except ValueError as exc:
        assert "filter_step_size" in str(exc)


def test_filter_tick_size_rejects() -> None:
    filters = SymbolFilters(min_qty=0.0, step_size=0.001, min_notional=0.0, tick_size=0.03)
    try:
        validate_intent_filters(_intent(price=100.0), filters, price_override=None)
        assert False, "expected tick size violation"
    except ValueError as exc:
        assert "filter_tick_size" in str(exc)


def test_filter_min_notional_rejects_with_override_price() -> None:
    filters = SymbolFilters(min_qty=0.0, step_size=0.001, min_notional=10.0, tick_size=0.01)
    intent = _intent(price=None)
    try:
        validate_intent_filters(intent, filters, price_override=5.0)
        assert False, "expected min notional violation"
    except ValueError as exc:
        assert "filter_min_notional" in str(exc)
