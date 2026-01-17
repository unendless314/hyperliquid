from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from hyperliquid.common.models import OrderIntent, OrderResult


@dataclass
class InMemoryPersistence:
    intents: List[OrderIntent] = field(default_factory=list)
    results: List[OrderResult] = field(default_factory=list)

    def record_intent(self, intent: OrderIntent) -> None:
        self.intents.append(intent)

    def record_result(self, result: OrderResult) -> None:
        self.results.append(result)
