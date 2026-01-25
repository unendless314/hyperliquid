from __future__ import annotations

import signal
import time
from typing import List, Optional
from dataclasses import dataclass

from hyperliquid.common.logging import setup_logging
from hyperliquid.common.metrics import MetricsEmitter
from hyperliquid.common.models import (
    CONTRACT_VERSION,
    PositionDeltaEvent,
    PriceSnapshot,
    assert_contract_version,
    normalize_execution_symbol,
)
from hyperliquid.common.pipeline import Pipeline
from hyperliquid.common.settings import Settings, compute_config_hash
from hyperliquid.decision.config import DecisionConfig
from hyperliquid.decision.service import DecisionService
from hyperliquid.decision.types import DecisionInputs
from hyperliquid.execution.adapters.binance import (
    AdapterNotImplementedError,
    BinanceExecutionAdapter,
    BinanceExecutionConfig,
)
from hyperliquid.execution.service import ExecutionService, ExecutionServiceConfig
from hyperliquid.ingest.coordinator import IngestCoordinator
from hyperliquid.ingest.service import IngestService, RawPositionEvent
from hyperliquid.safety.reconcile import PositionSnapshot, ReconciliationResult
from hyperliquid.safety.service import SafetyService
from hyperliquid.storage.db import assert_schema_version, get_system_state, init_db, set_system_state
from hyperliquid.storage.positions import load_local_positions_from_orders
from hyperliquid.storage.safety import load_safety_state, set_safety_state
from hyperliquid.storage.persistence import DbPersistence


