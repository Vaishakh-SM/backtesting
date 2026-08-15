"""Momentum and reversal.

They are one computation with opposite signs, so they are one class:
direction=+1 buys the winners, direction=-1 buys the losers.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from qrt.backtest.portfolio import Allocation, rank_weights
from qrt.data.dividends import dividend_adjusted
from qrt.data.schema import ACTIONS, PRICES
from qrt.data.view import MarketView
from qrt.strategy.base import Strategy


class TrailingReturn(Strategy):
    def __init__(
        self,
        lookback_sessions: int = 60,
        direction: int = 1,
        top_fraction: float = 0.2,
        bottom_fraction: float = 0.2,
    ) -> None:
        if direction not in (1, -1):
            raise ValueError("direction must be +1 (momentum) or -1 (reversal)")
        if lookback_sessions < 1:
            raise ValueError("lookback_sessions must be at least 1")
        self._lookback_sessions = lookback_sessions
        self.direction = direction
        self.top_fraction = top_fraction
        self.bottom_fraction = bottom_fraction

    @property
    def lookback_sessions(self) -> int:
        return self._lookback_sessions

    def allocate(self, view: MarketView) -> Allocation:
        """Rank on trailing return, hold the ends equal-weighted.

        Sizing is the strategy's to choose. This one uses only the ordering of
        the scores, so a name up 61% and one up 14% are held identically — a
        strategy that wants conviction to matter would size differently here
        without the engine knowing or caring.
        """
        return rank_weights(self._scores(view), self.top_fraction, self.bottom_fraction)

    def _scores(self, view: MarketView) -> Mapping[str, float]:
        """Return over the window, signed by direction."""
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
