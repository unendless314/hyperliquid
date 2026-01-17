from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class MetricsEmitter:
    metrics_log_path: str

    def __post_init__(self) -> None:
        path = Path(self.metrics_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("a", encoding="utf-8")

    def emit(self, name: str, value: float, tags: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "name": name,
            "value": value,
            "tags": tags or {},
        }
        line = f"[METRICS] {json.dumps(payload, ensure_ascii=True)}"
        print(line, file=sys.stdout)
        self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
