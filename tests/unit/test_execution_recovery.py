from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from hyperliquid.common.models import OrderIntent, OrderResult
from hyperliquid.execution.service import ExecutionService, ExecutionServiceConfig


@dataclass
class _AdapterStub:
    calls: int = 0
    query_calls: int = 0
    cancel_calls: int = 0
    execute_status: str = "SUBMITTED"
    query_status: str = "SUBMITTED"

    def execute(self, intent: OrderIntent) -> OrderResult:
        self.calls += 1
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id="ex-1",
            status=self.execute_status,
            filled_qty=0.0,
            avg_price=None,
            error_code=None,
            error_message=None,
        )

    def query_order(self, intent: OrderIntent) -> OrderResult:
        self.query_calls += 1
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id="ex-1",
            status=self.query_status,
            filled_qty=0.0,
            avg_price=None,
            error_code=None,
            error_message=None,
        )

    def cancel_order(self, intent: OrderIntent) -> OrderResult:
        self.cancel_calls += 1
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id="ex-1",
            status="CANCELED",
            filled_qty=0.0,
            avg_price=None,
            error_code=None,
            error_message=None,
        )


def _intent() -> OrderIntent:
    return OrderIntent(
        correlation_id="hl-abc-6-BTCUSDT",
        client_order_id="hl-abc-6-BTCUSDT-deadbeef",
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        qty=1.0,
        price=None,
        reduce_only=0,
        time_in_force="IOC",
        is_replay=0,
        risk_notes=None,
    )


def test_execution_recovery_skips_filled() -> None:
    adapter = _AdapterStub()

    def provider(_: str) -> Optional[OrderResult]:
        return OrderResult(
            correlation_id="hl-abc-6-BTCUSDT",
            exchange_order_id="ex-1",
            status="FILLED",
            filled_qty=1.0,
            avg_price=100.0,
            error_code=None,
            error_message=None,
        )

    service = ExecutionService(adapter=adapter, result_provider=provider)
    result = service.execute(_intent())

    assert result.status == "FILLED"
    assert adapter.calls == 0


def test_execution_recovery_returns_submitted_without_adapter() -> None:
    adapter = _AdapterStub()

    def provider(_: str) -> Optional[OrderResult]:
        return OrderResult(
            correlation_id="hl-abc-6-BTCUSDT",
            exchange_order_id="ex-1",
            status="SUBMITTED",
            filled_qty=0.0,
            avg_price=None,
            error_code=None,
            error_message=None,
        )

    service = ExecutionService(adapter=adapter, result_provider=provider)
    result = service.execute(_intent())

    assert result.status == "SUBMITTED"
    assert adapter.calls == 0


def test_execution_recovery_returns_unknown_without_adapter() -> None:
    adapter = _AdapterStub()

    def provider(_: str) -> Optional[OrderResult]:
        return OrderResult(
            correlation_id="hl-abc-6-BTCUSDT",
            exchange_order_id="ex-1",
            status="UNKNOWN",
            filled_qty=0.0,
            avg_price=None,
            error_code="EXECUTION_ERROR",
            error_message="timeout",
        )

    service = ExecutionService(adapter=adapter, result_provider=provider)
    result = service.execute(_intent())

    assert result.status == "UNKNOWN"
    assert adapter.calls == 0


def test_execution_recovery_unknown_resolves_when_adapter_present() -> None:
    adapter = _AdapterStub()

    def provider(_: str) -> Optional[OrderResult]:
        return OrderResult(
            correlation_id="hl-abc-6-BTCUSDT",
            exchange_order_id="ex-1",
            status="UNKNOWN",
            filled_qty=0.0,
            avg_price=None,
            error_code="EXECUTION_ERROR",
            error_message="timeout",
        )

    service = ExecutionService(
        adapter=adapter,
        result_provider=provider,
        config=ExecutionServiceConfig(
            tif_seconds=0,
            order_poll_interval_sec=1,
            retry_budget_max_attempts=1,
            retry_budget_window_sec=1,
            unknown_poll_interval_sec=1,
            retry_budget_mode="ARMED_SAFE",
        ),
    )
    result = service.execute(_intent())
    assert result.status in ("SUBMITTED", "FILLED", "CANCELED", "EXPIRED", "REJECTED", "UNKNOWN")
    assert adapter.query_calls == 1


