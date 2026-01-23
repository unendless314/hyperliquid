from hyperliquid.common.models import PositionDeltaEvent
from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision.service import DecisionService
from hyperliquid.decision.types import DecisionInputs


def _safety_mode_provider() -> str:
    return "ARMED_LIVE"


def _decrease_event() -> PositionDeltaEvent:
    return PositionDeltaEvent(
        symbol="BTCUSDT",
        timestamp_ms=1700000000000,
        tx_hash="0xdec",
        event_index=1,
        is_replay=0,
        prev_target_net_position=1.0,
        next_target_net_position=0.5,
        delta_target_net_position=-0.5,
        action_type="DECREASE",
        open_component=None,
        close_component=None,
    )


def _increase_event() -> PositionDeltaEvent:
    return PositionDeltaEvent(
        symbol="BTCUSDT",
        timestamp_ms=1700000000000,
        tx_hash="0xinc",
        event_index=2,
        is_replay=0,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        delta_target_net_position=1.0,
        action_type="INCREASE",
        open_component=None,
        close_component=None,
    )


def test_missing_local_position_rejects_decrease() -> None:
    service = DecisionService(
        config=DecisionConfig(strategy_version="v1"),
        safety_mode_provider=_safety_mode_provider,
    )
    inputs = DecisionInputs(safety_mode="ARMED_LIVE", local_current_position=None, closable_qty=1.0)
    intents = service.decide(_decrease_event(), inputs)
    assert intents == []


def test_missing_closable_qty_rejects_decrease() -> None:
    service = DecisionService(
        config=DecisionConfig(strategy_version="v1"),
        safety_mode_provider=_safety_mode_provider,
    )
    inputs = DecisionInputs(safety_mode="ARMED_LIVE", local_current_position=1.0, closable_qty=None)
    intents = service.decide(_decrease_event(), inputs)
    assert intents == []


def test_missing_local_position_allows_increase() -> None:
    service = DecisionService(
        config=DecisionConfig(strategy_version="v1"),
        safety_mode_provider=_safety_mode_provider,
    )
    inputs = DecisionInputs(safety_mode="ARMED_LIVE", local_current_position=None, closable_qty=None)
    intents = service.decide(_increase_event(), inputs)
    assert len(intents) == 1
    assert intents[0].strategy_version == "v1"
