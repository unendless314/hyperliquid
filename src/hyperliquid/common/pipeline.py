from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional

from hyperliquid.common.models import OrderIntent, OrderResult, PositionDeltaEvent
from hyperliquid.decision.service import DecisionService
from hyperliquid.decision.types import DecisionInputs
from hyperliquid.execution.service import ExecutionService
from hyperliquid.storage.persistence import Persistence


@dataclass
class Pipeline:
    decision: DecisionService
    execution: ExecutionService
    decision_inputs_provider: Optional[Callable[[PositionDeltaEvent], DecisionInputs]] = None
    persistence: Optional[Persistence] = None

    def process_events(self, events: Iterable[PositionDeltaEvent]) -> List[OrderResult]:
        results: List[OrderResult] = []
        for event in events:
            inputs = None
            if self.decision_inputs_provider is not None:
                inputs = self.decision_inputs_provider(event)
            intents = self.decision.decide(event, inputs)
            for intent in intents:
                if self.persistence is not None:
                    ensure_intent = getattr(self.persistence, "ensure_intent", None)
                    if callable(ensure_intent):
                        intent = ensure_intent(intent)
                    else:
                        record_intent = getattr(self.persistence, "record_intent", None)
                        if callable(record_intent):
                            record_intent(intent)
                results.append(self.execution.execute(intent))
                if self.persistence is not None:
                    record_result = getattr(self.persistence, "record_result", None)
                    if callable(record_result):
                        record_result(results[-1])
        return results

    def process_single_event(self, event: PositionDeltaEvent) -> List[OrderResult]:
        return self.process_events([event])
