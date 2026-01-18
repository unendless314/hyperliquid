from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from hyperliquid.common.idempotency import (
    build_client_order_id,
    generate_nonce,
    sanitize_client_order_id,
)
from hyperliquid.common.models import OrderIntent, OrderResult


@dataclass
class InMemoryPersistence:
    intents: List[OrderIntent] = field(default_factory=list)
    results: List[OrderResult] = field(default_factory=list)
    _client_order_ids: dict[str, str] = field(default_factory=dict, init=False)
    _result_index: dict[str, int] = field(default_factory=dict, init=False)

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
        self.record_intent(intent)
        return intent

    def record_intent(self, intent: OrderIntent) -> None:
        self.intents.append(intent)

    def record_result(self, result: OrderResult) -> None:
        existing_index = self._result_index.get(result.correlation_id)
        if existing_index is not None:
            self.results[existing_index] = result
            return
        self._result_index[result.correlation_id] = len(self.results)
        self.results.append(result)

    def get_order_result(self, correlation_id: str) -> OrderResult | None:
        index = self._result_index.get(correlation_id)
        if index is None:
            return None
        return self.results[index]
