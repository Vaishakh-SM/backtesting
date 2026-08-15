"""Metrics, against numbers worked out by hand.

These are what a PM decides on, so being quietly wrong here is worse than being
wrong almost anywhere else — a bad Sharpe still looks like a Sharpe.

Built from a synthetic result rather than a real backtest: a metric is a pure
function of what the engine recorded, and testing it through a run would make
a failure ambiguous between the two.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl
import pytest

from backtester.engine.spec import BacktestResult, BacktestSpec
from backtester.report import metrics
from backtester.strategy.base import StrategyRef
from tests.conftest import ts

START = ts(2022, 1, 3)


def result_with(
    net: list[float],
    gross: list[float] | None = None,
    turnover: list[float] | None = None,
    long_pnl: list[float] | None = None,
    short_pnl: list[float] | None = None,
    days_per_period: int = 30,
) -> BacktestResult:
    """A result carrying exactly the columns metrics read."""
    n = len(net)
    gross = gross if gross is not None else list(net)
    equity, running = [], 1.0
    for r in net:
        running *= 1.0 + r
        equity.append(running)

    starts = [START + timedelta(days=i * days_per_period) for i in range(n)]
    return BacktestResult(
        spec=BacktestSpec(
            universe=("AAPL",),
            start=START,
            end=starts[-1],
            strategy=StrategyRef("trailing_return"),
            as_of_knowledge=ts(2026, 1, 1),
        ),
        knowledge_ts=ts(2026, 1, 1),
        reproducible=True,
        scores=pl.DataFrame(),
        positions=pl.DataFrame(),
        returns=pl.DataFrame(
            {
                "rebalance_ts": starts,
                "held_from": starts,
                "held_to": [s + timedelta(days=days_per_period) for s in starts],
                "turnover": turnover or [1.0] * n,
                "long_pnl": long_pnl or [g / 2 for g in gross],
                "short_pnl": short_pnl or [g / 2 for g in gross],
                "gross_return": gross,
                "cost": [g - x for g, x in zip(gross, net, strict=True)],
                "net_return": net,
                "equity": equity,
            }
        ),
    )


def test_max_drawdown_is_the_worst_peak_to_trough() -> None:
    """Equity 1.0 -> 1.5 -> 0.75. The fall is measured from the peak, not from
    the start, so it is -50% rather than -25%."""
    result = result_with([0.5, -0.5, 1 / 3])
    assert result.returns["equity"].to_list() == pytest.approx([1.5, 0.75, 1.0])
    assert metrics.max_drawdown(result) == pytest.approx(-0.5)


def test_a_curve_that_only_rises_has_no_drawdown() -> None:
    assert metrics.max_drawdown(result_with([0.01] * 5)) == pytest.approx(0.0)


def test_annualised_return_compounds_back_to_the_growth() -> None:
    """The invariant that defines it: growing at the reported rate for the
    reported time reproduces the final equity."""
    result = result_with([0.02] * 24)
    years = metrics._years(result)
    growth = result.returns["equity"][-1]
    assert (1 + metrics.annualised_return(result)) ** years == pytest.approx(growth)


def test_a_total_loss_does_not_produce_a_nonsense_growth_rate() -> None:
    """A negative base to a fractional power is not a number anyone wants
    printed in a report."""
    assert metrics.annualised_return(result_with([-1.0, 0.0])) == -1.0


def test_sharpe_scales_with_the_square_root_of_frequency() -> None:
    """The same returns arriving four times as often annualise to twice the
    Sharpe. Getting this wrong makes a daily strategy look better than a
    monthly one for no reason."""
    monthly = metrics.net_sharpe(result_with([0.02, -0.01] * 6, days_per_period=30))
    weekly = metrics.net_sharpe(result_with([0.02, -0.01] * 6, days_per_period=7))

    assert weekly / monthly == pytest.approx((30 / 7) ** 0.5, rel=1e-6)


def test_a_flat_return_series_has_no_sharpe() -> None:
    """Zero variance, so the ratio is undefined. Zero is the honest answer, not
    an infinity."""
    assert metrics.net_sharpe(result_with([0.01] * 5)) == 0.0


def test_volatility_annualises_from_the_data() -> None:
    net = [0.02, -0.01] * 6
    result = result_with(net, days_per_period=30)
    expected = pl.Series(net).std() * metrics._periods_per_year(result) ** 0.5
    assert metrics.annualised_volatility(result) == pytest.approx(expected)


def test_cost_drag_is_the_gap_between_gross_and_net() -> None:
    """A book earning 2% gross and 1% net per period gives up the difference,
    compounded and annualised."""
    result = result_with(net=[0.01] * 12, gross=[0.02] * 12)
    years = metrics._years(result)

    gross_cagr = (1.02**12) ** (1 / years) - 1
    net_cagr = (1.01**12) ** (1 / years) - 1
    assert metrics.cost_drag(result) == pytest.approx(gross_cagr - net_cagr)


def test_no_costs_means_no_drag() -> None:
    assert metrics.cost_drag(result_with([0.01] * 5)) == pytest.approx(0.0)


def test_leg_attribution_uses_real_per_leg_pnl() -> None:
    """Long side earns 6, short side earns 4, so the long leg is 60% of it.

    This has to come from the recorded per-leg P&L. Deriving it from weights
    gives exactly 50% every time, because the weights are half the gross per
    side by construction — a number that looks like information and is not.
    """
    result = result_with(
        net=[0.10] * 2,
        gross=[0.10] * 2,
        long_pnl=[0.03, 0.03],
        short_pnl=[0.02, 0.02],
    )
    assert metrics.long_leg_contribution(result) == pytest.approx(0.6)


def test_a_losing_short_leg_still_counts_toward_the_split() -> None:
    """Magnitudes, not signs: a hedge that costs money is still doing
    something, and a reader needs to see how much."""
    result = result_with(net=[0.05], gross=[0.05], long_pnl=[0.08], short_pnl=[-0.02])
    assert metrics.long_leg_contribution(result) == pytest.approx(0.8)


def test_hit_rate_counts_profitable_periods() -> None:
    assert metrics.hit_rate(result_with([0.01, -0.01, 0.01, 0.01])) == pytest.approx(0.75)


def test_mean_turnover_is_per_rebalance() -> None:
    assert metrics.mean_turnover(result_with([0.0] * 3, turnover=[1.0, 0.5, 0.6])) == pytest.approx(
        0.7
    )


def test_every_metric_produces_a_number() -> None:
    """The report renders whatever METRICS contains, so a new one that returns
    a null or a NaN would land in the output rather than fail here."""
    values = metrics.compute(result_with([0.02, -0.01] * 6))

    assert set(values) == {m.key for m in metrics.METRICS}
    for key, value in values.items():
        assert isinstance(value, float), key
        assert value == value, f"{key} is NaN"


def test_metrics_are_declared_once_and_uniquely() -> None:
    keys = [m.key for m in metrics.METRICS]
    assert len(keys) == len(set(keys))