@dataclass
class Orchestrator:
    settings: Settings
    mode: str
    emit_boot_event: bool = True
    run_loop: bool = False
    loop_interval_sec: Optional[int] = None

    def run(self) -> None:
        logger = setup_logging(self.settings.app_log_path, self.settings.log_level)
        metrics = MetricsEmitter(self.settings.metrics_log_path)
        conn = None
        audit_recorder = None
        try:
            logger.info("boot_start")
            conn = init_db(self.settings.db_path)
            audit_recorder = DbPersistence(conn).record_audit
            assert_schema_version(conn)

            config_hash = compute_config_hash(self.settings.config_path)
            self._handle_config_hash(conn, config_hash, logger, audit_recorder=audit_recorder)
            self._record_config(conn, config_hash, audit_recorder=audit_recorder)
            self._ensure_bootstrap_state(conn)
            services = self._initialize_services(conn, logger, audit_recorder=audit_recorder)
            self._run_startup_reconcile(
                services, conn, logger, metrics, audit_recorder=audit_recorder
            )
            if get_system_state(conn, "safety_mode") == "HALT":
                logger.warning("boot_halted")
                if not self.run_loop:
                    return
            if self.emit_boot_event and get_system_state(conn, "safety_mode") != "HALT":
                self._run_single_cycle(services, conn, logger, audit_recorder=audit_recorder)
            logger.info("boot_complete", extra={"mode": self.mode})
            if self.run_loop:
                self._run_loop(services, conn, logger, metrics, audit_recorder=audit_recorder)
            metrics.emit("cursor_lag_ms", 0)
        except AdapterNotImplementedError as exc:
            if conn is not None:
                set_safety_state(
                    conn,
                    mode="HALT",
                    reason_code="EXECUTION_ADAPTER_NOT_IMPLEMENTED",
                    reason_message=str(exc),
                    audit_recorder=audit_recorder,
                )
            raise
        except RuntimeError as exc:
            if str(exc) == "SCHEMA_VERSION_MISMATCH" and conn is not None:
                set_safety_state(
                    conn,
                    mode="HALT",
                    reason_code="SCHEMA_VERSION_MISMATCH",
                    reason_message="DB schema version mismatch",
                    audit_recorder=audit_recorder,
                )
            raise
        except KeyboardInterrupt:
            logger.info("shutdown_requested")
        finally:
            metrics.close()
            if conn is not None:
                conn.close()

    @staticmethod
    def _handle_config_hash(
        conn, config_hash: str, logger, *, audit_recorder=None
    ) -> None:
        existing = get_system_state(conn, "config_hash")
        if existing and existing != config_hash:
            logger.warning("config_hash_changed", extra={"previous": existing})
            if get_system_state(conn, "safety_mode") == "HALT":
                return
            mode = get_system_state(conn, "safety_mode") or "ARMED_SAFE"
            set_safety_state(
                conn,
                mode=mode,
                reason_code="CONFIG_HASH_CHANGED",
                reason_message="Config hash changed; continuing per operator policy",
                audit_recorder=audit_recorder,
            )

    def _record_config(self, conn, config_hash: str, *, audit_recorder=None) -> None:
        set_system_state(conn, "config_hash", config_hash)
        set_system_state(conn, "config_version", self.settings.config_version)
        self._assert_contract_version(conn, audit_recorder=audit_recorder)
        set_system_state(conn, "contract_version", CONTRACT_VERSION)

    @staticmethod
    def _assert_contract_version(conn, *, audit_recorder=None) -> None:
        existing = get_system_state(conn, "contract_version")
        if existing:
            try:
                assert_contract_version(existing)
            except ValueError as exc:
                set_safety_state(
                    conn,
                    mode="HALT",
                    reason_code="CONTRACT_VERSION_MISMATCH",
                    reason_message=str(exc),
                    audit_recorder=audit_recorder,
                )
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

    def _initialize_services(self, conn, logger, *, audit_recorder=None) -> dict[str, object]:
        def safety_mode_provider() -> str:
            return get_system_state(conn, "safety_mode") or "ARMED_SAFE"

        def safety_state_updater(mode: str, reason_code: str, reason_message: str) -> None:
            set_safety_state(
                conn,
                mode=mode,
                reason_code=reason_code,
                reason_message=reason_message,
                audit_recorder=audit_recorder,
            )

        safety_service = SafetyService(safety_mode_provider=safety_mode_provider)
        persistence = DbPersistence(conn)
        execution_adapter = None
        binance_cfg = self.settings.raw.get("execution", {}).get("binance", {})
        if self.mode == "live" and binance_cfg.get("enabled", False):
            execution_adapter = BinanceExecutionAdapter(
                BinanceExecutionConfig.from_settings(self.settings.raw),
                logger=logger,
            )
        execution_service = ExecutionService(
            config=ExecutionServiceConfig.from_settings(self.settings.raw),
            pre_hooks=[safety_service.pre_execution_check],
            post_hooks=[safety_service.post_execution_check],
            adapter=execution_adapter,
            result_provider=persistence.get_order_result,
            safety_state_updater=safety_state_updater,
            audit_recorder=audit_recorder,
            adapter_success_recorder=lambda: self._record_adapter_success(conn),
            adapter_error_recorder=lambda: self._record_adapter_error(conn),
        )
        decision_config = DecisionConfig.from_settings(self.settings.raw)

        def price_provider(symbol: str) -> PriceSnapshot | None:
            adapter = execution_service.adapter
            fetcher = getattr(adapter, "fetch_mark_price", None)
            if adapter is None or not callable(fetcher):
                return None
            try:
                price = float(fetcher(symbol))
            except Exception:
                return None
            return PriceSnapshot(price=price, timestamp_ms=int(time.time() * 1000), source="adapter")

        def filters_provider(symbol: str):
            adapter = execution_service.adapter
            fetcher = getattr(adapter, "fetch_symbol_filters", None)
            if adapter is None or not callable(fetcher):
                return None
            try:
                return fetcher(symbol)
            except Exception:
                return None

        def decision_inputs_provider(event: PositionDeltaEvent) -> DecisionInputs:
            safety_mode = safety_mode_provider()
            positions = load_local_positions_from_orders(conn)
            symbol_key = normalize_execution_symbol(event.symbol)
            local_position = float(positions.get(symbol_key, 0.0))
            expected_price = None
            if event.expected_price is not None:
                expected_price = PriceSnapshot(
                    price=float(event.expected_price),
                    timestamp_ms=int(
                        event.expected_price_timestamp_ms
                        if event.expected_price_timestamp_ms is not None
                        else event.timestamp_ms
                    ),
                    source="ingest",
                )
            return DecisionInputs(
                safety_mode=safety_mode,
                local_current_position=local_position,
                closable_qty=abs(local_position),
                expected_price=expected_price,
            )

        decision_service = DecisionService(
            config=decision_config,
            safety_mode_provider=safety_mode_provider,
            replay_policy_provider=lambda: decision_config.replay_policy,
            price_provider=price_provider,
            filters_provider=filters_provider,
            logger=logger,
        )
        ingest_service = IngestService()

        return {
            "safety": safety_service,
            "execution": execution_service,
            "decision": decision_service,
            "ingest": ingest_service,
            "pipeline": Pipeline(
                decision=decision_service,
                execution=execution_service,
                decision_inputs_provider=decision_inputs_provider,
                persistence=persistence,
            ),
        }

    def _run_startup_reconcile(
        self, services: dict[str, object], conn, logger, metrics, *, audit_recorder=None
    ) -> None:
        safety_config = self.settings.raw.get("safety", {})
        startup_policy = str(safety_config.get("startup_policy", "manual")).lower()
        allow_auto_promote = startup_policy in ("auto", "auto_promote", "auto-promote")
        self._run_reconcile(
            services,
            conn,
            logger,
            metrics,
            allow_auto_promote=allow_auto_promote,
            context="startup",
            audit_recorder=audit_recorder,
        )

    def _run_reconcile(
        self,
        services: dict[str, object],
        conn,
        logger,
        metrics,
        *,
        allow_auto_promote: bool,
        context: str,
        audit_recorder=None,
    ) -> tuple[ReconciliationResult | None, ReconciliationResult | None]:
        safety: SafetyService = services["safety"]  # type: ignore[assignment]
        execution: ExecutionService = services["execution"]  # type: ignore[assignment]

        adapter = execution.adapter
        if adapter is None:
            logger.info("reconcile_skipped", extra={"context": context, "reason": "no_adapter"})
            return None, None

        try:
            exchange_positions, exchange_ts_ms = adapter.fetch_positions()
            self._record_adapter_success(conn)
        except AdapterNotImplementedError as exc:
            logger.info(
                "reconcile_skipped",
                extra={
                    "context": context,
                    "reason": "adapter_not_implemented",
                    "error": str(exc),
                },
            )
            self._record_adapter_error(conn)
            return None, None
        except Exception as exc:
            logger.warning(
                "reconcile_failed",
                extra={"context": context, "error": str(exc)},
            )
            self._record_adapter_error(conn)
            if context == "startup":
                set_safety_state(
                    conn,
                    mode="HALT",
                    reason_code="RECONCILE_FAILED",
                    reason_message="Startup reconciliation failed",
                    audit_recorder=audit_recorder,
                )
            metrics.emit(
                "reconcile_failed",
                1,
                tags={"context": context},
            )
            return None, None

        now_ms = int(time.time() * 1000)
        local_positions = load_local_positions_from_orders(conn)
        local_snapshot = PositionSnapshot(
            source="local",
            positions=local_positions,
            timestamp_ms=now_ms,
        )
        exchange_snapshot = PositionSnapshot(
            source="exchange",
            positions=exchange_positions,
            timestamp_ms=exchange_ts_ms,
        )

        safety_config = self.settings.raw.get("safety", {})
        warn_threshold = float(safety_config.get("warn_threshold", 0.0))
        critical_threshold = float(safety_config.get("critical_threshold", 0.0))
        snapshot_max_stale_ms = int(safety_config.get("snapshot_max_stale_ms", 0))
        current_state = load_safety_state(conn)

        raw_result = safety.reconcile_snapshots(
            local_snapshot=local_snapshot,
            exchange_snapshot=exchange_snapshot,
            warn_threshold=warn_threshold,
            critical_threshold=critical_threshold,
            snapshot_max_stale_ms=snapshot_max_stale_ms,
            current_state=None,
            allow_auto_promote=allow_auto_promote,
        )
        result = safety.reconcile_snapshots(
            local_snapshot=local_snapshot,
            exchange_snapshot=exchange_snapshot,
            warn_threshold=warn_threshold,
            critical_threshold=critical_threshold,
            snapshot_max_stale_ms=snapshot_max_stale_ms,
            current_state=current_state,
            allow_auto_promote=allow_auto_promote,
        )
        set_safety_state(
            conn,
            mode=result.mode,
            reason_code=result.reason_code,
            reason_message=result.reason_message,
            audit_recorder=audit_recorder,
        )
        logger.info(
            "reconcile_result",
            extra={
                "context": context,
                "mode": result.mode,
                "reason_code": result.reason_code,
                "max_drift": result.report.max_drift,
            },
        )
        metrics.emit(
            "reconcile_max_drift",
            result.report.max_drift,
            tags={"context": context, "mode": result.mode, "reason": result.reason_code},
        )
        return result, raw_result

    @staticmethod
    def _record_adapter_success(conn) -> None:
        set_system_state(conn, "adapter_last_success_ms", str(int(time.time() * 1000)))

    @staticmethod
    def _record_adapter_error(conn) -> None:
        set_system_state(conn, "adapter_last_error_ms", str(int(time.time() * 1000)))

    def _run_single_cycle(
        self, services: dict[str, object], conn, logger, *, audit_recorder=None
    ) -> None:
        ingest: IngestService = services["ingest"]  # type: ignore[assignment]
        pipeline: Pipeline = services["pipeline"]  # type: ignore[assignment]

        events = self._ingest_external_once(
            ingest, conn, logger, audit_recorder=audit_recorder
        )
        if events is None:
            raw_event = RawPositionEvent(
                symbol="BTCUSDT",
                tx_hash="boot",
                event_index=0,
                prev_target_net_position=0.0,
                next_target_net_position=0.01,
                is_replay=0,
            )
            events = ingest.ingest_raw_events([raw_event], conn)
        if not events:
            return
        results = pipeline.process_events(events)
        for result in results:
            logger.info(
                "boot_cycle_result",
                extra={
                    "correlation_id": result.correlation_id,
                    "status": result.status,
                },
            )

    def _ingest_external_once(
        self, ingest: IngestService, conn, logger, *, audit_recorder=None
    ) -> Optional[List[PositionDeltaEvent]]:
        ingest_config = self.settings.raw.get("ingest", {})
        hyperliquid_cfg = ingest_config.get("hyperliquid", {})
        if not hyperliquid_cfg.get("enabled", False):
            return None
        coordinator = IngestCoordinator.from_settings(
            self.settings, ingest, logger, audit_recorder=audit_recorder
        )
        return coordinator.run_once(conn, mode=self.mode)

    def _run_loop(
        self,
        services: dict[str, object],
        conn,
        logger,
        metrics,
        *,
        audit_recorder=None,
        max_ticks: Optional[int] = None,
    ) -> None:
        pipeline: Pipeline = services["pipeline"]  # type: ignore[assignment]
        ingest: IngestService = services["ingest"]  # type: ignore[assignment]
        ingest_config = self.settings.raw.get("ingest", {})
        hyperliquid_cfg = ingest_config.get("hyperliquid", {})
        coordinator = None
        if hyperliquid_cfg.get("enabled", False):
            coordinator = IngestCoordinator.from_settings(
                self.settings, ingest, logger, audit_recorder=audit_recorder
            )

        loop_cfg = self.settings.raw.get("orchestrator", {})
        idle_sleep_sec = int(loop_cfg.get("loop_idle_sleep_sec", 1))
        max_idle_sleep_sec = int(loop_cfg.get("loop_max_idle_sleep_sec", 10))
        active_sleep_sec = int(loop_cfg.get("loop_active_sleep_sec", 0))
        heartbeat_sec = int(loop_cfg.get("loop_heartbeat_sec", 10))
        tick_warn_sec = int(loop_cfg.get("loop_tick_warn_sec", 30))
        if self.loop_interval_sec is not None:
            idle_sleep_sec = self.loop_interval_sec

        idle_sleep_sec = max(idle_sleep_sec, 1)
        max_idle_sleep_sec = max(max_idle_sleep_sec, idle_sleep_sec)
        active_sleep_sec = max(active_sleep_sec, 0)
        heartbeat_ms = max(heartbeat_sec, 1) * 1000
        tick_warn_ms = max(tick_warn_sec, 1) * 1000

        logger.info(
            "loop_start",
            extra={
                "idle_sleep_sec": idle_sleep_sec,
                "max_idle_sleep_sec": max_idle_sleep_sec,
                "active_sleep_sec": active_sleep_sec,
                "heartbeat_sec": heartbeat_sec,
                "tick_warn_sec": tick_warn_sec,
            },
        )

        safety_config = self.settings.raw.get("safety", {})
        reconcile_interval_sec = int(safety_config.get("reconcile_interval_sec", 0))
        next_reconcile_ms = int(time.time() * 1000)
        last_heartbeat_ms = 0
        idle_backoff_sec = idle_sleep_sec
        tick_count = 0
        stop_requested = False
        halt_noncritical_required = 3
        halt_recovery_window_ms = 60_000
        halt_allowlist = {
            "SNAPSHOT_STALE",
            "BACKFILL_WINDOW_EXCEEDED",
            "RECONCILE_CRITICAL",
        }

        def _handle_signal(signum, _frame) -> None:
            nonlocal stop_requested
            stop_requested = True
            logger.info("loop_stop_requested", extra={"signal": signum})

        prev_int = signal.getsignal(signal.SIGINT)
        prev_term = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        try:
            while True:
                if stop_requested:
                    break
                if max_ticks is not None and tick_count >= max_ticks:
                    break
                tick_count += 1

                tick_start_ms = int(time.time() * 1000)
                set_system_state(conn, "loop_last_tick_started_ms", str(tick_start_ms))

                now_ms = tick_start_ms
                raw_reconcile = None
                if reconcile_interval_sec > 0 and now_ms >= next_reconcile_ms:
                    _, raw_reconcile = self._run_reconcile(
                        services,
                        conn,
                        logger,
                        metrics,
                        allow_auto_promote=False,
                        context="loop",
                        audit_recorder=audit_recorder,
                    )
                    next_reconcile_ms = now_ms + reconcile_interval_sec * 1000

                metrics.emit("heartbeat", 1)

                safety_state = load_safety_state(conn)
                safety_mode = safety_state.mode if safety_state is not None else "ARMED_SAFE"
                safety_reason = safety_state.reason_code if safety_state is not None else ""

                if safety_mode == "HALT":
                    noncritical_count = int(
                        get_system_state(conn, "halt_recovery_noncritical_count") or 0
                    )
                    if raw_reconcile is None:
                        noncritical_count = 0
                    elif raw_reconcile.reason_code in ("OK", "RECONCILE_WARN"):
                        noncritical_count += 1
                    else:
                        noncritical_count = 0
                    set_system_state(
                        conn,
                        "halt_recovery_noncritical_count",
                        str(noncritical_count),
                    )

                    if self._should_auto_recover_halt(
                        conn,
                        now_ms=now_ms,
                        safety_reason=safety_reason,
                        raw_reconcile=raw_reconcile,
                        noncritical_count=noncritical_count,
                        allowlist=halt_allowlist,
                        window_ms=halt_recovery_window_ms,
                        required_noncritical=halt_noncritical_required,
                    ):
                        logger.warning(
                            "halt_auto_recovery",
                            extra={
                                "reason_code": safety_reason,
                                "noncritical_count": noncritical_count,
                            },
                        )
                        metrics.emit(
                            "halt_auto_recovery",
                            1,
                            tags={"reason_code": safety_reason},
                        )
                        set_safety_state(
                            conn,
                            mode="ARMED_SAFE",
                            reason_code="HALT_RECOVERY_AUTO",
                            reason_message="Auto-recovered to reduce-only after HALT",
                            audit_recorder=audit_recorder,
                        )
                        set_system_state(conn, "halt_recovery_noncritical_count", "0")
                        safety_mode = "HALT"
                else:
                    set_system_state(conn, "halt_recovery_noncritical_count", "0")

                events: List[PositionDeltaEvent] = []
                if coordinator is not None and safety_mode != "HALT":
                    events = coordinator.run_once(conn, mode=self.mode)

                if safety_mode == "HALT":
                    logger.info(
                        "loop_tick",
                        extra={
                            "event_count": len(events),
                            "result_count": 0,
                            "safety_mode": safety_mode,
                        },
                    )
                    try:
                        time.sleep(idle_backoff_sec)
                    except KeyboardInterrupt:
                        stop_requested = True
                    idle_backoff_sec = min(max_idle_sleep_sec, idle_backoff_sec * 2)
                elif events:
                    results = pipeline.process_events(events)
                    logger.info(
                        "loop_tick",
                        extra={
                            "event_count": len(events),
                            "result_count": len(results),
                        },
                    )
                    idle_backoff_sec = idle_sleep_sec
                    if active_sleep_sec > 0:
                        try:
                            time.sleep(active_sleep_sec)
                        except KeyboardInterrupt:
                            stop_requested = True
                else:
                    logger.info(
                        "loop_idle",
                        extra={
                            "sleep_sec": idle_backoff_sec,
                        },
                    )
                    try:
                        time.sleep(idle_backoff_sec)
                    except KeyboardInterrupt:
                        stop_requested = True
                    idle_backoff_sec = min(max_idle_sleep_sec, idle_backoff_sec * 2)

                tick_end_ms = int(time.time() * 1000)
                set_system_state(conn, "loop_last_tick_ms", str(tick_end_ms))
                tick_duration_ms = tick_end_ms - tick_start_ms
                if tick_duration_ms >= tick_warn_ms:
                    logger.warning(
                        "loop_tick_slow",
                        extra={"duration_ms": tick_duration_ms},
                    )
                metrics.emit("loop_tick_duration_ms", tick_duration_ms)

                if tick_end_ms - last_heartbeat_ms >= heartbeat_ms:
                    metrics.emit("loop_alive", 1)
                    logger.info("loop_heartbeat", extra={"last_tick_ms": tick_end_ms})
                    last_heartbeat_ms = tick_end_ms
        finally:
            signal.signal(signal.SIGINT, prev_int)
            signal.signal(signal.SIGTERM, prev_term)
            logger.info("loop_stop_complete", extra={"ticks": tick_count})

    def _should_auto_recover_halt(
        self,
        conn,
        *,
        now_ms: int,
        safety_reason: str,
        raw_reconcile: ReconciliationResult | None,
        noncritical_count: int,
        allowlist: set[str],
        window_ms: int,
        required_noncritical: int,
    ) -> bool:
        if safety_reason not in allowlist:
            return False
        if raw_reconcile is None:
            return False
        if raw_reconcile.reason_code == "SNAPSHOT_STALE":
            return False
        last_success_ms = int(get_system_state(conn, "adapter_last_success_ms") or 0)
        last_error_ms = int(get_system_state(conn, "adapter_last_error_ms") or 0)
        if now_ms - last_success_ms > window_ms:
            return False
        if last_error_ms and now_ms - last_error_ms <= window_ms:
            return False
        if safety_reason == "RECONCILE_CRITICAL":
            return noncritical_count >= required_noncritical
        if safety_reason == "BACKFILL_WINDOW_EXCEEDED":
            ingest_cfg = self.settings.raw.get("ingest", {})
            if not ingest_cfg.get("maintenance_skip_gap", False):
                return False
            maintenance_applied = get_system_state(conn, "maintenance_skip_applied_ms")
            return maintenance_applied is not None
        return True
