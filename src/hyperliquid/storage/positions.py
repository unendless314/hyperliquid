from __future__ import annotations

import json
from typing import Dict

from hyperliquid.common.models import OrderIntent, normalize_execution_symbol
from hyperliquid.storage.baseline import load_active_baseline


def load_local_positions_from_orders(
    conn, *, since_ms: int | None = None
) -> Dict[str, float]:
    params: list[object] = []
    query = (
        "SELECT r.filled_qty, i.intent_payload "
        "FROM order_results r "
        "JOIN order_intents i ON r.correlation_id = i.correlation_id "
        "WHERE r.status IN ('FILLED', 'PARTIALLY_FILLED')"
    )
    if since_ms is not None:
        query += " AND r.created_at_ms >= ?"
        params.append(int(since_ms))
    rows = conn.execute(query, params).fetchall()
    positions: Dict[str, float] = {}
    for filled_qty, intent_payload in rows:
        if filled_qty is None or filled_qty == 0:
            continue
        data = json.loads(intent_payload)
        data.setdefault("client_order_id", None)
        data.setdefault("strategy_version", None)
        intent = OrderIntent(**data)
        symbol = normalize_execution_symbol(intent.symbol)
        sign = 1.0 if intent.side == "BUY" else -1.0
        positions[symbol] = positions.get(symbol, 0.0) + (sign * float(filled_qty))
    return positions


def load_local_positions(conn) -> Dict[str, float]:
    baseline = load_active_baseline(conn)
    positions: Dict[str, float] = {}
    since_ms = None
    if baseline is not None:
        positions.update(baseline.positions)
        since_ms = baseline.created_at_ms
    order_positions = load_local_positions_from_orders(conn, since_ms=since_ms)
    for symbol, qty in order_positions.items():
        positions[symbol] = positions.get(symbol, 0.0) + float(qty)
    return positions
