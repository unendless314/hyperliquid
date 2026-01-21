from hyperliquid.common.pipeline import Pipeline
from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision.service import DecisionService
from hyperliquid.execution.service import ExecutionService
from hyperliquid.ingest.service import IngestService
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
