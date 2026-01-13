"""
Executor (Action Layer)
Handles Order FSM, CCXT integration, smart retry with jitter, and idempotent clientOrderId.
Placeholder implementation.
"""


class Executor:
    def __init__(self):
        # TODO: inject exchange client, rate limiter, db handle
        pass

    async def submit(self, order_request):
        # TODO: implement FSM: submit -> monitor -> finalize; update SQLite
        raise NotImplementedError

