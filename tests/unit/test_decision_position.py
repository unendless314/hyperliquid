from hyperliquid.decision.position import reduce_only_for_action


def test_reduce_only_for_decrease() -> None:
    assert reduce_only_for_action("DECREASE") == 1


def test_reduce_only_for_increase() -> None:
    assert reduce_only_for_action("INCREASE") == 0


def test_reduce_only_for_flip_components() -> None:
    assert reduce_only_for_action("FLIP", "close") == 1
    assert reduce_only_for_action("FLIP", "open") == 0
