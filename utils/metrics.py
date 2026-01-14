"""
Lightweight in-memory metrics counters/timers with periodic snapshot printing.

This is deliberately simple: a process-local registry storing counters and timers.
It can later be swapped for Prometheus/OTLP without touching call sites.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Dict


class Metrics:
    def __init__(self):
        self.counters: Dict[str, float] = defaultdict(float)
        self.timers: Dict[str, list[float]] = defaultdict(list)

    def inc(self, name: str, value: float = 1.0, **labels):
        key = self._key(name, labels)
        self.counters[key] += value

    def observe(self, name: str, value: float, **labels):
        key = self._key(name, labels)
        self.timers[key].append(value)

    def snapshot(self) -> dict:
        stats = {}
        for k, v in self.counters.items():
            stats[k] = v
        for k, arr in self.timers.items():
            if not arr:
                continue
            stats[k] = {
                "count": len(arr),
                "avg": sum(arr) / len(arr),
                "p95": sorted(arr)[int(0.95 * len(arr)) - 1],
                "max": max(arr),
            }
        return stats

    def dump(self):
        print("[METRICS] " + json.dumps(self.snapshot(), ensure_ascii=False))

    @staticmethod
    def _key(name: str, labels: dict) -> str:
        if not labels:
            return name
        lbl = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}|{lbl}"


# singleton for convenience
metrics = Metrics()
