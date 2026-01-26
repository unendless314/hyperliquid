from __future__ import annotations

import time
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Dict, Optional

from hyperliquid.common.models import normalize_execution_symbol


@dataclass(frozen=True)
class BaselineSnapshot:
    baseline_id: str
    created_at_ms: int
    operator: str
    reason_message: str
    positions: Dict[str, float]


def load_active_baseline(conn) -> Optional[BaselineSnapshot]:
    try:
        row = conn.execute(
            "SELECT baseline_id, created_at_ms, operator, reason_message "
            "FROM baseline_snapshots WHERE active = 1 ORDER BY created_at_ms DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    baseline_id, created_at_ms, operator, reason_message = row
    positions: Dict[str, float] = {}
    try:
        rows = conn.execute(
            "SELECT symbol, qty FROM baseline_positions WHERE baseline_id = ?",
            (baseline_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    for symbol, qty in rows:
        positions[normalize_execution_symbol(symbol)] = float(qty)
    return BaselineSnapshot(
        baseline_id=str(baseline_id),
        created_at_ms=int(created_at_ms),
        operator=str(operator or ""),
        reason_message=str(reason_message or ""),
        positions=positions,
    )


def insert_baseline(
    conn,
    *,
    positions: Dict[str, float],
    operator: str,
    reason_message: str,
    replace: bool,
) -> BaselineSnapshot:
    now_ms = int(time.time() * 1000)
    baseline_id = str(uuid.uuid4())
    if not replace:
        existing = conn.execute(
            "SELECT baseline_id FROM baseline_snapshots WHERE active = 1 LIMIT 1"
        ).fetchone()
        if existing is not None:
            raise ValueError("baseline_active_exists")
    conn.execute("UPDATE baseline_snapshots SET active = 0 WHERE active = 1")
    conn.execute(
        "INSERT INTO baseline_snapshots(baseline_id, created_at_ms, operator, reason_message, active) "
        "VALUES(?, ?, ?, ?, 1)",
        (baseline_id, now_ms, operator, reason_message),
    )
    for symbol, qty in positions.items():
        conn.execute(
            "INSERT INTO baseline_positions(baseline_id, symbol, qty) VALUES(?, ?, ?)",
            (baseline_id, normalize_execution_symbol(symbol), float(qty)),
        )
    conn.commit()
    return BaselineSnapshot(
        baseline_id=baseline_id,
        created_at_ms=now_ms,
        operator=operator,
        reason_message=reason_message,
        positions={normalize_execution_symbol(k): float(v) for k, v in positions.items()},
    )


def reset_baseline(conn) -> None:
    conn.execute("UPDATE baseline_snapshots SET active = 0 WHERE active = 1")
    conn.commit()
