from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from hyperliquid.common.models import OrderIntent, OrderResult
from hyperliquid.execution.service import ExecutionService


@dataclass
class _AdapterStub:
    calls: int = 0

    def execute(self, intent: OrderIntent) -> OrderResult:
        self.calls += 1
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id="ex-1",
            status="SUBMITTED",
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
