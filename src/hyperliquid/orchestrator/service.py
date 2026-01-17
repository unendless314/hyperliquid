from __future__ import annotations

import time
from dataclasses import dataclass

from hyperliquid.common.logging import setup_logging
from hyperliquid.common.metrics import MetricsEmitter
from hyperliquid.common.models import CONTRACT_VERSION, assert_contract_version
from hyperliquid.common.settings import Settings, compute_config_hash
from hyperliquid.storage.db import assert_schema_version, get_system_state, init_db, set_system_state


@dataclass
class Orchestrator:
    settings: Settings
    mode: str

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

            logger.info("boot_complete", extra={"mode": self.mode})
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
