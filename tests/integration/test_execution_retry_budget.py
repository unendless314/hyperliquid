from __future__ import annotations

import tempfile
from pathlib import Path

from hyperliquid.common.models import OrderIntent, OrderResult
from hyperliquid.execution.service import ExecutionService, ExecutionServiceConfig
from hyperliquid.storage.db import get_system_state, init_db, set_system_state
from hyperliquid.storage.safety import set_safety_state


class _UnknownAdapter:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.query_calls = 0

    def execute(self, intent: OrderIntent) -> OrderResult:
        self.execute_calls += 1
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id="ex-1",
            status="UNKNOWN",
            filled_qty=0.0,
            avg_price=None,
            error_code="EXECUTION_ERROR",
            error_message="unknown",
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
            error_message="unknown",
        )


class _RecoveringAdapter:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.query_calls = 0

    def execute(self, intent: OrderIntent) -> OrderResult:
        self.execute_calls += 1
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id="ex-1",
            status="UNKNOWN",
            filled_qty=0.0,
            avg_price=None,
            error_code="EXECUTION_ERROR",
            error_message="unknown",
        )

    def query_order(self, intent: OrderIntent) -> OrderResult:
        self.query_calls += 1
        status = "UNKNOWN" if self.query_calls == 1 else "FILLED"
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id="ex-1",
            status=status,
            filled_qty=1.0 if status == "FILLED" else 0.0,
            avg_price=100.0 if status == "FILLED" else None,
            error_code=None if status == "FILLED" else "EXECUTION_ERROR",
            error_message=None if status == "FILLED" else "unknown",
        )


def test_unknown_retry_budget_updates_safety(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        conn = init_db(str(root / "test.db"))
        try:
            set_system_state(conn, "safety_mode", "ARMED_LIVE")
            set_system_state(conn, "safety_reason_code", "BOOTSTRAP")
            set_system_state(conn, "safety_reason_message", "Initial bootstrap state")

            adapter = _UnknownAdapter()

            def _safety_updater(mode: str, reason_code: str, reason_message: str) -> None:
                set_safety_state(
                    conn,
                    mode=mode,
                    reason_code=reason_code,
                    reason_message=reason_message,
                )

            service = ExecutionService(
                adapter=adapter,
                result_provider=lambda _: None,
                config=ExecutionServiceConfig(
                    retry_budget_max_attempts=1,
                    retry_budget_window_sec=1,
                    unknown_poll_interval_sec=1,
                    retry_budget_mode="HALT",
                ),
                safety_state_updater=_safety_updater,
            )

            monkeypatch.setattr(
                "hyperliquid.execution.service.time.sleep",
                lambda _seconds: None,
            )

            intent = OrderIntent(
                correlation_id="hl-unknown-1-BTCUSDT",
                client_order_id="hl-unknown-1-BTCUSDT-deadbeef",
                symbol="BTCUSDT",
                side="BUY",
                order_type="MARKET",
                qty=1.0,
                price=None,
                reduce_only=0,
                time_in_force="IOC",
                is_replay=0,
            )
            result = service.execute(intent)

            assert result.status == "UNKNOWN"
            assert result.error_code == "RETRY_BUDGET_EXCEEDED"
            assert adapter.execute_calls == 1
            assert adapter.query_calls == 1
            assert get_system_state(conn, "safety_mode") == "HALT"
            assert get_system_state(conn, "safety_reason_code") == "EXECUTION_RETRY_BUDGET_EXCEEDED"
        finally:
            conn.close()


def test_unknown_recovery_succeeds_without_safety_transition(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        conn = init_db(str(root / "test.db"))
        try:
            set_system_state(conn, "safety_mode", "ARMED_LIVE")
            set_system_state(conn, "safety_reason_code", "BOOTSTRAP")
            set_system_state(conn, "safety_reason_message", "Initial bootstrap state")

            adapter = _RecoveringAdapter()
            safety_calls = {"count": 0}

            def _safety_updater(mode: str, reason_code: str, reason_message: str) -> None:
                safety_calls["count"] += 1
                set_safety_state(
                    conn,
                    mode=mode,
                    reason_code=reason_code,
                    reason_message=reason_message,
                )

            service = ExecutionService(
                adapter=adapter,
                result_provider=lambda _: None,
                config=ExecutionServiceConfig(
                    retry_budget_max_attempts=2,
                    retry_budget_window_sec=2,
                    unknown_poll_interval_sec=1,
                    retry_budget_mode="HALT",
                ),
                safety_state_updater=_safety_updater,
            )

            monkeypatch.setattr(
                "hyperliquid.execution.service.time.sleep",
                lambda _seconds: None,
            )

            intent = OrderIntent(
                correlation_id="hl-unknown-2-BTCUSDT",
                client_order_id="hl-unknown-2-BTCUSDT-deadbeef",
                symbol="BTCUSDT",
                side="BUY",
                order_type="MARKET",
                qty=1.0,
                price=None,
                reduce_only=0,
                time_in_force="IOC",
                is_replay=0,
            )
            result = service.execute(intent)

            assert result.status == "FILLED"
            assert adapter.execute_calls == 1
            assert adapter.query_calls == 2
            assert safety_calls["count"] == 0
            assert get_system_state(conn, "safety_mode") == "ARMED_LIVE"
            assert get_system_state(conn, "safety_reason_code") == "BOOTSTRAP"
        finally:
            conn.close()


def test_unknown_retry_budget_armed_safe(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        conn = init_db(str(root / "test.db"))
        try:
            set_system_state(conn, "safety_mode", "ARMED_LIVE")
            set_system_state(conn, "safety_reason_code", "BOOTSTRAP")
            set_system_state(conn, "safety_reason_message", "Initial bootstrap state")

            adapter = _UnknownAdapter()

            def _safety_updater(mode: str, reason_code: str, reason_message: str) -> None:
                set_safety_state(
                    conn,
                    mode=mode,
                    reason_code=reason_code,
                    reason_message=reason_message,
                )

            service = ExecutionService(
                adapter=adapter,
                result_provider=lambda _: None,
                config=ExecutionServiceConfig(
                    retry_budget_max_attempts=1,
                    retry_budget_window_sec=1,
                    unknown_poll_interval_sec=1,
                    retry_budget_mode="ARMED_SAFE",
                ),
                safety_state_updater=_safety_updater,
            )

            monkeypatch.setattr(
                "hyperliquid.execution.service.time.sleep",
                lambda _seconds: None,
            )

            intent = OrderIntent(
                correlation_id="hl-unknown-3-BTCUSDT",
                client_order_id="hl-unknown-3-BTCUSDT-deadbeef",
                symbol="BTCUSDT",
                side="BUY",
                order_type="MARKET",
                qty=1.0,
                price=None,
                reduce_only=0,
                time_in_force="IOC",
                is_replay=0,
            )
            result = service.execute(intent)

            assert result.status == "UNKNOWN"
            assert result.error_code == "RETRY_BUDGET_EXCEEDED"
            assert get_system_state(conn, "safety_mode") == "ARMED_SAFE"
            assert get_system_state(conn, "safety_reason_code") == "EXECUTION_RETRY_BUDGET_EXCEEDED"
        finally:
            conn.close()
