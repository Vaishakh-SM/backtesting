"""Momentum and reversal.

They are one computation with opposite signs, so they are one class:
direction=+1 buys the winners, direction=-1 buys the losers.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

import polars as pl

from qrt.data.adjust import adjust
from qrt.data.schema import ACTIONS, PRICES
from qrt.data.view import MarketView
from qrt.strategy.base import Strategy


class TrailingReturn(Strategy):
    def __init__(self, lookback_days: int = 60, direction: int = 1) -> None:
        if direction not in (1, -1):
            raise ValueError("direction must be +1 (momentum) or -1 (reversal)")
        self.lookback_days = lookback_days
        self.direction = direction

    @property
    def lookback(self) -> timedelta:
        # Calendar days. The window is a lower bound on what the engine
        # fetches, so asking for more calendar days than trading days is safe.
        return timedelta(days=self.lookback_days)

    def generate_signal(self, view: MarketView) -> Mapping[str, float]:
        prices = adjust(view.read(PRICES), view.read(ACTIONS))

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
