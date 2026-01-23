from hyperliquid.common.models import PositionDeltaEvent
from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision.service import DecisionService
from hyperliquid.decision.types import DecisionInputs


def _safety_mode_provider() -> str:
    return "ARMED_LIVE"


def _flip_event() -> PositionDeltaEvent:
    return PositionDeltaEvent(
        symbol="BTCUSDT",
        timestamp_ms=1700000000000,
        tx_hash="0xdet",
        event_index=1,
        is_replay=0,
        prev_target_net_position=1.5,
        next_target_net_position=-2.0,
        delta_target_net_position=-3.5,
        action_type="FLIP",
        open_component=2.0,
        close_component=1.5,
    )


def _increase_event() -> PositionDeltaEvent:
    return PositionDeltaEvent(
        symbol="BTCUSDT",
        timestamp_ms=1700000000000,
        tx_hash="0xdet-inc",
        event_index=2,
        is_replay=0,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        delta_target_net_position=1.0,
        action_type="INCREASE",
        open_component=None,
        close_component=None,
    )


def _intent_signature(intents):
    return [
        (
            intent.correlation_id,
            intent.side,
            intent.qty,
            intent.reduce_only,
            intent.strategy_version,
        )
        for intent in intents
    ]


def test_deterministic_flip_intents() -> None:
    service = DecisionService(
        config=DecisionConfig(strategy_version="v1"),
        safety_mode_provider=_safety_mode_provider,
    )
    inputs = DecisionInputs(
        safety_mode="ARMED_LIVE",
        local_current_position=1.5,
        closable_qty=1.5,
    )
    first = service.decide(_flip_event(), inputs)
    second = service.decide(_flip_event(), inputs)
    assert _intent_signature(first) == _intent_signature(second)
    assert [intent.correlation_id for intent in first] == [
        "hl-0xdet-1-BTCUSDT-close",
        "hl-0xdet-1-BTCUSDT-open",
    ]


def test_deterministic_increase_intent() -> None:
    service = DecisionService(
        config=DecisionConfig(strategy_version="v1"),
        safety_mode_provider=_safety_mode_provider,
    )
    inputs = DecisionInputs(safety_mode="ARMED_LIVE")
    first = service.decide(_increase_event(), inputs)
    second = service.decide(_increase_event(), inputs)
    assert _intent_signature(first) == _intent_signature(second)
