"""
Telegram / notification helper with rate limiting and circuit breaker.
Placeholder implementation.
"""


class Notifier:
    def __init__(self):
        # TODO: inject rate limiter, chat targets
        pass

    async def send(self, message: str):
        # TODO: implement with rate limiting and failure safeguards
        raise NotImplementedError

