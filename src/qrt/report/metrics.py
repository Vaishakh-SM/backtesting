"""Numbers a PM would want. Separate from rendering, because these are
unit-testable and HTML is not."""

from __future__ import annotations

from collections.abc import Mapping

from qrt.backtest.spec import BacktestResult


def compute(result: BacktestResult) -> Mapping[str, float]:
    """Sharpe, CAGR, vol, max drawdown, turnover, cost drag, long vs short leg
    attribution, market beta."""
    raise NotImplementedError
