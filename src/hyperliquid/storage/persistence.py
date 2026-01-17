from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Protocol

import sqlite3

from hyperliquid.common.models import OrderIntent, OrderResult


class Persistence(Protocol):
    def record_intent(self, intent: OrderIntent) -> None:
        ...

    def record_result(self, result: OrderResult) -> None:
        ...


@dataclass
class DbPersistence:
    conn: sqlite3.Connection

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    def record_intent(self, intent: OrderIntent) -> None:
        payload = json.dumps(asdict(intent), ensure_ascii=True)
        self.conn.execute(
            "INSERT OR IGNORE INTO order_intents(correlation_id, intent_payload, created_at_ms) "
            "VALUES(?, ?, ?)",
            (intent.correlation_id, payload, self._now_ms()),
        )
        self.conn.commit()

    def record_result(self, result: OrderResult) -> None:
        self.conn.execute(
            "INSERT INTO order_results("
            "correlation_id, exchange_order_id, status, filled_qty, avg_price, error_code, "
            "error_message, created_at_ms, updated_at_ms"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(correlation_id) DO UPDATE SET "
            "exchange_order_id=excluded.exchange_order_id, "
            "status=excluded.status, "
            "filled_qty=excluded.filled_qty, "
            "avg_price=excluded.avg_price, "
            "error_code=excluded.error_code, "
            "error_message=excluded.error_message, "
            "updated_at_ms=excluded.updated_at_ms",
            (
                result.correlation_id,
                result.exchange_order_id,
                result.status,
                result.filled_qty,
                result.avg_price,
                result.error_code,
                result.error_message,
                self._now_ms(),
                self._now_ms(),
            ),
        )
        self.conn.commit()


@dataclass
class NoopPersistence:
    def record_intent(self, intent: OrderIntent) -> None:
        _ = intent

    def record_result(self, result: OrderResult) -> None:
        _ = result
