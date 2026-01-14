"""
Monitor (Ingestion Layer)
Responsible for WebSocket connection to Hyperliquid, cursor tracking, gap detection/backfill, and dedup gatekeeping.

Current implementation:
- Supports pluggable ws_client/rest_client (pass actual Hyperliquid SDK clients when available).
- Deduplicates on composite key (tx_hash/fillId/tradeId + event_index) before enqueueing.
- Persists cursor in system_state under key `last_processed_cursor` (uses block_height if present, else timestamp_ms).
- Emits heartbeat if no ws_client is provided (keeps pipeline alive for dry-run/dev).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import logging
from typing import Any, Optional, Callable

from utils.db import get_system_state, set_system_state, cleanup_processed_txs, DEFAULT_DEDUP_TTL_SECONDS

logger = logging.getLogger(__name__)


class Monitor:
    def __init__(
        self,
        queue: asyncio.Queue,
        db_conn,
        settings: dict,
        ws_client: Optional[Any] = None,
        ws_factory: Optional[Callable[[], Any]] = None,
        rest_client: Optional[Any] = None,
        backfill_window: int = 200,
        cursor_key: str = "last_processed_cursor",
        cursor_mode: str = "block",  # "block" or "timestamp"
        run_once: bool = False,
        dedup_ttl_seconds: int = DEFAULT_DEDUP_TTL_SECONDS,
        cleanup_interval_seconds: int = 300,
        notifier: Optional[Any] = None,
    ):
        self.queue = queue
        self.db_conn = db_conn
        self.ws_client = ws_client
        self.ws_factory = ws_factory
        self.rest_client = rest_client
        self.backfill_window = backfill_window
        self.settings = settings
        self._stopped = asyncio.Event()
        self.cursor_key = cursor_key
        self.cursor_mode = cursor_mode
        self.run_once = run_once
        self.dedup_ttl_seconds = dedup_ttl_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self._cleanup_task: Optional[asyncio.Task] = None
        self.notifier = notifier

    async def run(self):
        """
        Main entry: backfill (if client provided) then consume WS stream or emit heartbeats.
        """
        if self.cleanup_interval_seconds:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop(), name="monitor_cleanup")

        try:
            if self.rest_client:
                await self._maybe_gap_and_backfill()

            if self._stopped.is_set():
                return

            if self.ws_client:
                await self._consume_ws()
                return
            else:
                # Fallback: emit heartbeat to keep downstream alive in dev/dry-run
                while not self._stopped.is_set():
                    await self.queue.put({"type": "heartbeat", "source": "monitor", "ts": time.time()})
                    if self.run_once:
                        break
                    await asyncio.sleep(1)
        finally:
            if self._cleanup_task:
                self._cleanup_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._cleanup_task

    async def _consume_ws(self):
        """
        Consume messages from an async-iterable ws_client.
        Expect ws_client to yield dict events with keys:
          tx_hash, event_index, symbol, block_height, timestamp
        """
        backoff = 1.0
        max_backoff = 5.0
        while not self._stopped.is_set():
            try:
                async for raw in self.ws_client:
                    if self._stopped.is_set():
                        break
                    backoff = 1.0  # reset after successful receipt
                    await self._handle_raw_event(raw)
                break  # normal exit
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("monitor_ws_error", exc_info=exc)
                self._notify(f"[MONITOR][WS][RETRY] {exc}")
                await self._close_ws()
                if self.ws_factory:
                    try:
                        self.ws_client = self.ws_factory()
                    except Exception as create_exc:  # pragma: no cover - defensive
                        logger.error("monitor_ws_recreate_failed", exc_info=create_exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def _maybe_gap_and_backfill(self):
        """
        Detect cursor gap and perform REST backfill when within window.
        If gap exceeds window, halt to avoid trading on incomplete data.
        """
        last_cursor = self._get_cursor()

        # No prior cursor -> nothing to backfill
        if last_cursor is None:
            return

        try:
            latest = await self._call_rest("get_latest_cursor")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("monitor_get_latest_cursor_failed", exc_info=exc)
            return

        if latest is None:
            return

        try:
            last_cursor_int = int(last_cursor)
            latest_int = int(latest)
        except (TypeError, ValueError):
            logger.error(
                "monitor_cursor_non_numeric",
                extra={"last_cursor": last_cursor, "latest": latest, "mode": self.cursor_mode},
            )
            await self._halt(reason="cursor_unit_mismatch")
            return

        if not self._cursor_units_match(last_cursor_int, latest_int):
            logger.error(
                "monitor_cursor_unit_mismatch",
                extra={"last_cursor": last_cursor_int, "latest": latest_int, "mode": self.cursor_mode},
            )
            await self._halt(reason="cursor_unit_mismatch")
            return

        gap = latest_int - last_cursor_int
        if gap < 0:
            logger.warning("monitor_cursor_in_future", extra={"last_cursor": last_cursor_int, "latest": latest_int})
            return

        if gap == 0:
            return

        if gap > self.backfill_window:
            logger.error(
                "monitor_gap_exceeds_window",
                extra={"last_cursor": last_cursor_int, "latest": latest_int, "window": self.backfill_window},
            )
            await self._halt(reason="gap_exceeds_window")
            return

        try:
            events = await self._fetch_range(start_cursor=last_cursor_int + 1, end_cursor=latest_int)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("monitor_backfill_failed", exc_info=exc)
            return

        for ev in events:
            await self._handle_raw_event(ev)

        # Advance cursor even if no new events (already deduped) to avoid repeating the same backfill window
        self._set_cursor(latest_int)

    async def _handle_raw_event(self, raw: dict):
        # Hyperliquid user_fills do not include tx_hash/block_height; use fillId/tradeId + event_index surrogate keys
        tx_hash = raw.get("tx_hash") or raw.get("fillId") or raw.get("tradeId")
        event_index = raw.get("event_index", raw.get("hyperethIndex", 0)) or 0
        symbol = raw.get("symbol")
        block_height = raw.get("block_height") or raw.get("blockHeight")  # may be None for HL fills
        timestamp_ms = raw.get("timestamp") or raw.get("eventTime") or raw.get("dexProcessedTimestamp")
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)

        if not (tx_hash and symbol is not None):
            logger.warning("monitor_skip_malformed_event", extra={"event": raw})
            return

        if not self._dedup_and_record(tx_hash, event_index, symbol, block_height, timestamp_ms):
            return  # duplicate

        await self.queue.put(
            {
                "type": "fill",
                "tx_hash": tx_hash,
                "event_index": event_index,
                "symbol": symbol,
                "block_height": block_height,
                "timestamp": timestamp_ms,
                "price": raw.get("price"),
                "size": raw.get("quantity") or raw.get("size"),
                "quote_quantity": raw.get("quoteQuantity"),
                "side": raw.get("side"),
                "exchange_order_id": raw.get("orderId"),
                "client_order_id": raw.get("clientOrderId"),
            }
        )
        cursor_value = self._select_cursor_value(block_height, timestamp_ms)
        if cursor_value is not None:
            self._set_cursor(cursor_value)

    def _dedup_and_record(self, tx_hash, event_index, symbol, block_height, timestamp) -> bool:
        """
        Insert into processed_txs if not present; return True if inserted (new), False otherwise.
        """
        cur = self.db_conn.cursor()
        try:
            cur.execute(
                """
                INSERT OR IGNORE INTO processed_txs (tx_hash, event_index, symbol, block_height, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tx_hash, event_index, symbol, block_height, timestamp),
            )
            return cur.rowcount == 1
        finally:
            cur.close()

    async def stop(self):
        self._stopped.set()
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task

    def _get_cursor(self) -> Optional[int]:
        val = get_system_state(self.db_conn, self.cursor_key)
        return int(val) if val is not None else None

    def _set_cursor(self, cursor_value) -> None:
        set_system_state(self.db_conn, self.cursor_key, str(cursor_value))

    async def _halt(self, reason: str):
        """Stop monitor when safety conditions fail (e.g., gap too large)."""
        self._stopped.set()
        await self._close_ws()
        await self.queue.put({"type": "halt", "reason": reason})
        self._notify(f"[MONITOR][HALT] reason={reason}")

    async def _cleanup_loop(self):
        while not self._stopped.is_set():
            removed = cleanup_processed_txs(self.db_conn, self.dedup_ttl_seconds)
            if removed:
                logger.info("monitor_dedup_cleanup", extra={"removed": removed})
            await asyncio.sleep(self.cleanup_interval_seconds)

    async def _call_rest(self, method_name: str, *args, **kwargs):
        func: Optional[Callable] = getattr(self.rest_client, method_name, None)
        if not func:
            raise AttributeError(f"rest_client missing method {method_name}")
        result = func(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def _fetch_range(self, start_cursor: int, end_cursor: int):
        """
        Fetch events between cursors (inclusive start, inclusive end).
        Falls back to get_recent if fetch_range is unavailable.
        """
        try:
            return await self._call_rest("fetch_range", start_cursor, end_cursor)
        except AttributeError:
            # Fallback: attempt get_recent(limit, since_block=...)
            limit = (end_cursor - start_cursor) + 1
            return await self._call_rest("get_recent", limit, since_block=start_cursor - 1)

    def _select_cursor_value(self, block_height: Optional[int], timestamp_ms: Optional[int]) -> Optional[int]:
        """
        Choose cursor value based on configured mode to avoid mixing units.
        """
        if self.cursor_mode == "block":
            if block_height is None:
                logger.warning("monitor_missing_block_height_cursor_mode_block", extra={"timestamp_ms": timestamp_ms})
                return None
            return int(block_height)
        if self.cursor_mode == "timestamp":
            if timestamp_ms is None:
                logger.warning("monitor_missing_timestamp_cursor_mode_timestamp", extra={"block_height": block_height})
                return None
            return int(timestamp_ms)
        logger.error("monitor_invalid_cursor_mode", extra={"cursor_mode": self.cursor_mode})
        return None

    def _cursor_units_match(self, last_cursor: int, latest_cursor: int) -> bool:
        """
        Basic heuristic to prevent mixing block heights with millisecond timestamps.
        """
        if self.cursor_mode == "block":
            # block heights should be relatively small (<1e12)
            return last_cursor < 1e12 and latest_cursor < 1e12
        if self.cursor_mode == "timestamp":
            # timestamps in ms should be large (~1e12+ for 2026)
            return last_cursor > 1e11 and latest_cursor > 1e11
        return False

    async def _close_ws(self):
        if not self.ws_client:
            return
        close_fn = getattr(self.ws_client, "close", None) or getattr(self.ws_client, "aclose", None)
        if close_fn:
            res = close_fn()
            if asyncio.iscoroutine(res):
                with contextlib.suppress(Exception):
                    await res

    def _notify(self, message: str):
        if not self.notifier:
            return
        async def _send():
            try:
                await self.notifier.send(message)
            except Exception:  # pragma: no cover - defensive
                logger.exception("monitor_notify_failed")

        # fire-and-forget to avoid blocking ingest loop
        asyncio.create_task(_send())
