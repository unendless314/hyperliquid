"""
Monitor (Ingestion Layer)
Responsible for WebSocket connection to Hyperliquid, cursor tracking, gap detection/backfill, and dedup gatekeeping.
Placeholder implementation; wire per docs/SYSTEM_DESIGN.md.
"""


class Monitor:
    def __init__(self):
        # TODO: inject config, db handle, rate limiter
        pass

    async def run(self):
        # TODO: connect WS, detect gaps, backfill via REST, dedup and enqueue events
        raise NotImplementedError

