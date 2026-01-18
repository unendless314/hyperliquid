from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from hyperliquid.common.models import OrderIntent, OrderResult, assert_contract_version
from hyperliquid.execution.adapters.binance import (
    AdapterNotImplementedError,
    BinanceExecutionAdapter,
)


PreExecutionHook = Callable[[OrderIntent], None]
PostExecutionHook = Callable[[OrderIntent, OrderResult], None]
ResultProvider = Callable[[str], Optional[OrderResult]]


@dataclass
class ExecutionService:
    pre_hooks: List[PreExecutionHook] = field(default_factory=list)
    post_hooks: List[PostExecutionHook] = field(default_factory=list)
    adapter: BinanceExecutionAdapter | None = None
    result_provider: Optional[ResultProvider] = None

    def execute(self, intent: OrderIntent) -> OrderResult:
        assert_contract_version(intent.contract_version)
        existing = None
        if self.result_provider is not None:
            existing = self.result_provider(intent.correlation_id)
        if existing is not None:
            assert_contract_version(existing.contract_version)
            if existing.status in ("FILLED", "SUBMITTED", "UNKNOWN"):
                return existing
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
            assert_contract_version(result.contract_version)
            return result

        if self.adapter is not None:
            try:
                result = self.adapter.execute(intent)
            except AdapterNotImplementedError:
                raise
            except Exception as exc:
                result = OrderResult(
                    correlation_id=intent.correlation_id,
                    exchange_order_id=None,
                    status="UNKNOWN",
                    filled_qty=0.0,
                    avg_price=None,
                    error_code="EXECUTION_ERROR",
                    error_message=str(exc),
                )
        else:
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
        assert_contract_version(result.contract_version)
        return result
