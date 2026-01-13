"""
Monitor (Ingestion Layer)
Responsible for WebSocket connection to Hyperliquid, cursor tracking, gap detection/backfill, and dedup gatekeeping.

Current implementation:
- Supports pluggable ws_client/rest_client (pass actual Hyperliquid SDK clients when available).
- Deduplicates on `processed_txs` (tx_hash + event_index + symbol) before enqueueing.
- Emits heartbeat if no ws_client is provided (keeps pipeline alive for dry-run/dev).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional


class Monitor:
    def __init__(
        self,
        queue: asyncio.Queue,
        db_conn,
        settings: dict,
        ws_client: Optional[Any] = None,
        rest_client: Optional[Any] = None,
        backfill_window: int = 200,
    ):
        self.queue = queue
        self.db_conn = db_conn
        self.ws_client = ws_client
        self.rest_client = rest_client
        self.backfill_window = backfill_window
        self.settings = settings
        self._stopped = asyncio.Event()

    async def run(self):
        """
        Main entry: backfill (if client provided) then consume WS stream or emit heartbeats.
        """
        if self.rest_client:
            await self._backfill()

        if self.ws_client:
            await self._consume_ws()
        else:
            # Fallback: emit heartbeat to keep downstream alive in dev/dry-run
            while not self._stopped.is_set():
                await self.queue.put({"type": "heartbeat", "source": "monitor", "ts": time.time()})
                await asyncio.sleep(1)

    async def _consume_ws(self):
        """
        Consume messages from an async-iterable ws_client.
        Expect ws_client to yield dict events with keys:
          tx_hash, event_index, symbol, block_height, timestamp
        """
        async for raw in self.ws_client:
            if self._stopped.is_set():
                break
            await self._handle_raw_event(raw)

    async def _backfill(self):
        """
        Placeholder backfill logic; expects rest_client.get_recent(limit) to return list of events.
        """
        try:
            events = await self.rest_client.get_recent(self.backfill_window)
        except Exception as exc:  # pragma: no cover - best effort
            print(f"[MONITOR] backfill failed: {exc}")
            return

        for ev in events:
            await self._handle_raw_event(ev)

    async def _handle_raw_event(self, raw: dict):
        tx_hash = raw.get("tx_hash")
        event_index = raw.get("event_index", 0)
        symbol = raw.get("symbol")
        block_height = raw.get("block_height")
        timestamp = raw.get("timestamp", int(time.time()))

        if not (tx_hash and symbol is not None and block_height is not None):
            print(f"[MONITOR] skip malformed event: {raw}")
            return

        if not self._dedup_and_record(tx_hash, event_index, symbol, block_height, timestamp):
            return  # duplicate

        await self.queue.put(
            {
                "type": "fill",
                "tx_hash": tx_hash,
                "event_index": event_index,
                "symbol": symbol,
                "block_height": block_height,
                "timestamp": timestamp,
            }
        )

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
