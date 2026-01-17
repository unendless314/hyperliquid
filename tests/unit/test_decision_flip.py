from hyperliquid.decision.service import DecisionService
from hyperliquid.common.models import PositionDeltaEvent


def _safety_mode_provider(mode: str):
    return lambda: mode


def _flip_event() -> PositionDeltaEvent:
    return PositionDeltaEvent(
        symbol="BTCUSDT",
        timestamp_ms=1700000000000,
        tx_hash="0xabc",
        event_index=1,
        is_replay=0,
        prev_target_net_position=1.5,
        next_target_net_position=-2.0,
        delta_target_net_position=-3.5,
        action_type="FLIP",
        open_component=2.0,
        close_component=1.5,
    )


def test_flip_generates_distinct_intents() -> None:
    service = DecisionService(safety_mode_provider=_safety_mode_provider("ARMED_LIVE"))
    intents = service.decide(_flip_event())

    assert len(intents) == 2
    assert intents[0].correlation_id != intents[1].correlation_id
    assert intents[0].correlation_id.endswith("-close")
    assert intents[1].correlation_id.endswith("-open")


def test_flip_in_armed_safe_keeps_reduce_only() -> None:
    service = DecisionService(safety_mode_provider=_safety_mode_provider("ARMED_SAFE"))
    intents = service.decide(_flip_event())

    assert len(intents) == 1
    assert intents[0].reduce_only == 1
    assert intents[0].correlation_id.endswith("-close")
