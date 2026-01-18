from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Optional, Protocol

import sqlite3

from hyperliquid.common.idempotency import (
    build_client_order_id,
    generate_nonce,
    sanitize_client_order_id,
)
from hyperliquid.common.models import OrderIntent, OrderResult


class Persistence(Protocol):
    def ensure_intent(self, intent: OrderIntent) -> OrderIntent:
        ...

    def record_intent(self, intent: OrderIntent) -> None:
        ...

    def get_order_result(self, correlation_id: str) -> Optional[OrderResult]:
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

    def get_intent(self, correlation_id: str) -> Optional[OrderIntent]:
        row = self.conn.execute(
            "SELECT intent_payload FROM order_intents WHERE correlation_id = ?",
            (correlation_id,),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        payload.setdefault("client_order_id", None)
        return OrderIntent(**payload)

    def ensure_intent(self, intent: OrderIntent) -> OrderIntent:
        existing = self.get_intent(intent.correlation_id)
        if existing:
            if not _intent_equivalent(existing, intent):
                raise ValueError(
                    "Intent payload mismatch for correlation_id="
                    f"{intent.correlation_id}"
                )
            if existing.client_order_id:
                return existing
            client_order_id = intent.client_order_id
            if client_order_id:
                client_order_id = sanitize_client_order_id(client_order_id)
            else:
                nonce = generate_nonce()
                client_order_id = build_client_order_id(
                    correlation_id=intent.correlation_id,
                    symbol=intent.symbol,
                    nonce=nonce,
                )
            existing.client_order_id = client_order_id
            self._update_intent_payload(existing)
            return existing

        if intent.client_order_id:
            intent.client_order_id = sanitize_client_order_id(intent.client_order_id)
            self.record_intent(intent)
            return intent

        nonce = generate_nonce()
        intent.client_order_id = build_client_order_id(
            correlation_id=intent.correlation_id,
            symbol=intent.symbol,
            nonce=nonce,
        )
        self.record_intent(intent)
        return intent

    def record_result(self, result: OrderResult) -> None:
        self.conn.execute(
            "INSERT INTO order_results("
            "correlation_id, exchange_order_id, status, filled_qty, avg_price, error_code, "
            "error_message, contract_version, created_at_ms, updated_at_ms"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(correlation_id) DO UPDATE SET "
            "exchange_order_id=excluded.exchange_order_id, "
            "status=excluded.status, "
            "filled_qty=excluded.filled_qty, "
            "avg_price=excluded.avg_price, "
            "error_code=excluded.error_code, "
            "error_message=excluded.error_message, "
            "contract_version=excluded.contract_version, "
            "updated_at_ms=excluded.updated_at_ms",
            (
                result.correlation_id,
                result.exchange_order_id,
                result.status,
                result.filled_qty,
                result.avg_price,
                result.error_code,
                result.error_message,
                result.contract_version,
                self._now_ms(),
                self._now_ms(),
            ),
        )
        self.conn.commit()

    def get_order_result(self, correlation_id: str) -> Optional[OrderResult]:
        row = self.conn.execute(
            "SELECT correlation_id, exchange_order_id, status, filled_qty, avg_price, "
            "error_code, error_message, contract_version FROM order_results "
            "WHERE correlation_id = ?",
            (correlation_id,),
        ).fetchone()
        if row is None:
            return None
        return OrderResult(
            correlation_id=row[0],
            exchange_order_id=row[1],
            status=row[2],
            filled_qty=row[3],
            avg_price=row[4],
            error_code=row[5],
            error_message=row[6],
            contract_version=row[7],
        )

    def _update_intent_payload(self, intent: OrderIntent) -> None:
        payload = json.dumps(asdict(intent), ensure_ascii=True)
        self.conn.execute(
            "UPDATE order_intents SET intent_payload = ? WHERE correlation_id = ?",
            (payload, intent.correlation_id),
        )
        self.conn.commit()


@dataclass
class NoopPersistence:
    _client_order_ids: dict[str, str] = field(default_factory=dict, init=False)

    def ensure_intent(self, intent: OrderIntent) -> OrderIntent:
        existing = self._client_order_ids.get(intent.correlation_id)
        if existing:
            intent.client_order_id = existing
        else:
            if not intent.client_order_id:
                nonce = generate_nonce()
                intent.client_order_id = build_client_order_id(
                    correlation_id=intent.correlation_id,
                    symbol=intent.symbol,
                    nonce=nonce,
                )
            intent.client_order_id = sanitize_client_order_id(intent.client_order_id)
            self._client_order_ids[intent.correlation_id] = intent.client_order_id
        return intent

    def record_intent(self, intent: OrderIntent) -> None:
        _ = intent

    def get_order_result(self, correlation_id: str) -> Optional[OrderResult]:
        _ = correlation_id
        return None

    def record_result(self, result: OrderResult) -> None:
        _ = result


def _intent_equivalent(left: OrderIntent, right: OrderIntent) -> bool:
    return (
        left.correlation_id == right.correlation_id
        and left.symbol == right.symbol
        and left.side == right.side
        and left.order_type == right.order_type
        and left.qty == right.qty
        and left.price == right.price
        and left.reduce_only == right.reduce_only
        and left.time_in_force == right.time_in_force
        and left.is_replay == right.is_replay
        and left.risk_notes == right.risk_notes
        and left.contract_version == right.contract_version
    )
