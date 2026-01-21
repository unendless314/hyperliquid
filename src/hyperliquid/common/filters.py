from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from hyperliquid.common.models import OrderIntent


@dataclass(frozen=True)
class SymbolFilters:
    min_qty: float
    step_size: float
    min_notional: float
    tick_size: float


def _decimal_from(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _is_multiple(value: Decimal, step: Decimal) -> bool:
    if step <= 0:
        return True
    return (value % step) == 0


def validate_intent_filters(
    intent: OrderIntent, filters: SymbolFilters, price_override: Optional[float]
) -> None:
    qty = _decimal_from(intent.qty)
    min_qty = _decimal_from(filters.min_qty)
    step_size = _decimal_from(filters.step_size)
    if min_qty > 0 and qty < min_qty:
        raise ValueError("filter_min_qty")
    if not _is_multiple(qty, step_size):
        raise ValueError("filter_step_size")

    price = intent.price
    if price is None:
        price = price_override
    if price is None:
        return

    price_dec = _decimal_from(price)
    tick_size = _decimal_from(filters.tick_size)
    if not _is_multiple(price_dec, tick_size):
        raise ValueError("filter_tick_size")
    min_notional = _decimal_from(filters.min_notional)
    if min_notional > 0 and (price_dec * qty) < min_notional:
        raise ValueError("filter_min_notional")
