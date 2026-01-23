from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from hyperliquid.common.idempotency import build_client_order_id, generate_nonce
from hyperliquid.common.models import OrderIntent, OrderResult, assert_contract_version
from hyperliquid.execution.adapters.binance import (
    AdapterNotImplementedError,
    BinanceExecutionAdapter,
)
from hyperliquid.storage.persistence import AuditLogEntry


PreExecutionHook = Callable[[OrderIntent], None]
PostExecutionHook = Callable[[OrderIntent, OrderResult], None]
ResultProvider = Callable[[str], Optional[OrderResult]]
SafetyStateUpdater = Callable[[str, str, str], None]
AuditRecorder = Callable[[AuditLogEntry], None]


@dataclass(frozen=True)
class ExecutionServiceConfig:
    tif_seconds: int = 0
    order_poll_interval_sec: int = 2
    retry_budget_max_attempts: int = 3
    retry_budget_window_sec: int = 30
    unknown_poll_interval_sec: int = 2
    retry_budget_mode: str = "ARMED_SAFE"
    market_fallback_enabled: bool = False
    market_fallback_threshold_pct: float = 0.1
    market_slippage_cap_pct: float = 0.005

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
            market_fallback_enabled=bool(execution.get("market_fallback_enabled", False)),
            market_fallback_threshold_pct=float(
                execution.get("market_fallback_threshold_pct", 0.1)
            ),
            market_slippage_cap_pct=float(
                execution.get("market_slippage_cap_pct", 0.005)
            ),
        )


