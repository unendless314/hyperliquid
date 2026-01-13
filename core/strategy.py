"""
Strategy (Processing Layer)
Performs symbol mapping, risk checks (price deviation, filters), position sizing, and produces OrderRequest objects.
Placeholder implementation.
"""


class Strategy:
    def __init__(self):
        # TODO: inject config, mapper, risk modules
        pass

    def process_event(self, event):
        # TODO: dedup already handled upstream; implement sizing and risk checks here
        raise NotImplementedError

