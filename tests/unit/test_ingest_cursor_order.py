import tempfile

from hyperliquid.ingest.service import IngestService, RawPositionEvent
from hyperliquid.storage.db import get_system_state, init_db


def _cursor_key(conn) -> str:
    value = get_system_state(conn, "last_processed_event_key")
    assert value is not None
    return value


def test_cursor_does_not_move_backward() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        conn = init_db(tmp.name)
        ingest = IngestService()

        newer = RawPositionEvent(
            symbol="BTCUSDT",
            tx_hash="0xnew",
            event_index=2,
            prev_target_net_position=0.0,
            next_target_net_position=1.0,
            is_replay=0,
            timestamp_ms=200,
        )
        older = RawPositionEvent(
            symbol="BTCUSDT",
            tx_hash="0xold",
            event_index=1,
            prev_target_net_position=0.0,
            next_target_net_position=1.0,
            is_replay=0,
            timestamp_ms=100,
        )

        ingest.ingest_raw_events([newer, older], conn)

        assert _cursor_key(conn).startswith("200|2|0xnew|BTCUSDT")
