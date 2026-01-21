from hyperliquid.common.models import PositionDeltaEvent
from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision.service import DecisionService


def _safety_mode_provider() -> str:
    return "ARMED_LIVE"


def _event(timestamp_ms: int) -> PositionDeltaEvent:
    return PositionDeltaEvent(
        symbol="BTCUSDT",
        timestamp_ms=timestamp_ms,
        tx_hash="0xstale",
        event_index=1,
        is_replay=0,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        delta_target_net_position=1.0,
        action_type="INCREASE",
        open_component=None,
        close_component=None,
    )


def test_fresh_event_passes() -> None:
    service = DecisionService(
        config=DecisionConfig(max_stale_ms=1000),
        safety_mode_provider=_safety_mode_provider,
        now_ms_provider=lambda: 2_000,
    )
    intents = service.decide(_event(timestamp_ms=1_500))
    assert len(intents) == 1


def test_stale_event_rejected() -> None:
    service = DecisionService(
        config=DecisionConfig(max_stale_ms=1000, max_future_ms=2000),
        safety_mode_provider=_safety_mode_provider,
        now_ms_provider=lambda: 2_000,
    )
    intents = service.decide(_event(timestamp_ms=500))
    assert intents == []


def test_missing_timestamp_rejected_when_enabled() -> None:
    service = DecisionService(
        config=DecisionConfig(max_stale_ms=1000, max_future_ms=2000),
        safety_mode_provider=_safety_mode_provider,
        now_ms_provider=lambda: 2_000,
    )
    intents = service.decide(_event(timestamp_ms=0))
    assert intents == []


def test_future_event_within_skew_allowed() -> None:
    service = DecisionService(
        config=DecisionConfig(max_stale_ms=1000, max_future_ms=2000),
        safety_mode_provider=_safety_mode_provider,
        now_ms_provider=lambda: 2_000,
    )
    intents = service.decide(_event(timestamp_ms=3_500))
    assert len(intents) == 1


def test_future_event_rejected_beyond_skew() -> None:
    service = DecisionService(
        config=DecisionConfig(max_stale_ms=1000, max_future_ms=2000),
        safety_mode_provider=_safety_mode_provider,
        now_ms_provider=lambda: 2_000,
    )
    intents = service.decide(_event(timestamp_ms=5_001))
    assert intents == []


def test_stale_check_disabled_allows_past_event() -> None:
    service = DecisionService(
        config=DecisionConfig(max_stale_ms=0, max_future_ms=2000),
        safety_mode_provider=_safety_mode_provider,
        now_ms_provider=lambda: 2_000,
    )
    intents = service.decide(_event(timestamp_ms=1_500))
    assert len(intents) == 1
