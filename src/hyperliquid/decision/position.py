from __future__ import annotations


def reduce_only_for_action(action_type: str, component: str | None = None) -> int:
    if action_type == "DECREASE":
        return 1
    if action_type == "FLIP":
        if component == "close":
            return 1
        if component == "open":
            return 0
        return 1
    return 0
