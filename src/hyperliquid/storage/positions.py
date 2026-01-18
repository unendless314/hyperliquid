from __future__ import annotations

import json
from typing import Dict

from hyperliquid.common.models import OrderIntent, normalize_symbol


def load_local_positions_from_orders(conn) -> Dict[str, float]:
    rows = conn.execute(
        "SELECT r.filled_qty, i.intent_payload "
        "FROM order_results r "
        "JOIN order_intents i ON r.correlation_id = i.correlation_id "
        "WHERE r.status IN ('FILLED', 'PARTIALLY_FILLED')"
    ).fetchall()
    positions: Dict[str, float] = {}
    for filled_qty, intent_payload in rows:
        if filled_qty is None or filled_qty == 0:
            continue
        data = json.loads(intent_payload)
        data.setdefault("client_order_id", None)
        intent = OrderIntent(**data)
        symbol = normalize_symbol(intent.symbol)
        sign = 1.0 if intent.side == "BUY" else -1.0
        positions[symbol] = positions.get(symbol, 0.0) + (sign * float(filled_qty))
    return positions