def test_execution_recovery_does_not_run_post_hooks() -> None:
    adapter = _AdapterStub()
    hook_calls = {"count": 0}

    def post_hook(_: OrderIntent, __: OrderResult) -> None:
        hook_calls["count"] += 1

    def provider(_: str) -> Optional[OrderResult]:
        return OrderResult(
            correlation_id="hl-abc-6-BTCUSDT",
            exchange_order_id="ex-1",
            status="FILLED",
            filled_qty=1.0,
            avg_price=100.0,
            error_code=None,
            error_message=None,
        )

    service = ExecutionService(
        adapter=adapter, result_provider=provider, post_hooks=[post_hook]
    )
    result = service.execute(_intent())

    assert result.status == "FILLED"
    assert adapter.calls == 0
    assert hook_calls["count"] == 0


def test_execution_recovery_allows_new_when_missing_result() -> None:
    adapter = _AdapterStub()

    def provider(_: str) -> Optional[OrderResult]:
        return None

    service = ExecutionService(adapter=adapter, result_provider=provider)
    result = service.execute(_intent())

    assert result.status == "SUBMITTED"
    assert adapter.calls == 1


def test_limit_order_tif_cancel_flow() -> None:
    adapter = _AdapterStub()
    intent = OrderIntent(
        correlation_id="hl-abc-7-BTCUSDT",
        client_order_id="hl-abc-7-BTCUSDT-deadbeef",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        qty=1.0,
        price=100.0,
        reduce_only=0,
        time_in_force="GTC",
        is_replay=0,
        risk_notes=None,
    )
    service = ExecutionService(
        adapter=adapter,
        result_provider=lambda _: None,
        config=ExecutionServiceConfig(
            tif_seconds=1,
            order_poll_interval_sec=1,
            retry_budget_max_attempts=1,
            retry_budget_window_sec=1,
            unknown_poll_interval_sec=1,
            retry_budget_mode="ARMED_SAFE",
        ),
    )
    result = service.execute(intent)
    assert result.status in ("CANCELED", "UNKNOWN")
    assert adapter.calls == 1
    assert adapter.cancel_calls == 1
    assert adapter.query_calls >= 1


def test_unknown_resolves_via_query() -> None:
    adapter = _AdapterStub(execute_status="UNKNOWN", query_status="FILLED")
    intent = OrderIntent(
        correlation_id="hl-abc-8-BTCUSDT",
        client_order_id="hl-abc-8-BTCUSDT-deadbeef",
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        qty=1.0,
        price=None,
        reduce_only=0,
        time_in_force="IOC",
        is_replay=0,
        risk_notes=None,
    )
    service = ExecutionService(
        adapter=adapter,
        result_provider=lambda _: None,
        config=ExecutionServiceConfig(
            tif_seconds=0,
            order_poll_interval_sec=1,
            retry_budget_max_attempts=1,
            retry_budget_window_sec=1,
            unknown_poll_interval_sec=1,
            retry_budget_mode="ARMED_SAFE",
        ),
    )
    result = service.execute(intent)
    assert result.status == "FILLED"
    assert adapter.query_calls == 1


def test_unknown_retry_budget_exceeded_updates_safety() -> None:
    adapter = _AdapterStub(execute_status="UNKNOWN", query_status="UNKNOWN")
    intent = OrderIntent(
        correlation_id="hl-abc-9-BTCUSDT",
        client_order_id="hl-abc-9-BTCUSDT-deadbeef",
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        qty=1.0,
        price=None,
        reduce_only=0,
        time_in_force="IOC",
        is_replay=0,
        risk_notes=None,
    )
    called = {"mode": None, "reason_code": None}

    def updater(mode: str, reason_code: str, reason_message: str) -> None:
        called["mode"] = mode
        called["reason_code"] = reason_code

    service = ExecutionService(
        adapter=adapter,
        result_provider=lambda _: None,
        config=ExecutionServiceConfig(
            tif_seconds=0,
            order_poll_interval_sec=1,
            retry_budget_max_attempts=1,
            retry_budget_window_sec=1,
            unknown_poll_interval_sec=1,
            retry_budget_mode="HALT",
        ),
        safety_state_updater=updater,
    )
    result = service.execute(intent)
    assert result.status == "UNKNOWN"
    assert result.error_code == "RETRY_BUDGET_EXCEEDED"
    assert called["mode"] == "HALT"
    assert called["reason_code"] == "EXECUTION_RETRY_BUDGET_EXCEEDED"
