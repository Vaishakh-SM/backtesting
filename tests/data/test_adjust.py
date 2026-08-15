"""Adjustment, against numbers worked out by hand.

A 4-for-1 split looks like a 75% single-day loss to anything that ignores it,
so this is where a silent sign of nonsense enters a backtest.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="adjust not implemented yet")
def test_split_leaves_return_unchanged() -> None: ...


@pytest.mark.skip(reason="adjust not implemented yet")
def test_dividend_is_added_back() -> None: ...


@pytest.mark.skip(reason="adjust not implemented yet")
def test_no_actions_leaves_prices_untouched() -> None: ...
