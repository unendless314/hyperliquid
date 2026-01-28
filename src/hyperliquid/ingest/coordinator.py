from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Callable, List, Optional

from hyperliquid.common.models import PositionDeltaEvent, assert_contract_version
from hyperliquid.common.settings import Settings
from hyperliquid.ingest.adapters.hyperliquid import (
    HyperliquidIngestAdapter,
    HyperliquidIngestConfig,
)
from hyperliquid.ingest.service import IngestService, RawPositionEvent
from hyperliquid.storage.db import get_system_state, set_system_state, update_cursor
from hyperliquid.storage.persistence import AuditLogEntry, DbPersistence
from hyperliquid.storage.safety import set_safety_state


@dataclass(frozen=True)
class IngestRuntimeConfig:
    backfill_window_ms: int
    cursor_overlap_ms: int
    maintenance_skip_gap: bool

    @staticmethod
    def from_settings(settings: Settings) -> "IngestRuntimeConfig":
        ingest = settings.raw.get("ingest", {})
        return IngestRuntimeConfig(
            backfill_window_ms=int(ingest.get("backfill_window_ms", 0)),
            cursor_overlap_ms=int(ingest.get("cursor_overlap_ms", 0)),
            maintenance_skip_gap=bool(ingest.get("maintenance_skip_gap", False)),
        )


