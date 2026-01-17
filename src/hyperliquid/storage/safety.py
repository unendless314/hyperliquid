from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from hyperliquid.storage.db import get_system_state, set_system_state


@dataclass(frozen=True)
class SafetyState:
    mode: str
    reason_code: str
    reason_message: str
    changed_at_ms: int


def load_safety_state(conn) -> Optional[SafetyState]:
    mode = get_system_state(conn, "safety_mode")
    if mode is None:
        return None
    reason_code = get_system_state(conn, "safety_reason_code") or ""
    reason_message = get_system_state(conn, "safety_reason_message") or ""
    changed_at_raw = get_system_state(conn, "safety_changed_at_ms") or "0"
    return SafetyState(
        mode=mode,
        reason_code=reason_code,
        reason_message=reason_message,
        changed_at_ms=int(changed_at_raw),
    )


def set_safety_state(
    conn,
    *,
    mode: str,
    reason_code: str,
    reason_message: str,
    commit: bool = True,
) -> None:
    now_ms = int(time.time() * 1000)
    set_system_state(conn, "safety_mode", mode, commit=False)
    set_system_state(conn, "safety_reason_code", reason_code, commit=False)
    set_system_state(conn, "safety_reason_message", reason_message, commit=False)
    set_system_state(conn, "safety_changed_at_ms", str(now_ms), commit=False)
    if commit:
        conn.commit()
