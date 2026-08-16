"""A strategy that is not just a sign flip of the shipped one, and a run of it.

Ranks by trailing return per unit of realised volatility, so a name that went
up on a smooth path beats one that went up on a wild path.

    python examples/custom_strategy.py

Needs data: `backtester ingest` first.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from backtester.config import load_universe
from backtester.conventions import CLOSE_HOUR, TZ
from backtester.data.dataset import DatasetRef
from backtester.data.polars_reader import latest_knowledge_ts
from backtester.data.schema import PRICES
from backtester.data.view import MarketView
from backtester.engine.runner import run_backtest
from backtester.engine.spec import BacktestSpec
from backtester.report.metrics import compute
from backtester.strategy import Allocation, Strategy, rank_weights


def at_close(year: int, month: int, day: int) -> datetime:
    """The engine works in exchange closes, so dates arrive as timestamps."""
    return datetime(year, month, day, CLOSE_HOUR, tzinfo=ZoneInfo(TZ))


class VolAdjustedMomentum(Strategy):
    """Trailing return divided by realised volatility."""

    def __init__(self, lookback_sessions: int = 60, top_fraction: float = 0.2) -> None:
        self._lookback_sessions = lookback_sessions
        self.top_fraction = top_fraction

    @property
    def lookback_sessions(self) -> int:
        """How much history allocate() needs. Sessions, not calendar days."""
        return self._lookback_sessions

    def allocate(self, view: MarketView) -> Allocation:
        return rank_weights(self._scores(view), self.top_fraction, self.top_fraction)

    def _scores(self, view: MarketView) -> Mapping[str, float]:
        prices = view.read(PRICES).sort("event_ts")

        stats = (
            prices.with_columns(pl.col("close").pct_change().over("ticker").alias("ret"))
            .group_by("ticker")
            .agg(
                (pl.col("close").last() / pl.col("close").first() - 1).alias("total"),
                pl.col("ret").std().alias("vol"),
            )
            .filter(pl.col("vol") > 0)
        )
        return {r["ticker"]: r["total"] / r["vol"] for r in stats.iter_rows(named=True)}


def main() -> None:
    ref = DatasetRef("./data/us-equities")
    # or ref = DatasetRef("s3://research/us-equities", {"region": "us-east-1"})

    universe = tuple(load_universe(Path("configs/universe.yaml")).tickers)

    # A live object, so no registration is needed. The result records that it
    # cannot be rebuilt from its own description — a worker elsewhere has no
    # way to look this class up.
    result = run_backtest(
        BacktestSpec(
            universe=universe,
            start=at_close(2020, 1, 1),
            end=at_close(2024, 12, 31),
            strategy=VolAdjustedMomentum(lookback_sessions=60),
            as_of_knowledge=latest_knowledge_ts(ref),
        ),
        ref,
    )

    metrics = compute(result)
    print(f"periods       {result.returns.height}")
    print(f"sharpe (net)  {metrics['net_sharpe']:.2f}")
    print(f"return  (ann) {metrics['annualised_return']:.1%}")
    print(f"max drawdown  {metrics['max_drawdown']:.1%}")
    print(f"reproducible  {result.reproducible}  (a live object cannot be named)")


if __name__ == "__main__":
    main()
