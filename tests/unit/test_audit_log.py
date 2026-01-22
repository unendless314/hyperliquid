from hyperliquid.common.models import OrderIntent, OrderResult
from hyperliquid.execution.service import ExecutionService
from hyperliquid.storage.persistence import DbPersistence
from hyperliquid.storage.safety import set_safety_state


class _StubAdapter:
    def execute(self, intent: OrderIntent) -> OrderResult:
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id="ex-1",
            status="SUBMITTED",
            filled_qty=0.0,
            avg_price=None,
            error_code=None,
            error_message=None,
        )


def _intent() -> OrderIntent:
    return OrderIntent(
        correlation_id="hl-abc-1-BTCUSDT",
        client_order_id="hl-abc-1-BTCUSDT-deadbeef",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        qty=0.01,
        price=100.0,
        reduce_only=0,
        time_in_force="IOC",
        is_replay=0,
        risk_notes=None,
    )


def test_audit_log_execution_transition_written_once(db_conn) -> None:
    persistence = DbPersistence(db_conn)
    service = ExecutionService(
        adapter=_StubAdapter(),
        audit_recorder=persistence.record_audit,
    )
    result = service.execute(_intent())
    assert result.status == "SUBMITTED"
    row = db_conn.execute("SELECT count(*) FROM audit_log").fetchone()
    assert row is not None and row[0] == 1
    entry = db_conn.execute(
        "SELECT category, entity_id, from_state, to_state FROM audit_log"
    ).fetchone()
    assert entry == ("execution", "hl-abc-1-BTCUSDT", "NONE", "SUBMITTED")


def test_audit_log_safety_transition_writes_only_on_change(db_conn) -> None:
    persistence = DbPersistence(db_conn)
    set_safety_state(
        db_conn,
        mode="ARMED_SAFE",
        reason_code="BOOT",
        reason_message="boot",
        audit_recorder=persistence.record_audit,
    )
    set_safety_state(
        db_conn,
        mode="ARMED_SAFE",
        reason_code="BOOT",
        reason_message="boot",
        audit_recorder=persistence.record_audit,
    )
    row = db_conn.execute("SELECT count(*) FROM audit_log").fetchone()
    assert row is not None and row[0] == 1


def test_audit_log_failure_does_not_block_execution() -> None:
    def _boom(_entry):
        raise RuntimeError("fail")

    service = ExecutionService(adapter=_StubAdapter(), audit_recorder=_boom)
    result = service.execute(_intent())
    assert result.status == "SUBMITTED"
