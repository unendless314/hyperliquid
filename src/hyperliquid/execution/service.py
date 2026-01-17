from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List

from hyperliquid.common.models import OrderIntent, OrderResult, assert_contract_version


PreExecutionHook = Callable[[OrderIntent], None]
PostExecutionHook = Callable[[OrderIntent, OrderResult], None]


@dataclass
class ExecutionService:
    pre_hooks: List[PreExecutionHook] = field(default_factory=list)
    post_hooks: List[PostExecutionHook] = field(default_factory=list)

    def execute(self, intent: OrderIntent) -> OrderResult:
        assert_contract_version(intent.contract_version)
        try:
            for hook in self.pre_hooks:
                hook(intent)
        except Exception as exc:
            result = OrderResult(
                correlation_id=intent.correlation_id,
                exchange_order_id=None,
                status="REJECTED",
                filled_qty=0.0,
                avg_price=None,
                error_code="SAFETY_REJECTED",
                error_message=str(exc),
            )
            for hook in self.post_hooks:
                hook(intent, result)
            return result

        result = OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id=None,
            status="SUBMITTED",
            filled_qty=0.0,
            avg_price=None,
            error_code=None,
            error_message=None,
        )
        for hook in self.post_hooks:
            hook(intent, result)
        return result
