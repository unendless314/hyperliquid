from hyperliquid.common.models import OrderIntent
from hyperliquid.execution.service import ExecutionService
from hyperliquid.safety.service import SafetyService


def test_execution_hook_signatures_accept_expected_args() -> None:
    called = {"pre": 0, "post": 0}

    def _pre_hook(intent: OrderIntent) -> None:
        called["pre"] += 1
        assert intent.correlation_id == "hl-hook-1-BTCUSDT"

    def _post_hook(intent: OrderIntent, _result) -> None:
        called["post"] += 1
        assert intent.correlation_id == "hl-hook-1-BTCUSDT"

    service = ExecutionService(pre_hooks=[_pre_hook], post_hooks=[_post_hook])
    intent = OrderIntent(
        correlation_id="hl-hook-1-BTCUSDT",
        client_order_id="hl-hook-1-BTCUSDT-deadbeef",
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

    assert result.status == "SUBMITTED"
    assert called["pre"] == 1
    assert called["post"] == 1


def test_safety_service_hooks_match_execution_signature() -> None:
    safety = SafetyService(safety_mode_provider=lambda: "ARMED_LIVE")
    service = ExecutionService(
        pre_hooks=[safety.pre_execution_check],
        post_hooks=[safety.post_execution_check],
    )
    intent = OrderIntent(
        correlation_id="hl-hook-2-BTCUSDT",
        client_order_id="hl-hook-2-BTCUSDT-deadbeef",
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

    assert result.status == "SUBMITTED"
