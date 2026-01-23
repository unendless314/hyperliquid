from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from hyperliquid.common.models import PriceSnapshot


@dataclass(frozen=True)
class DecisionInputs:
    safety_mode: str
    local_current_position: Optional[float] = None
    closable_qty: Optional[float] = None
    expected_price: Optional[PriceSnapshot] = None
