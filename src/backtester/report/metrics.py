"""What a PM needs to decide whether this is worth pursuing.

A metric is a function from a result to a number, plus enough about itself to
be rendered. Adding one means writing the function and adding a line to
METRICS — there is no base class, because nothing dispatches on a metric at
runtime.

Separate from rendering because these are unit-testable against hand-computed
cases and HTML is not.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import polars as pl

from backtester.engine.spec import BacktestResult

DAYS_PER_YEAR = 365.25

# No risk-free rate. A dollar-neutral book funds itself to a first
# approximation, and no financing is modelled — see docs/ASSUMPTIONS.md. A
# non-zero rate would have to be subtracted consistently from gross and net.
RISK_FREE = 0.0


@dataclass(frozen=True)
class Metric:
    """One number, and what a reader needs to make sense of it."""

    key: str
    label: str
    compute: Callable[[BacktestResult], float]
    unit: str = "ratio"  # "ratio" | "percent"
    higher_is_better: bool | None = True  # None where neither is better
    note: str = ""


# --- helpers ---------------------------------------------------------------


def _years(result: BacktestResult) -> float:
    """Calendar years the book was actually held.

    Measured from the data rather than from the spec, because rebalances
    without enough history are skipped and the first position may open well
    after the requested start.
    """
    r = result.returns
    first, last = r["held_from"].min(), r["held_to"].max()
    assert isinstance(first, datetime) and isinstance(last, datetime)
    return max((last - first).days / DAYS_PER_YEAR, 1e-9)


def _periods_per_year(result: BacktestResult) -> float:
    """Inferred from the data, so monthly, weekly and daily runs all annualise
    correctly without being told which they are."""
    return result.returns.height / _years(result)


def _compound(returns: pl.Series) -> float:
    total = 1.0
    for r in returns:
        total *= 1.0 + float(r)
    return total


def _cagr(growth: float, years: float) -> float:
    if growth <= 0:
        # A book that lost everything has no meaningful growth rate.
        return -1.0
    return growth ** (1.0 / years) - 1.0


def _number(value: object) -> float:
    """Polars aggregations are typed loosely enough that every caller would
    otherwise repeat this. A missing or non-numeric result means there was
    nothing to aggregate, which is zero for our purposes."""
    return float(value) if isinstance(value, int | float) else 0.0


def _annualised_sharpe(returns: pl.Series, periods_per_year: float) -> float:
    deviation = _number(returns.std())
    if not deviation:
        return 0.0
    excess = _number(returns.mean()) - RISK_FREE / periods_per_year
    return excess / deviation * periods_per_year**0.5


# --- the metrics -----------------------------------------------------------


def net_sharpe(result: BacktestResult) -> float:
    """Return per unit of risk, after costs.

    The headline. Annualised from whatever the rebalance frequency happens to
    be, with a zero risk-free rate.
    """
    return _annualised_sharpe(result.returns["net_return"], _periods_per_year(result))


def annualised_return(result: BacktestResult) -> float:
    """Compound growth rate of the book, after costs."""
    return _cagr(float(result.returns["equity"][-1]), _years(result))


def annualised_volatility(result: BacktestResult) -> float:
    """How bumpy the ride is. Sharpe alone does not say whether this is a 2%
    or a 20% vol strategy, which decides how much capital it can take."""
    return _number(result.returns["net_return"].std()) * _periods_per_year(result) ** 0.5


def max_drawdown(result: BacktestResult) -> float:
    """Worst peak-to-trough fall in the equity curve.

    Survivability rather than performance: a high Sharpe with a drawdown
    nobody could sit through is not a strategy anyone runs.
    """
    equity = result.returns["equity"]
    drawdown = equity / equity.cum_max() - 1.0
    return _number(drawdown.min())


def cost_drag(result: BacktestResult) -> float:
    """Annualised return given up to trading — gross CAGR minus net CAGR.

    The most common way a backtest flatters itself. This book turns over
    roughly its whole notional every rebalance, so the number is not small,
    and a strategy that only works at zero cost should be visibly so.
    """
    years = _years(result)
    gross = _cagr(_compound(result.returns["gross_return"]), years)
    return gross - _cagr(float(result.returns["equity"][-1]), years)


def long_leg_contribution(result: BacktestResult) -> float:
    """Share of gross P&L earned by the long side.

    A spread trade should draw from both legs. Near 1.0 or near 0.0 means one
    leg is carrying the strategy and the other is a hedge that costs money —
    which is a different, and usually worse, proposition than the one being
    claimed.
    """
    long_pnl = _number(result.returns["long_pnl"].sum())
    short_pnl = _number(result.returns["short_pnl"].sum())
    total = abs(long_pnl) + abs(short_pnl)
    return long_pnl / total if total else 0.0


def mean_turnover(result: BacktestResult) -> float:
    """Gross notional traded per rebalance. Drives cost sensitivity, and is the
    first thing capacity depends on."""
    return _number(result.returns["turnover"].mean())


def hit_rate(result: BacktestResult) -> float:
    """Share of holding periods that made money. Distinguishes a strategy that
    works from one that had a good quarter."""
    net = result.returns["net_return"]
    return (net > 0).sum() / net.len() if net.len() else 0.0


METRICS: tuple[Metric, ...] = (
    Metric("net_sharpe", "Sharpe (net)", net_sharpe, note="Annualised, zero risk-free rate"),
    Metric(
        "annualised_return",
        "Return (net, annualised)",
        annualised_return,
        unit="percent",
    ),
    Metric(
        "annualised_volatility",
        "Volatility (annualised)",
        annualised_volatility,
        unit="percent",
        higher_is_better=False,
    ),
    Metric(
        "max_drawdown",
        "Max drawdown",
        max_drawdown,
        unit="percent",
        higher_is_better=True,  # closer to zero is better; the value is negative
        note="Worst peak-to-trough fall",
    ),
    Metric(
        "cost_drag",
        "Cost drag (annualised)",
        cost_drag,
        unit="percent",
        higher_is_better=False,
        note="Gross CAGR minus net CAGR",
    ),
    Metric(
        "long_leg_contribution",
        "Long leg share of P&L",
        long_leg_contribution,
        unit="percent",
        higher_is_better=None,
        note="0.5 means both legs contribute equally",
    ),
    Metric(
        "mean_turnover",
        "Turnover per rebalance",
        mean_turnover,
        higher_is_better=False,
        note="1.0 is the whole book",
    ),
    Metric("hit_rate", "Periods positive", hit_rate, unit="percent", higher_is_better=None),
)


def compute(result: BacktestResult) -> dict[str, float]:
    """Every metric, keyed for a report or a comparison table."""
    return {metric.key: metric.compute(result) for metric in METRICS}
