from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision import reasons
from hyperliquid.decision.service import DecisionService
from hyperliquid.common.models import PositionDeltaEvent


def _safety_mode_provider() -> str:
    return "ARMED_LIVE"


class _Logger:
    def __init__(self) -> None:
        self.last_reason = None

    def warning(self, _msg: str, *, extra: dict) -> None:
        self.last_reason = extra.get("reason")


def test_replay_policy_close_only() -> None:
    logger = _Logger()
    service = DecisionService(
        config=DecisionConfig(strategy_version="v1"),
        safety_mode_provider=_safety_mode_provider,
        logger=logger,
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
    assert logger.last_reason == reasons.REPLAY_POLICY_BLOCKED


def test_replay_policy_unsupported_rejects() -> None:
    logger = _Logger()
    service = DecisionService(
        config=DecisionConfig(replay_policy="allow", strategy_version="v1"),
        safety_mode_provider=_safety_mode_provider,
        logger=logger,
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
    assert intents == []
    assert logger.last_reason == reasons.REPLAY_POLICY_UNSUPPORTED


def test_strategy_version_missing_rejects() -> None:
    logger = _Logger()
    service = DecisionService(
        config=DecisionConfig(strategy_version=None),
        safety_mode_provider=_safety_mode_provider,
        logger=logger,
    )
    event = PositionDeltaEvent(
        symbol="BTCUSDT",
        timestamp_ms=1700000000000,
        tx_hash="0xstrategy-missing",
        event_index=3,
        is_replay=0,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        delta_target_net_position=1.0,
        action_type="INCREASE",
        open_component=None,
        close_component=None,
    )

    intents = service.decide(event)
    assert intents == []
    assert logger.last_reason == reasons.STRATEGY_VERSION_MISSING


def test_strategy_version_unsupported_rejects() -> None:
    logger = _Logger()
    service = DecisionService(
        config=DecisionConfig(strategy_version="v2"),
        safety_mode_provider=_safety_mode_provider,
        logger=logger,
    )
    event = PositionDeltaEvent(
        symbol="BTCUSDT",
        timestamp_ms=1700000000000,
        tx_hash="0xstrategy-unsupported",
        event_index=4,
        is_replay=0,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        delta_target_net_position=1.0,
        action_type="INCREASE",
        open_component=None,
        close_component=None,
    )

    intents = service.decide(event)
    assert intents == []
    assert logger.last_reason == reasons.STRATEGY_VERSION_UNSUPPORTED
