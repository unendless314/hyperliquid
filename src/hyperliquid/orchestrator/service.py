from __future__ import annotations

import time
from dataclasses import dataclass

from hyperliquid.common.logging import setup_logging
from hyperliquid.common.metrics import MetricsEmitter
from hyperliquid.common.models import CONTRACT_VERSION, assert_contract_version
from hyperliquid.common.pipeline import Pipeline
from hyperliquid.common.settings import Settings, compute_config_hash
from hyperliquid.decision.service import DecisionService
from hyperliquid.execution.service import ExecutionService
from hyperliquid.ingest.service import IngestService
from hyperliquid.safety.service import SafetyService
from hyperliquid.storage.db import assert_schema_version, get_system_state, init_db, set_system_state
from hyperliquid.storage.persistence import DbPersistence


@dataclass
class Orchestrator:
    settings: Settings
    mode: str
    emit_boot_event: bool = True
    run_loop: bool = False
    loop_interval_sec: int = 5

    def run(self) -> None:
        logger = setup_logging(self.settings.app_log_path, self.settings.log_level)
        metrics = MetricsEmitter(self.settings.metrics_log_path)
        conn = None
        try:
            logger.info("boot_start")
            conn = init_db(self.settings.db_path)
            assert_schema_version(conn)

            config_hash = compute_config_hash(self.settings.config_path)
            self._handle_config_hash(conn, config_hash, logger)
            self._record_config(conn, config_hash)
            self._ensure_bootstrap_state(conn)
            services = self._initialize_services(conn)
            if self.emit_boot_event:
                self._run_single_cycle(services, logger)
            logger.info("boot_complete", extra={"mode": self.mode})
            if self.run_loop:
                self._run_loop(logger, metrics)
            metrics.emit("cursor_lag_ms", 0)
        except RuntimeError as exc:
            if str(exc) == "SCHEMA_VERSION_MISMATCH" and conn is not None:
                set_system_state(conn, "safety_mode", "HALT")
                set_system_state(conn, "safety_reason_code", "SCHEMA_VERSION_MISMATCH")
                set_system_state(
                    conn, "safety_reason_message", "DB schema version mismatch"
                )
                set_system_state(
                    conn, "safety_changed_at_ms", str(int(time.time() * 1000))
                )
            raise
        except KeyboardInterrupt:
            logger.info("shutdown_requested")
        finally:
            metrics.close()
            if conn is not None:
                conn.close()

    @staticmethod
    def _handle_config_hash(conn, config_hash: str, logger) -> None:
        existing = get_system_state(conn, "config_hash")
        if existing and existing != config_hash:
            logger.warning("config_hash_changed", extra={"previous": existing})
            if get_system_state(conn, "safety_mode") == "HALT":
                return
            if get_system_state(conn, "safety_mode") is None:
                set_system_state(conn, "safety_mode", "ARMED_SAFE")
            set_system_state(conn, "safety_reason_code", "CONFIG_HASH_CHANGED")
            set_system_state(
                conn,
                "safety_reason_message",
                "Config hash changed; continuing per operator policy",
            )
            set_system_state(conn, "safety_changed_at_ms", str(int(time.time() * 1000)))

    def _record_config(self, conn, config_hash: str) -> None:
        set_system_state(conn, "config_hash", config_hash)
        set_system_state(conn, "config_version", self.settings.config_version)
        self._assert_contract_version(conn)
        set_system_state(conn, "contract_version", CONTRACT_VERSION)

    @staticmethod
    def _assert_contract_version(conn) -> None:
        existing = get_system_state(conn, "contract_version")
        if existing:
            try:
                assert_contract_version(existing)
            except ValueError as exc:
                set_system_state(conn, "safety_mode", "HALT")
                set_system_state(conn, "safety_reason_code", "CONTRACT_VERSION_MISMATCH")
                set_system_state(conn, "safety_reason_message", str(exc))
                set_system_state(conn, "safety_changed_at_ms", str(int(time.time() * 1000)))
                raise

    @staticmethod
    def _ensure_bootstrap_state(conn) -> None:
        now_ms = int(time.time() * 1000)
        if get_system_state(conn, "last_processed_timestamp_ms") is None:
            set_system_state(conn, "last_processed_timestamp_ms", "0")
        if get_system_state(conn, "last_processed_event_key") is None:
            set_system_state(conn, "last_processed_event_key", "")
        if get_system_state(conn, "safety_mode") is None:
            set_system_state(conn, "safety_mode", "ARMED_SAFE")
        if get_system_state(conn, "safety_reason_code") is None:
            set_system_state(conn, "safety_reason_code", "BOOTSTRAP")
        if get_system_state(conn, "safety_reason_message") is None:
            set_system_state(conn, "safety_reason_message", "Initial bootstrap state")
        if get_system_state(conn, "safety_changed_at_ms") is None:
            set_system_state(conn, "safety_changed_at_ms", str(now_ms))

    @staticmethod
    def _initialize_services(conn) -> dict[str, object]:
        def safety_mode_provider() -> str:
            return get_system_state(conn, "safety_mode") or "ARMED_SAFE"

        safety_service = SafetyService(safety_mode_provider=safety_mode_provider)
        execution_service = ExecutionService(
            pre_hooks=[safety_service.pre_execution_check],
            post_hooks=[safety_service.post_execution_check],
        )
        decision_service = DecisionService(safety_mode_provider=safety_mode_provider)
        ingest_service = IngestService()

        return {
            "safety": safety_service,
            "execution": execution_service,
            "decision": decision_service,
            "ingest": ingest_service,
            "pipeline": Pipeline(
                decision=decision_service,
                execution=execution_service,
                persistence=DbPersistence(conn),
            ),
        }

    @staticmethod
    def _run_single_cycle(services: dict[str, object], logger) -> None:
        ingest: IngestService = services["ingest"]  # type: ignore[assignment]
        pipeline: Pipeline = services["pipeline"]  # type: ignore[assignment]

        event = ingest.build_position_delta_event(
            symbol="BTCUSDT",
            tx_hash="boot",
            event_index=0,
            prev_target_net_position=0.0,
            next_target_net_position=0.01,
            is_replay=0,
        )
        results = pipeline.process_single_event(event)
        for result in results:
            logger.info(
                "boot_cycle_result",
                extra={
                    "correlation_id": result.correlation_id,
                    "status": result.status,
                },
            )

    def _run_loop(self, logger, metrics) -> None:
        logger.info("loop_start", extra={"interval_sec": self.loop_interval_sec})
        while True:
            metrics.emit("heartbeat", 1)
            logger.info("loop_tick")
            time.sleep(self.loop_interval_sec)
