"""Dividend adjustment.

On an ex-date the price drops by roughly the dividend, so raw closes read every
distribution as a loss. XOM over 10-15 May 2024, around a $0.95 dividend:

    raw close    117.96 -> 118.58    +0.53%
    adj_close    117.01 -> 118.58    +1.34%

The holder earned 1.34%. XOM pays quarterly, so unadjusted returns understate
it by ~3.5% a year — a standing bias against high yielders in exactly the
cross-sectional rank this platform exists to run.

A plain function rather than a method on the view, so it can be tested against
hand-computed cases on its own. Splits are not handled: Yahoo already
back-adjusts for those (see yahoo.py).
"""

from __future__ import annotations

import polars as pl


def adjust(prices: pl.DataFrame, actions: pl.DataFrame) -> pl.DataFrame:
    """Return `prices` with an `adj_close` column.

    Back-adjusted: the latest bar keeps its quoted close, and every earlier bar
    is scaled by `1 - d / close(D-1)` for each dividend `d` with ex-date `D`.
    Multiplicative, so several distributions compound.

    Levels are relative to the end of the window passed in and so are only
    comparable within it. Returns are not, and returns are all this is for.
    """
    if prices.is_empty():
        return prices.with_columns(pl.col("close").alias("adj_close"))

    dividends = actions.filter(pl.col("kind") == "dividend").select(
        "ticker", "event_ts", pl.col("value").alias("dividend")
    )

    return (
        prices.sort("ticker", "event_ts")
        .join(dividends, on=["ticker", "event_ts"], how="left")
        .with_columns(
            # The reference is the close *before* the ex-date, which is the
            # price the drop is measured against.
            (1.0 - pl.col("dividend") / pl.col("close").shift(1).over("ticker"))
            # No dividend that day, or no prior bar to reference: no effect.
            .fill_null(1.0)
            .alias("_factor")
        )
        .with_columns(
            # Product of every factor strictly after this bar. A dividend
            # adjusts what came before it, never itself.
            pl.col("_factor")
            .reverse()
            .cum_prod()
            .reverse()
            .shift(-1)
            .fill_null(1.0)
            .over("ticker")
            .alias("_cumulative")
        )
        .with_columns((pl.col("close") * pl.col("_cumulative")).alias("adj_close"))
        .drop("dividend", "_factor", "_cumulative")
    )