@dataclass
class IngestCoordinator:
    ingest_service: IngestService
    adapter: HyperliquidIngestAdapter
    runtime: IngestRuntimeConfig
    logger: Optional[logging.Logger] = None
    audit_recorder: Optional[Callable[[AuditLogEntry], None]] = None
    last_event_gap_warn_ms: Optional[int] = None

    @staticmethod
    def from_settings(
        settings: Settings,
        ingest_service: IngestService,
        logger: Optional[logging.Logger] = None,
        audit_recorder: Optional[Callable[[AuditLogEntry], None]] = None,
    ) -> "IngestCoordinator":
        adapter = HyperliquidIngestAdapter(
            HyperliquidIngestConfig.from_settings(settings.raw), logger=logger
        )
        runtime = IngestRuntimeConfig.from_settings(settings)
        return IngestCoordinator(
            ingest_service=ingest_service,
            adapter=adapter,
            runtime=runtime,
            logger=logger,
            audit_recorder=audit_recorder,
        )

    def run_once(self, conn, *, mode: str) -> List[PositionDeltaEvent]:
        safety_mode = get_system_state(conn, "safety_mode") or "ARMED_SAFE"
        if safety_mode == "HALT":
            reason_code = get_system_state(conn, "safety_reason_code") or ""
            if self.runtime.maintenance_skip_gap and reason_code == "BACKFILL_WINDOW_EXCEEDED":
                now_ms = int(time.time() * 1000)
                self._apply_maintenance_skip(conn, now_ms=now_ms)
                return []
            else:
                return []
        if mode == "backfill-only":
            events, should_poll_live = self._run_backfill(conn)
        else:
            backfill_events, should_poll_live = self._run_backfill(conn)
            live_events = self._run_live_poll(conn) if should_poll_live else []
            events = [*backfill_events, *live_events]
        for event in events:
            assert_contract_version(event.contract_version)
        return events

    def apply_maintenance_skip(self, conn) -> bool:
        safety_mode = get_system_state(conn, "safety_mode") or "ARMED_SAFE"
        reason_code = get_system_state(conn, "safety_reason_code") or ""
        if safety_mode != "HALT":
            return False
        if reason_code != "BACKFILL_WINDOW_EXCEEDED":
            return False
        if not self.runtime.maintenance_skip_gap:
            return False
        if get_system_state(conn, "maintenance_skip_applied_ms") is not None:
            return False
        now_ms = int(time.time() * 1000)
        self._apply_maintenance_skip(conn, now_ms=now_ms)
        return True

    def _run_backfill(self, conn) -> tuple[List[PositionDeltaEvent], bool]:
        last_ts = int(get_system_state(conn, "last_processed_timestamp_ms") or 0)
        last_success_ms = int(get_system_state(conn, "last_ingest_success_ms") or 0)
        now_ms = int(time.time() * 1000)
        if last_success_ms == 0 and last_ts > 0:
            # Legacy DBs before bootstrap seed; preserve upgrade safety semantics.
            last_success_ms = last_ts
        if (
            last_success_ms > 0
            and self.runtime.backfill_window_ms
            and now_ms - last_success_ms > self.runtime.backfill_window_ms
        ):
            if self.runtime.maintenance_skip_gap:
                self._apply_maintenance_skip(conn, now_ms=now_ms)
                return [], True
            self._halt_for_gap(
                conn, last_success_ms=last_success_ms, last_event_ts=last_ts, now_ms=now_ms
            )
            return [], False
        if (
            last_ts > 0
            and self.runtime.backfill_window_ms
            and now_ms - last_ts > self.runtime.backfill_window_ms
        ):
            self._warn_event_gap(last_ts=last_ts, now_ms=now_ms)
        else:
            self.last_event_gap_warn_ms = None
        since_ms = max(0, last_ts - self.runtime.cursor_overlap_ms)
        raw_events, success = self.adapter.fetch_backfill_with_status(
            since_ms=since_ms, until_ms=now_ms
        )
        if success:
            set_system_state(conn, "last_ingest_success_ms", str(int(time.time() * 1000)))
        replay_events = [self._with_replay_flag(event, 1) for event in raw_events]
        return self.ingest_service.ingest_raw_events(replay_events, conn), True

    def _run_live_poll(self, conn) -> List[PositionDeltaEvent]:
        last_ts = int(get_system_state(conn, "last_processed_timestamp_ms") or 0)
        raw_events, success = self.adapter.poll_live_events_with_status(since_ms=last_ts)
        if success:
            set_system_state(conn, "last_ingest_success_ms", str(int(time.time() * 1000)))
        live_events = [self._with_replay_flag(event, 0) for event in raw_events]
        return self.ingest_service.ingest_raw_events(live_events, conn)

    def _with_replay_flag(self, event: RawPositionEvent, is_replay: int) -> RawPositionEvent:
        if event.is_replay == is_replay:
            return event
        return replace(event, is_replay=is_replay)

    def _halt_for_gap(
        self, conn, *, last_success_ms: int, last_event_ts: int, now_ms: int
    ) -> None:
        logger = self.logger or logging.getLogger("hyperliquid")
        logger.error(
            "ingest_gap_exceeded",
            extra={
                "last_ingest_success_ms": last_success_ms,
                "last_processed_timestamp_ms": last_event_ts,
                "now_ms": now_ms,
                "backfill_window_ms": self.runtime.backfill_window_ms,
                "gap_ms": now_ms - last_success_ms,
            },
        )
        set_safety_state(
            conn,
            mode="HALT",
            reason_code="BACKFILL_WINDOW_EXCEEDED",
            reason_message="Gap exceeds backfill window",
            audit_recorder=self._audit_recorder(conn),
        )

    def _warn_event_gap(self, *, last_ts: int, now_ms: int) -> None:
        if self.last_event_gap_warn_ms is not None:
            if now_ms - self.last_event_gap_warn_ms < 300_000:
                return
        self.last_event_gap_warn_ms = now_ms
        logger = self.logger or logging.getLogger("hyperliquid")
        logger.warning(
            "ingest_event_gap_exceeded",
            extra={
                "last_processed_timestamp_ms": last_ts,
                "now_ms": now_ms,
                "backfill_window_ms": self.runtime.backfill_window_ms,
                "gap_ms": now_ms - last_ts,
            },
        )

    def _apply_maintenance_skip(self, conn, *, now_ms: int) -> None:
        logger = self.logger or logging.getLogger("hyperliquid")
        logger.warning(
            "maintenance_skip_gap",
            extra={
                "now_ms": now_ms,
                "backfill_window_ms": self.runtime.backfill_window_ms,
            },
        )
        update_cursor(
            conn,
            timestamp_ms=now_ms,
            event_index=0,
            tx_hash="maintenance",
            symbol="MAINTENANCE",
            commit=False,
        )
        set_system_state(conn, "maintenance_skip_applied_ms", str(now_ms), commit=False)
        conn.commit()

    def _audit_recorder(self, conn):
        if self.audit_recorder is not None:
            return self.audit_recorder
        return DbPersistence(conn).record_audit


__all__ = ["IngestCoordinator", "IngestRuntimeConfig"]
