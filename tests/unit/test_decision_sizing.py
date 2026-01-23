from hyperliquid.common.models import PositionDeltaEvent
from hyperliquid.decision.config import DecisionConfig, SizingConfig
from hyperliquid.decision.service import DecisionService
from hyperliquid.decision.types import DecisionInputs


def _safety_mode_provider() -> str:
    return "ARMED_LIVE"


def _increase_event(tx_hash: str) -> PositionDeltaEvent:
    return PositionDeltaEvent(
        symbol="BTCUSDT",
        timestamp_ms=1700000000000,
        tx_hash=tx_hash,
        event_index=1,
        is_replay=0,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        delta_target_net_position=1.0,
        action_type="INCREASE",
        open_component=None,
        close_component=None,
    )


def test_kelly_params_missing_rejects() -> None:
    service = DecisionService(
        config=DecisionConfig(
            strategy_version="v1",
            sizing=SizingConfig(
                mode="kelly",
                kelly_win_rate=0.0,
                kelly_edge=1.0,
                kelly_fraction=1.0,
            ),
        ),
        safety_mode_provider=_safety_mode_provider,
    )
    intents = service.decide(_increase_event("0xkelly-missing"), DecisionInputs(safety_mode="ARMED_LIVE"))
    assert intents == []


def test_kelly_invalid_range_rejects() -> None:
    service = DecisionService(
        config=DecisionConfig(
            strategy_version="v1",
            sizing=SizingConfig(
                mode="kelly",
                kelly_win_rate=1.2,
                kelly_edge=1.0,
                kelly_fraction=1.0,
            ),
        ),
        safety_mode_provider=_safety_mode_provider,
    )
    intents = service.decide(_increase_event("0xkelly-range"), DecisionInputs(safety_mode="ARMED_LIVE"))
    assert intents == []


def test_kelly_fraction_invalid_rejects() -> None:
    service = DecisionService(
        config=DecisionConfig(
            strategy_version="v1",
            sizing=SizingConfig(
                mode="kelly",
                kelly_win_rate=0.6,
                kelly_edge=1.0,
                kelly_fraction=0.0,
            ),
        ),
        safety_mode_provider=_safety_mode_provider,
    )
    intents = service.decide(_increase_event("0xkelly-fraction"), DecisionInputs(safety_mode="ARMED_LIVE"))
    assert intents == []


def test_kelly_valid_emits_intent() -> None:
    service = DecisionService(
        config=DecisionConfig(
            strategy_version="v1",
            sizing=SizingConfig(
                mode="kelly",
                kelly_win_rate=0.6,
                kelly_edge=2.0,
                kelly_fraction=1.0,
            ),
        ),
        safety_mode_provider=_safety_mode_provider,
    )
    intents = service.decide(_increase_event("0xkelly-ok"), DecisionInputs(safety_mode="ARMED_LIVE"))
    assert len(intents) == 1
    assert intents[0].qty > 0


def test_max_qty_rejects() -> None:
    service = DecisionService(
        config=DecisionConfig(
            strategy_version="v1",
            sizing=SizingConfig(
                mode="proportional",
                proportional_ratio=2.0,
                max_qty=1.5,
            ),
        ),
        safety_mode_provider=_safety_mode_provider,
    )
    intents = service.decide(_increase_event("0xmaxqty"), DecisionInputs(safety_mode="ARMED_LIVE"))
    assert intents == []
