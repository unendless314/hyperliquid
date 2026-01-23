from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from hyperliquid.common.models import OrderIntent, OrderResult
from hyperliquid.execution.service import ExecutionService, ExecutionServiceConfig


@dataclass
class _AdapterStub:
    query_calls: int = 0

    def execute(self, intent: OrderIntent) -> OrderResult:
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id="ex-1",
            status="SUBMITTED",
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
            status="UNKNOWN",
            filled_qty=0.0,
            avg_price=None,
            error_code="EXECUTION_ERROR",
            error_message="timeout",
        )


def _intent() -> OrderIntent:
    return OrderIntent(
        correlation_id="hl-unk-1-BTCUSDT",
        client_order_id="hl-unk-1-BTCUSDT-deadbeef",
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


def test_unknown_recovery_skips_when_budget_disabled() -> None:
    adapter = _AdapterStub()

    def provider(_: str) -> Optional[OrderResult]:
        return OrderResult(
            correlation_id="hl-unk-1-BTCUSDT",
            exchange_order_id="ex-1",
            status="UNKNOWN",
            filled_qty=0.0,
            avg_price=None,
            error_code="EXECUTION_ERROR",
            error_message="timeout",
        )

    called = {"count": 0}

    def updater(*_args) -> None:
        called["count"] += 1

    service = ExecutionService(
        adapter=adapter,
        result_provider=provider,
        safety_state_updater=updater,
        config=ExecutionServiceConfig(
            retry_budget_max_attempts=0,
            retry_budget_window_sec=0,
        ),
    )
    result = service.execute(_intent())
    assert result.status == "UNKNOWN"
    assert adapter.query_calls == 0
    assert called["count"] == 0


def test_unknown_recovery_exceeds_budget_sets_safety(monkeypatch) -> None:
    adapter = _AdapterStub()

    def provider(_: str) -> Optional[OrderResult]:
        return OrderResult(
            correlation_id="hl-unk-1-BTCUSDT",
            exchange_order_id="ex-1",
            status="UNKNOWN",
            filled_qty=0.0,
            avg_price=None,
            error_code="EXECUTION_ERROR",
            error_message="timeout",
        )

    called = {"mode": None, "reason_code": None}

    def updater(mode: str, reason_code: str, _msg: str) -> None:
        called["mode"] = mode
        called["reason_code"] = reason_code

    monkeypatch.setattr("hyperliquid.execution.service.time.time", lambda: 0.0)
    monkeypatch.setattr("hyperliquid.execution.service.time.sleep", lambda _sec: None)

    service = ExecutionService(
        adapter=adapter,
        result_provider=provider,
        safety_state_updater=updater,
        config=ExecutionServiceConfig(
            retry_budget_max_attempts=1,
            retry_budget_window_sec=1,
            unknown_poll_interval_sec=1,
            retry_budget_mode="ARMED_SAFE",
        ),
    )
    result = service.execute(_intent())
    assert result.status == "UNKNOWN"
    assert result.error_code == "RETRY_BUDGET_EXCEEDED"
    assert adapter.query_calls == 1
    assert called["mode"] == "ARMED_SAFE"
    assert called["reason_code"] == "EXECUTION_RETRY_BUDGET_EXCEEDED"
