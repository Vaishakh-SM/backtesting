"""Momentum and reversal.

They are one computation with opposite signs, so they are one class:
direction=+1 buys the winners, direction=-1 buys the losers.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from qrt.data.dividends import dividend_adjusted
from qrt.data.schema import ACTIONS, PRICES
from qrt.data.view import MarketView
from qrt.strategy.base import Strategy


class TrailingReturn(Strategy):
    def __init__(self, lookback_sessions: int = 60, direction: int = 1) -> None:
        if direction not in (1, -1):
            raise ValueError("direction must be +1 (momentum) or -1 (reversal)")
        if lookback_sessions < 1:
            raise ValueError("lookback_sessions must be at least 1")
        self._lookback_sessions = lookback_sessions
        self.direction = direction

    @property
    def lookback_sessions(self) -> int:
        return self._lookback_sessions

    def generate_signal(self, view: MarketView) -> Mapping[str, float]:
        prices = dividend_adjusted(view.read(PRICES), view.read(ACTIONS))

        first_last = (
            prices.sort("event_ts")
            .group_by("ticker")
            .agg(
                pl.col("adj_close").first().alias("first"),
                pl.col("adj_close").last().alias("last"),
                pl.len().alias("bars"),
            )
            # A name with one bar has no return to speak of.
            .filter(pl.col("bars") > 1)
        )

        return {
            row["ticker"]: self.direction * (row["last"] / row["first"] - 1.0)
            for row in first_last.iter_rows(named=True)
        }
