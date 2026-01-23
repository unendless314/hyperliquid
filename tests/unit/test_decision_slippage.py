from hyperliquid.common.models import PositionDeltaEvent, PriceSnapshot
from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision.service import DecisionService
from hyperliquid.decision.types import DecisionInputs


def _safety_mode_provider() -> str:
    return "ARMED_LIVE"


def _event() -> PositionDeltaEvent:
    return PositionDeltaEvent(
        symbol="BTCUSDT",
        timestamp_ms=1700000000000,
        tx_hash="0xslip",
        event_index=1,
        is_replay=0,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        delta_target_net_position=1.0,
        action_type="INCREASE",
        open_component=None,
        close_component=None,
    )


def test_slippage_rejects_when_reference_missing_and_policy_rejects() -> None:
    service = DecisionService(
        config=DecisionConfig(
            slippage_cap_pct=0.01, price_failure_policy="reject", strategy_version="v1"
        ),
        safety_mode_provider=_safety_mode_provider,
        price_provider=lambda symbol: None,
    )
    inputs = DecisionInputs(
        safety_mode="ARMED_LIVE",
        expected_price=PriceSnapshot(price=100.0, timestamp_ms=1700000000000, source="ingest"),
    )
    intents = service.decide(_event(), inputs)
    assert intents == []


def test_slippage_rejects_when_expected_missing_and_policy_rejects() -> None:
    service = DecisionService(
        config=DecisionConfig(
            slippage_cap_pct=0.01, price_failure_policy="reject", strategy_version="v1"
        ),
        safety_mode_provider=_safety_mode_provider,
        price_provider=lambda symbol: PriceSnapshot(
            price=101.0, timestamp_ms=1700000000000, source="adapter"
        ),
    )
    inputs = DecisionInputs(safety_mode="ARMED_LIVE", expected_price=None)
    intents = service.decide(_event(), inputs)
    assert intents == []


def test_slippage_rejects_when_over_cap() -> None:
    service = DecisionService(
        config=DecisionConfig(
            slippage_cap_pct=0.01,
            price_failure_policy="allow_without_price",
            strategy_version="v1",
        ),
        safety_mode_provider=_safety_mode_provider,
        price_provider=lambda symbol: PriceSnapshot(
            price=105.0, timestamp_ms=1700000000000, source="adapter"
        ),
    )
    inputs = DecisionInputs(
        safety_mode="ARMED_LIVE",
        expected_price=PriceSnapshot(price=100.0, timestamp_ms=1700000000000, source="ingest"),
    )
    intents = service.decide(_event(), inputs)
    assert intents == []


def test_slippage_allows_within_cap() -> None:
    service = DecisionService(
        config=DecisionConfig(
            slippage_cap_pct=0.02,
            price_failure_policy="allow_without_price",
            strategy_version="v1",
        ),
        safety_mode_provider=_safety_mode_provider,
        price_provider=lambda symbol: PriceSnapshot(
            price=101.0, timestamp_ms=1700000000000, source="adapter"
        ),
    )
    inputs = DecisionInputs(
        safety_mode="ARMED_LIVE",
        expected_price=PriceSnapshot(price=100.0, timestamp_ms=1700000000000, source="ingest"),
    )
    intents = service.decide(_event(), inputs)
    assert len(intents) == 1


def test_slippage_rejects_stale_expected_price() -> None:
    service = DecisionService(
        config=DecisionConfig(
            slippage_cap_pct=0.02,
            price_failure_policy="reject",
            expected_price_max_stale_ms=1000,
            strategy_version="v1",
        ),
        safety_mode_provider=_safety_mode_provider,
        now_ms_provider=lambda: 2000,
        price_provider=lambda symbol: PriceSnapshot(
            price=101.0, timestamp_ms=2000, source="adapter"
        ),
    )
    inputs = DecisionInputs(
        safety_mode="ARMED_LIVE",
        expected_price=PriceSnapshot(price=100.0, timestamp_ms=0, source="ingest"),
    )
    intents = service.decide(_event(), inputs)
    assert intents == []