@dataclass
class ExecutionService:
    config: ExecutionServiceConfig = field(default_factory=ExecutionServiceConfig)
    pre_hooks: List[PreExecutionHook] = field(default_factory=list)
    post_hooks: List[PostExecutionHook] = field(default_factory=list)
    adapter: BinanceExecutionAdapter | None = None
    result_provider: Optional[ResultProvider] = None
    safety_state_updater: Optional[SafetyStateUpdater] = None
    audit_recorder: Optional[AuditRecorder] = None

    def execute(self, intent: OrderIntent) -> OrderResult:
        assert_contract_version(intent.contract_version)
        existing = None
        if self.result_provider is not None:
            existing = self.result_provider(intent.correlation_id)
        if existing is not None:
            assert_contract_version(existing.contract_version)
            if existing.status == "UNKNOWN" and self.adapter is not None:
                resolved = self._resolve_unknown(intent, existing)
                self._record_transition(intent, existing.status, resolved)
                return resolved
            if existing.status in ("FILLED", "SUBMITTED"):
                return existing
            last_status = existing.status
        else:
            last_status = "NONE"
        try:
            for hook in self.pre_hooks:
                hook(intent)
        except Exception as exc:
            result = self._reject_from_hook(intent, exc)
            self._record_transition(intent, last_status, result)
            for hook in self.post_hooks:
                hook(intent, result)
            assert_contract_version(result.contract_version)
            return result

        result = self._execute_adapter(intent)
        self._record_transition(intent, last_status, result)
        last_status = result.status
        if (
            intent.order_type == "LIMIT"
            and self.adapter is not None
            and result.status in ("SUBMITTED", "PARTIALLY_FILLED")
        ):
            result = self._handle_limit_tif(intent, result)
            self._record_transition(intent, last_status, result)
            last_status = result.status
            result = self._maybe_market_fallback(intent, result)
            self._record_transition(intent, last_status, result)
            last_status = result.status
        if result.status == "UNKNOWN" and self.adapter is not None:
            result = self._resolve_unknown(intent, result)
            self._record_transition(intent, last_status, result)
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

    def _maybe_market_fallback(self, intent: OrderIntent, result: OrderResult) -> OrderResult:
        if not self.config.market_fallback_enabled:
            return result
        if intent.order_type != "LIMIT":
            return result
        if result.status not in ("CANCELED", "EXPIRED"):
            return result
        if result.filled_qty >= intent.qty:
            return result
        remaining_qty = intent.qty - result.filled_qty
        if remaining_qty <= 0:
            return result
        remaining_ratio = remaining_qty / max(intent.qty, 1e-9)
        threshold = max(self.config.market_fallback_threshold_pct, 0.0)
        if remaining_ratio > threshold:
            return result
        adapter = self.adapter
        if adapter is None:
            return result
        try:
            mark_price = adapter.fetch_mark_price(intent.symbol)
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
        slippage_cap = max(self.config.market_slippage_cap_pct, 0.0)
        if intent.price is not None and mark_price > 0:
            slippage = abs(float(mark_price) - intent.price) / max(intent.price, 1e-9)
            if slippage > slippage_cap:
                return OrderResult(
                    correlation_id=intent.correlation_id,
                    exchange_order_id=result.exchange_order_id,
                    status="REJECTED",
                    filled_qty=result.filled_qty,
                    avg_price=result.avg_price,
                    error_code="SLIPPAGE_EXCEEDED",
                    error_message="Fallback slippage exceeds cap",
                )
        fallback_intent = OrderIntent(
            correlation_id=intent.correlation_id,
            client_order_id=build_client_order_id(
                correlation_id=intent.correlation_id,
                symbol=intent.symbol,
                nonce=generate_nonce(),
            ),
            strategy_version=intent.strategy_version,
            symbol=intent.symbol,
            side=intent.side,
            order_type="MARKET",
            qty=remaining_qty,
            price=None,
            reduce_only=intent.reduce_only,
            time_in_force="IOC",
            is_replay=intent.is_replay,
            risk_notes=intent.risk_notes,
        )
        try:
            for hook in self.pre_hooks:
                hook(fallback_intent)
        except Exception as exc:
            return self._reject_from_hook(fallback_intent, exc)
        fallback_result = self._execute_adapter(fallback_intent)
        return self._merge_fallback_result(result, fallback_result)

    def _reject_from_hook(self, intent: OrderIntent, exc: Exception) -> OrderResult:
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id=None,
            status="REJECTED",
            filled_qty=0.0,
            avg_price=None,
            error_code="SAFETY_REJECTED",
            error_message=str(exc),
        )

    def _execute_adapter(self, intent: OrderIntent) -> OrderResult:
        if self.adapter is not None:
            try:
                return self.adapter.execute(intent)
            except AdapterNotImplementedError:
                raise
            except Exception as exc:
                return OrderResult(
                    correlation_id=intent.correlation_id,
                    exchange_order_id=None,
                    status="UNKNOWN",
                    filled_qty=0.0,
                    avg_price=None,
                    error_code="EXECUTION_ERROR",
                    error_message=str(exc),
                )
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id=None,
            status="SUBMITTED",
            filled_qty=0.0,
            avg_price=None,
            error_code=None,
            error_message=None,
        )

    @staticmethod
    def _merge_fallback_result(
        base_result: OrderResult, fallback_result: OrderResult
    ) -> OrderResult:
        combined_qty = max(0.0, float(base_result.filled_qty) + float(fallback_result.filled_qty))
        avg_price = fallback_result.avg_price
        if fallback_result.avg_price is None:
            avg_price = base_result.avg_price
        elif base_result.filled_qty > 0 and base_result.avg_price is not None:
            if combined_qty > 0:
                avg_price = (
                    (base_result.filled_qty * base_result.avg_price)
                    + (fallback_result.filled_qty * fallback_result.avg_price)
                ) / combined_qty
        return OrderResult(
            correlation_id=fallback_result.correlation_id,
            exchange_order_id=fallback_result.exchange_order_id,
            status=fallback_result.status,
            filled_qty=combined_qty,
            avg_price=avg_price,
            error_code=fallback_result.error_code,
            error_message="fallback_from_limit",
            contract_version=fallback_result.contract_version,
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

    def _record_transition(
        self, intent: OrderIntent, from_state: str, result: OrderResult
    ) -> None:
        if self.audit_recorder is None:
            return
        if from_state == result.status:
            return
        try:
            self.audit_recorder(
                AuditLogEntry(
                    timestamp_ms=int(time.time() * 1000),
                    category="execution",
                    entity_id=intent.correlation_id,
                    from_state=from_state,
                    to_state=result.status,
                    reason_code=result.error_code or "",
                    reason_message=result.error_message or "",
                    event_id="",
                    metadata={
                        "symbol": intent.symbol,
                        "side": intent.side,
                        "order_type": intent.order_type,
                        "qty": intent.qty,
                        "exchange_order_id": result.exchange_order_id,
                    },
                )
            )
        except Exception:
            return None


def _is_terminal_status(status: str, *, include_unknown: bool = True) -> bool:
    if include_unknown:
        return status in ("FILLED", "CANCELED", "EXPIRED", "REJECTED", "UNKNOWN")
    return status in ("FILLED", "CANCELED", "EXPIRED", "REJECTED")
