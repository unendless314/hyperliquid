from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from hyperliquid.common.models import PositionDeltaEvent, assert_contract_version


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
    ) -> PositionDeltaEvent:
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)
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
        )
        assert_contract_version(event.contract_version)
        return event
