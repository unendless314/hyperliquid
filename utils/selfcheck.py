"""
Startup self-checks for safety modes.
"""

from __future__ import annotations

import logging
from typing import Optional


logger = logging.getLogger(__name__)


class SelfCheckError(RuntimeError):
    pass


def ensure_no_external_writes(mode: str, ccxt_client: Optional[object]) -> None:
    """
    In dry-run/backfill-only modes, ensure no live ccxt client is injected.
    """
    if mode in {"dry-run", "backfill-only"} and ccxt_client is not None:
        raise SelfCheckError(f"mode={mode} must not receive ccxt_client (would enable external writes)")
