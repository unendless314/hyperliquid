from hyperliquid.common.models import PositionDeltaEvent
from hyperliquid.decision.config import DecisionConfig, SizingConfig
from hyperliquid.decision.service import DecisionService
from hyperliquid.decision.types import DecisionInputs


def _safety_mode_provider() -> str:
    return "ARMED_LIVE"


def _increase_event(delta: float) -> PositionDeltaEvent:
    return PositionDeltaEvent(
        symbol="BTCUSDT",
        timestamp_ms=1700000000000,
        tx_hash=f"0xsizing-{delta}",
        event_index=1,
        is_replay=0,
        prev_target_net_position=0.0,
        next_target_net_position=delta,
        delta_target_net_position=delta,
        action_type="INCREASE",
        open_component=None,
        close_component=None,
    )


def test_fixed_sizing_uses_fixed_qty() -> None:
    service = DecisionService(
        config=DecisionConfig(
            strategy_version="v1",
            sizing=SizingConfig(mode="fixed", fixed_qty=0.75),
        ),
        safety_mode_provider=_safety_mode_provider,
    )
    intents = service.decide(_increase_event(2.0), DecisionInputs(safety_mode="ARMED_LIVE"))
    assert len(intents) == 1
    assert intents[0].qty == 0.75


def test_proportional_sizing_scales_by_ratio() -> None:
    service = DecisionService(
        config=DecisionConfig(
            strategy_version="v1",
            sizing=SizingConfig(mode="proportional", proportional_ratio=0.5),
        ),
        safety_mode_provider=_safety_mode_provider,
    )
    intents = service.decide(_increase_event(2.0), DecisionInputs(safety_mode="ARMED_LIVE"))
    assert len(intents) == 1
    assert intents[0].qty == 1.0


def test_kelly_sizing_applies_kelly_fraction() -> None:
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
    intents = service.decide(_increase_event(2.0), DecisionInputs(safety_mode="ARMED_LIVE"))
    assert len(intents) == 1
    # kelly_fraction = 0.6 - ((1 - 0.6) / 2.0) = 0.4
    assert abs(intents[0].qty - 0.8) < 1e-9
