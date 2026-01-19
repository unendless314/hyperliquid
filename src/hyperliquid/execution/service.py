from __future__ import annotations

import time
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
SafetyStateUpdater = Callable[[str, str, str], None]


@dataclass(frozen=True)
class ExecutionServiceConfig:
    tif_seconds: int
    order_poll_interval_sec: int
    retry_budget_max_attempts: int
    retry_budget_window_sec: int
    unknown_poll_interval_sec: int
    retry_budget_mode: str

    @staticmethod
    def from_settings(raw: dict) -> "ExecutionServiceConfig":
        execution = raw.get("execution", {})
        return ExecutionServiceConfig(
            tif_seconds=int(execution.get("tif_seconds", 0)),
            order_poll_interval_sec=int(execution.get("order_poll_interval_sec", 2)),
            retry_budget_max_attempts=int(execution.get("retry_budget_max_attempts", 3)),
            retry_budget_window_sec=int(execution.get("retry_budget_window_sec", 30)),
            unknown_poll_interval_sec=int(execution.get("unknown_poll_interval_sec", 2)),
            retry_budget_mode=str(execution.get("retry_budget_mode", "ARMED_SAFE")),
        )


@dataclass
class ExecutionService:
    config: ExecutionServiceConfig = field(
        default_factory=lambda: ExecutionServiceConfig(0, 2, 3, 30, 2, "ARMED_SAFE")
    )
    pre_hooks: List[PreExecutionHook] = field(default_factory=list)
    post_hooks: List[PostExecutionHook] = field(default_factory=list)
    adapter: BinanceExecutionAdapter | None = None
    result_provider: Optional[ResultProvider] = None
    safety_state_updater: Optional[SafetyStateUpdater] = None

    def execute(self, intent: OrderIntent) -> OrderResult:
        assert_contract_version(intent.contract_version)
        existing = None
        if self.result_provider is not None:
            existing = self.result_provider(intent.correlation_id)
        if existing is not None:
            assert_contract_version(existing.contract_version)
            if existing.status == "UNKNOWN" and self.adapter is not None:
                return self._resolve_unknown(intent, existing)
            if existing.status in ("FILLED", "SUBMITTED"):
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
        if (
            intent.order_type == "LIMIT"
            and self.adapter is not None
            and result.status in ("SUBMITTED", "PARTIALLY_FILLED")
        ):
            result = self._handle_limit_tif(intent, result)
        if result.status == "UNKNOWN" and self.adapter is not None:
            result = self._resolve_unknown(intent, result)
        for hook in self.post_hooks:
            hook(intent, result)
        assert_contract_version(result.contract_version)
        return result

    def _handle_limit_tif(self, intent: OrderIntent, result: OrderResult) -> OrderResult:
        tif_seconds = max(self.config.tif_seconds, 0)
        poll_interval = max(self.config.order_poll_interval_sec, 1)
        if tif_seconds == 0:
            return result
        adapter = self.adapter
        if adapter is None:
            return result
        if not hasattr(adapter, "query_order") or not hasattr(adapter, "cancel_order"):
            return result
        deadline = time.time() + tif_seconds
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            time.sleep(min(poll_interval, remaining))
            try:
                current = adapter.query_order(intent)
            except Exception as exc:
                return OrderResult(
                    correlation_id=intent.correlation_id,
                    exchange_order_id=result.exchange_order_id,
                    status="UNKNOWN",
                    filled_qty=result.filled_qty,
                    avg_price=result.avg_price,
                    error_code="EXECUTION_ERROR",
                    error_message=str(exc),
                )
            if _is_terminal_status(current.status):
                return current
        try:
            cancel_result = adapter.cancel_order(intent)
        except Exception as exc:
            return OrderResult(
                correlation_id=intent.correlation_id,
                exchange_order_id=result.exchange_order_id,
                status="UNKNOWN",
                filled_qty=result.filled_qty,
                avg_price=result.avg_price,
                error_code="EXECUTION_ERROR",
                error_message=str(exc),
            )
        if _is_terminal_status(cancel_result.status):
            return cancel_result
        try:
            return adapter.query_order(intent)
        except Exception as exc:
            return OrderResult(
                correlation_id=intent.correlation_id,
                exchange_order_id=result.exchange_order_id,
                status="UNKNOWN",
                filled_qty=result.filled_qty,
                avg_price=result.avg_price,
                error_code="EXECUTION_ERROR",
                error_message=str(exc),
            )

    def _resolve_unknown(self, intent: OrderIntent, result: OrderResult) -> OrderResult:
        adapter = self.adapter
        if adapter is None or not hasattr(adapter, "query_order"):
            return result
        max_attempts = max(self.config.retry_budget_max_attempts, 0)
        window_sec = max(self.config.retry_budget_window_sec, 0)
        poll_interval = max(self.config.unknown_poll_interval_sec, 1)
        if max_attempts == 0 or window_sec == 0:
            return result
        deadline = time.time() + window_sec
        attempts = 0
        last_error = result.error_message or "unknown"
        while attempts < max_attempts and time.time() < deadline:
            attempts += 1
            try:
                current = adapter.query_order(intent)
            except Exception as exc:
                last_error = str(exc)
            else:
                if _is_terminal_status(current.status, include_unknown=False):
                    return current
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            time.sleep(min(poll_interval, remaining))
        if self.safety_state_updater is not None:
            mode = self.config.retry_budget_mode.upper()
            if mode not in ("ARMED_SAFE", "HALT"):
                mode = "ARMED_SAFE"
            self.safety_state_updater(
                mode,
                "EXECUTION_RETRY_BUDGET_EXCEEDED",
                "Execution retry budget exceeded; requires operator review",
            )
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id=result.exchange_order_id,
            status="UNKNOWN",
            filled_qty=result.filled_qty,
            avg_price=result.avg_price,
            error_code="RETRY_BUDGET_EXCEEDED",
            error_message=last_error,
        )


def _is_terminal_status(status: str, *, include_unknown: bool = True) -> bool:
    if include_unknown:
        return status in ("FILLED", "CANCELED", "EXPIRED", "REJECTED", "UNKNOWN")
    return status in ("FILLED", "CANCELED", "EXPIRED", "REJECTED")
