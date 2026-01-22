from hyperliquid.common.pipeline import Pipeline
from hyperliquid.decision.config import DecisionConfig
from hyperliquid.common.models import PriceSnapshot
from hyperliquid.decision.service import DecisionService
from hyperliquid.execution.service import ExecutionService
from hyperliquid.ingest.service import IngestService
from hyperliquid.storage.db import set_system_state
from hyperliquid.storage.memory import InMemoryPersistence


def _safety_mode_provider() -> str:
    return "ARMED_LIVE"


def test_pipeline_records_intents_and_results() -> None:
    ingest = IngestService()
    decision = DecisionService(
        config=DecisionConfig(),
        safety_mode_provider=_safety_mode_provider,
    )
    execution = ExecutionService()
    persistence = InMemoryPersistence()

    pipeline = Pipeline(
        decision=decision,
        execution=execution,
        persistence=persistence,
    )

    event = ingest.build_position_delta_event(
        symbol="BTCUSDT",
        tx_hash="0xabc",
        event_index=1,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        is_replay=0,
    )

    results = pipeline.process_single_event(event)

    assert len(results) == 1
    assert len(persistence.intents) == 1
    assert len(persistence.results) == 1
    assert persistence.intents[0].correlation_id == results[0].correlation_id


def test_expected_price_wired_into_decision_inputs(db_conn, db_path) -> None:
    set_system_state(db_conn, "safety_mode", "ARMED_LIVE")
    ingest = IngestService()
    decision = DecisionService(
        config=DecisionConfig(slippage_cap_pct=0.01, price_failure_policy="allow_without_price"),
        safety_mode_provider=_safety_mode_provider,
        price_provider=lambda symbol: PriceSnapshot(
            price=105.0, timestamp_ms=1700000000000, source="adapter"
        ),
    )
    execution = ExecutionService()
    persistence = InMemoryPersistence()

    from hyperliquid.common.settings import Settings
    from hyperliquid.orchestrator.service import Orchestrator
    from pathlib import Path

    settings = Settings(
        config_version="0.1",
        environment="local",
        db_path=db_path,
        metrics_log_path="logs/metrics.log",
        app_log_path="logs/app.log",
        log_level="INFO",
        config_path=Path("config/settings.yaml"),
        raw={
            "execution": {"binance": {"enabled": False, "mode": "stub"}},
            "decision": {
                "slippage_cap_pct": 0.01,
                "price_failure_policy": "allow_without_price",
            },
        },
    )
    orchestrator = Orchestrator(settings=settings, mode="dry-run", emit_boot_event=False)
    services = orchestrator._initialize_services(db_conn, None)
    pipeline = Pipeline(
        decision=decision,
        execution=execution,
        decision_inputs_provider=services["pipeline"].decision_inputs_provider,
        persistence=persistence,
    )

    event = ingest.build_position_delta_event(
        symbol="BTCUSDT",
        tx_hash="0xprice",
        event_index=2,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        is_replay=0,
        expected_price=100.0,
        expected_price_timestamp_ms=1700000000000,
    )

    results = pipeline.process_single_event(event)
    assert results == []


def test_expected_price_missing_allows_intent(db_conn, db_path) -> None:
    set_system_state(db_conn, "safety_mode", "ARMED_LIVE")
    ingest = IngestService()
    decision = DecisionService(
        config=DecisionConfig(slippage_cap_pct=0.01, price_failure_policy="allow_without_price"),
        safety_mode_provider=_safety_mode_provider,
        price_provider=lambda symbol: PriceSnapshot(
            price=105.0, timestamp_ms=1700000000000, source="adapter"
        ),
    )
    execution = ExecutionService()
    persistence = InMemoryPersistence()

    from hyperliquid.common.settings import Settings
    from hyperliquid.orchestrator.service import Orchestrator
    from pathlib import Path

    settings = Settings(
        config_version="0.1",
        environment="local",
        db_path=db_path,
        metrics_log_path="logs/metrics.log",
        app_log_path="logs/app.log",
        log_level="INFO",
        config_path=Path("config/settings.yaml"),
        raw={
            "execution": {"binance": {"enabled": False, "mode": "stub"}},
            "decision": {
                "slippage_cap_pct": 0.01,
                "price_failure_policy": "allow_without_price",
            },
        },
    )
    orchestrator = Orchestrator(settings=settings, mode="dry-run", emit_boot_event=False)
    services = orchestrator._initialize_services(db_conn, None)
    pipeline = Pipeline(
        decision=decision,
        execution=execution,
        decision_inputs_provider=services["pipeline"].decision_inputs_provider,
        persistence=persistence,
    )

    event = ingest.build_position_delta_event(
        symbol="BTCUSDT",
        tx_hash="0xpricemissing",
        event_index=3,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        is_replay=0,
    )

    results = pipeline.process_single_event(event)
    assert len(results) == 1
