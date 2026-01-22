from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional

from hyperliquid.common.models import PositionDeltaEvent, assert_contract_version
from hyperliquid.storage.db import (
    advance_cursor_if_newer,
    has_processed_tx,
    record_processed_tx,
)


@dataclass(frozen=True)
class RawPositionEvent:
    symbol: str
    tx_hash: str
    event_index: int
    prev_target_net_position: float
    next_target_net_position: float
    is_replay: int = 0
    timestamp_ms: Optional[int] = None
    open_component: Optional[float] = None
    close_component: Optional[float] = None
    expected_price: Optional[float] = None
    expected_price_timestamp_ms: Optional[int] = None


@dataclass
class IngestService:
    def build_position_delta_event(
        self,
        *,
        symbol: str,
        tx_hash: str,
        event_index: int,
        prev_target_net_position: float,
        next_target_net_position: float,
        is_replay: int = 0,
        timestamp_ms: Optional[int] = None,
        action_type: Optional[str] = None,
        open_component: Optional[float] = None,
        close_component: Optional[float] = None,
        expected_price: Optional[float] = None,
        expected_price_timestamp_ms: Optional[int] = None,
    ) -> PositionDeltaEvent:
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)
        if expected_price is not None and expected_price_timestamp_ms is None:
            expected_price_timestamp_ms = timestamp_ms
        delta = next_target_net_position - prev_target_net_position
        if action_type is None:
            if prev_target_net_position == 0:
                action_type = "INCREASE" if delta != 0 else "DECREASE"
            elif prev_target_net_position > 0 > next_target_net_position:
                action_type = "FLIP"
            elif prev_target_net_position < 0 < next_target_net_position:
                action_type = "FLIP"
            elif abs(next_target_net_position) < abs(prev_target_net_position):
                action_type = "DECREASE"
            else:
                action_type = "INCREASE"

        event = PositionDeltaEvent(
            symbol=symbol,
            timestamp_ms=timestamp_ms,
            tx_hash=tx_hash,
            event_index=event_index,
            is_replay=is_replay,
            prev_target_net_position=prev_target_net_position,
            next_target_net_position=next_target_net_position,
            delta_target_net_position=delta,
            action_type=action_type,
            open_component=open_component,
            close_component=close_component,
            expected_price=expected_price,
            expected_price_timestamp_ms=expected_price_timestamp_ms,
        )
        assert_contract_version(event.contract_version)
        return event

    def ingest_raw_events(
        self, raw_events: Iterable[RawPositionEvent], conn: sqlite3.Connection
    ) -> List[PositionDeltaEvent]:
        events: List[PositionDeltaEvent] = []
        for raw in raw_events:
            if has_processed_tx(conn, raw.tx_hash, raw.event_index, raw.symbol):
                continue
            event = self.build_position_delta_event(
                symbol=raw.symbol,
                tx_hash=raw.tx_hash,
                event_index=raw.event_index,
                prev_target_net_position=raw.prev_target_net_position,
                next_target_net_position=raw.next_target_net_position,
                is_replay=raw.is_replay,
                timestamp_ms=raw.timestamp_ms,
                open_component=raw.open_component,
                close_component=raw.close_component,
                expected_price=raw.expected_price,
                expected_price_timestamp_ms=raw.expected_price_timestamp_ms,
            )
            with conn:
                record_processed_tx(
                    conn,
                    tx_hash=event.tx_hash,
                    event_index=event.event_index,
                    symbol=event.symbol,
                    timestamp_ms=event.timestamp_ms,
                    is_replay=event.is_replay,
                    commit=False,
                )
                advance_cursor_if_newer(
                    conn,
                    timestamp_ms=event.timestamp_ms,
                    event_index=event.event_index,
                    tx_hash=event.tx_hash,
                    symbol=event.symbol,
                    commit=False,
                )
            events.append(event)
        return events
