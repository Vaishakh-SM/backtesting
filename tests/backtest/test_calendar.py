"""Rebalance dates land on days the exchange was actually open."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="calendar not implemented yet")
def test_month_end_falls_on_a_trading_day() -> None:
    """31 Dec 2022 was a Saturday; the December rebalance is 30 Dec."""


@pytest.mark.skip(reason="calendar not implemented yet")
def test_holidays_are_excluded() -> None:
    """Thanksgiving and Good Friday are not sessions."""


@pytest.mark.skip(reason="calendar not implemented yet")
def test_early_closes_are_still_sessions() -> None: ...
