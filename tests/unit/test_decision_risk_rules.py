from hyperliquid.common.filters import SymbolFilters
from hyperliquid.common.models import PositionDeltaEvent, PriceSnapshot
from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision.service import DecisionService
from hyperliquid.decision.types import DecisionInputs
from hyperliquid.decision import reasons


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


def test_blacklist_rejects() -> None:
    service = DecisionService(
        config=DecisionConfig(strategy_version="v1", blacklist_symbols=["BTCUSDT"]),
        safety_mode_provider=_safety_mode_provider,
    )
    intents = service.decide(_increase_event("0xblk"))
    assert intents == []


def test_filters_unavailable_allow_adds_risk_note() -> None:
    service = DecisionService(
        config=DecisionConfig(
            strategy_version="v1",
            filters_enabled=True,
            filters_failure_policy="allow_without_filters",
            price_failure_policy="allow_without_price",
        ),
        safety_mode_provider=_safety_mode_provider,
        filters_provider=None,
    )
    intents = service.decide(_increase_event("0xfilt"), DecisionInputs(safety_mode="ARMED_LIVE"))
    assert len(intents) == 1
    notes = set((intents[0].risk_notes or "").split(","))
    assert reasons.FILTERS_UNAVAILABLE in notes
    assert reasons.MISSING_REFERENCE_PRICE in notes


def test_filters_unavailable_rejects() -> None:
    service = DecisionService(
        config=DecisionConfig(
            strategy_version="v1",
            filters_enabled=True,
            filters_failure_policy="reject",
        ),
        safety_mode_provider=_safety_mode_provider,
        filters_provider=None,
    )
    intents = service.decide(_increase_event("0xfilt-reject"), DecisionInputs(safety_mode="ARMED_LIVE"))
    assert intents == []


def test_price_fallback_adds_note() -> None:
    service = DecisionService(
        config=DecisionConfig(
            strategy_version="v1",
            price_fallback_enabled=True,
            price_fallback_max_stale_ms=5000,
        ),
        safety_mode_provider=_safety_mode_provider,
        price_provider=lambda symbol: None,
        fallback_price_provider=lambda symbol: PriceSnapshot(
            price=100.0, timestamp_ms=1700000000000, source="ingest"
        ),
        now_ms_provider=lambda: 1700000000000,
    )
    intents = service.decide(_increase_event("0xfallback"), DecisionInputs(safety_mode="ARMED_LIVE"))
    assert len(intents) == 1
    notes = set((intents[0].risk_notes or "").split(","))
    assert reasons.PRICE_FALLBACK_USED in notes
    assert reasons.MISSING_REFERENCE_PRICE not in notes


def test_missing_reference_price_note_not_duplicated() -> None:
    service = DecisionService(
        config=DecisionConfig(
            strategy_version="v1",
            slippage_cap_pct=0.01,
            price_failure_policy="allow_without_price",
        ),
        safety_mode_provider=_safety_mode_provider,
        price_provider=lambda symbol: None,
    )
    inputs = DecisionInputs(
        safety_mode="ARMED_LIVE",
        expected_price=PriceSnapshot(price=100.0, timestamp_ms=1700000000000, source="ingest"),
    )
    intents = service.decide(_increase_event("0xmissingref"), inputs)
    assert len(intents) == 1
    notes = (intents[0].risk_notes or "").split(",")
    assert notes.count(reasons.MISSING_REFERENCE_PRICE) == 1
