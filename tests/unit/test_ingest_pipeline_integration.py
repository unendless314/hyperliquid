import tempfile

from hyperliquid.common.pipeline import Pipeline
from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision.service import DecisionService
from hyperliquid.execution.service import ExecutionService
from hyperliquid.ingest.service import IngestService, RawPositionEvent
from hyperliquid.storage.db import get_system_state, init_db
from hyperliquid.storage.persistence import DbPersistence


def _safety_mode_provider() -> str:
    return "ARMED_LIVE"


def test_ingest_pipeline_writes_intents_and_results() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        conn = init_db(tmp.name)
        ingest = IngestService()
        decision = DecisionService(
            config=DecisionConfig(),
            safety_mode_provider=_safety_mode_provider,
        )
        execution = ExecutionService()
        pipeline = Pipeline(
            decision=decision,
            execution=execution,
            persistence=DbPersistence(conn),
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

        events = ingest.ingest_raw_events([raw], conn)
        results = pipeline.process_events(events)

        assert len(results) == 1
        row = conn.execute(
            "SELECT count(*) FROM order_intents WHERE correlation_id = ?",
            (results[0].correlation_id,),
        ).fetchone()
        assert row is not None and row[0] == 1
        row = conn.execute(
            "SELECT count(*) FROM order_results WHERE correlation_id = ?",
            (results[0].correlation_id,),
        ).fetchone()
        assert row is not None and row[0] == 1
        assert get_system_state(conn, "last_processed_event_key") is not None
