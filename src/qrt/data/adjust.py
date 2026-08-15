"""Split and dividend adjustment.

A plain function over what a view returns, not a method on the view, so it can
be tested against hand-computed cases on its own.

We store raw prices and derive this, rather than storing a vendor's adjusted
close. A vendor's adjusted series is restated on every dividend, which would
mean the whole price history silently changes underneath a finished backtest.

A strategy that skips this reads a 4-for-1 split as a 75% loss.
"""

from __future__ import annotations

import polars as pl


def adjust(prices: pl.DataFrame, actions: pl.DataFrame) -> pl.DataFrame:
    """Return prices with an `adj_close` column.

    Adjustment is backward-looking from the end of the window: the most recent
    bar is unadjusted and earlier bars are scaled, which is what makes returns
    within the window comparable across a corporate action.
    """
    raise NotImplementedError
