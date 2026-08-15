"""Walking a strategy over history."""

from __future__ import annotations

from qrt.backtest.spec import BacktestResult, BacktestSpec
from qrt.data.dataset import DatasetRef


def run_backtest(spec: BacktestSpec, ref: DatasetRef) -> BacktestResult:
    """Takes a spec and a location. Knows nothing about scheduling.

    Runs one query per rebalance, each fetching the lookback window ending at
    that rebalance, and hands the result to the strategy. The time bounds are
    in the query, so a strategy cannot see past them however it is written.

    Consecutive windows overlap, so rows are read more than once. That is
    accepted — docs/DESIGN_DECISIONS.md 14d-14f has the cost and the point at
    which it stops being acceptable.
    """
    raise NotImplementedError
