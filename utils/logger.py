"""
Structured logging helper.

Goals:
- JSON logs to stdout for easy ingestion.
- Correlation ID propagation via LoggerAdapter.
- Simple redaction hook to avoid leaking secrets.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import sys
from typing import Any, Dict, Optional

_SECRET_PATTERN = re.compile(r"([A-Za-z0-9]{24,})")


def _redact(value: str) -> str:
    # Heuristic redaction: mask long tokens (API keys, secrets)
    return _SECRET_PATTERN.sub("***REDACTED***", value)


class JsonFormatter(logging.Formatter):
    def __init__(self, mode: str = "live"):
        super().__init__()
        self.mode = mode

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": _dt.datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "lvl": record.levelname,
            "msg": _redact(str(record.getMessage())),
            "logger": record.name,
            "mode": self.mode,
        }
        # Include correlation_id and any extra keys
        for key, value in record.__dict__.items():
            if key in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
            }:
                continue
            if key == "exc_text":
                continue
            if key == "exc_info" and record.exc_info:
                continue
            payload[key] = value

        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def setup_logger(level: str = "INFO", mode: str = "live") -> None:
    level_value = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level_value)
    # Clear existing handlers to avoid duplicates in tests
    root.handlers.clear()
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter(mode=mode))
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: Optional[str] = None, correlation_id: Optional[str] = None, **extra) -> logging.LoggerAdapter:
    logger = logging.getLogger(name)
    context = dict(extra)
    if correlation_id:
        context["correlation_id"] = correlation_id
    return logging.LoggerAdapter(logger, context)
