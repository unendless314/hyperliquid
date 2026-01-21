from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision.service import DecisionService
from hyperliquid.common.models import PositionDeltaEvent


def _safety_mode_provider() -> str:
    return "ARMED_LIVE"


def test_replay_policy_close_only() -> None:
    service = DecisionService(
        config=DecisionConfig(),
        safety_mode_provider=_safety_mode_provider,
    )
    event = PositionDeltaEvent(
        symbol="BTCUSDT",
        timestamp_ms=1700000000000,
        tx_hash="0xreplay",
        event_index=1,
        is_replay=1,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        delta_target_net_position=1.0,
        action_type="INCREASE",
        open_component=None,
        close_component=None,
    )

    intents = service.decide(event)
    assert intents == []


def test_replay_policy_allow_from_config() -> None:
    service = DecisionService(
        config=DecisionConfig(replay_policy="allow"),
        safety_mode_provider=_safety_mode_provider,
    )
    event = PositionDeltaEvent(
        symbol="BTCUSDT",
        timestamp_ms=1700000000000,
        tx_hash="0xreplay-allow",
        event_index=2,
        is_replay=1,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        delta_target_net_position=1.0,
        action_type="INCREASE",
        open_component=None,
        close_component=None,
    )

    intents = service.decide(event)
    assert len(intents) == 1
