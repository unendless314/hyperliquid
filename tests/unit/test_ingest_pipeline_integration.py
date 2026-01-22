from hyperliquid.common.pipeline import Pipeline
from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision.service import DecisionService
from hyperliquid.execution.service import ExecutionService
from hyperliquid.ingest.service import IngestService, RawPositionEvent
from hyperliquid.storage.db import get_system_state
from hyperliquid.storage.persistence import DbPersistence


def _safety_mode_provider() -> str:
    return "ARMED_LIVE"


def test_ingest_pipeline_writes_intents_and_results(db_conn) -> None:
    ingest = IngestService()
    decision = DecisionService(
        config=DecisionConfig(),
        safety_mode_provider=_safety_mode_provider,
    )
    execution = ExecutionService()
    pipeline = Pipeline(
        decision=decision,
        execution=execution,
        persistence=DbPersistence(db_conn),
    )

    raw = RawPositionEvent(
        symbol="BTCUSDT",
        tx_hash="0xpipe",
        event_index=1,
        prev_target_net_position=0.0,
        next_target_net_position=1.0,
        is_replay=0,
        timestamp_ms=1700000001000,
    )

    events = ingest.ingest_raw_events([raw], db_conn)
    results = pipeline.process_events(events)

    assert len(results) == 1
    row = db_conn.execute(
        "SELECT count(*) FROM order_intents WHERE correlation_id = ?",
        (results[0].correlation_id,),
    ).fetchone()
    assert row is not None and row[0] == 1
    row = db_conn.execute(
        "SELECT count(*) FROM order_results WHERE correlation_id = ?",
        (results[0].correlation_id,),
    ).fetchone()
    assert row is not None and row[0] == 1
    assert get_system_state(db_conn, "last_processed_event_key") is not None
