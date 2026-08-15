"""Turning scores into positions, and charging for the trading.

Separate from the strategy on purpose: one signal has to be runnable under
several sizings and cost assumptions, which is what makes a sensitivity grid
cheap to produce. Keeping this out of the strategy is what allows that.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_TOLERANCE = 1e-9


@dataclass(frozen=True)
class TargetWeights:
    """Weights as a fraction of gross notional.

    The invariants are checked here because they are exactly what breaks
    silently: a book that has quietly stopped being neutral, or that has
    levered itself, still produces a plausible equity curve.
    """

    weights: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.weights:
            return
        net = sum(self.weights.values())
        gross = sum(abs(w) for w in self.weights.values())
        if abs(net) > _TOLERANCE:
            raise ValueError(f"not dollar neutral: net exposure {net}")
        if abs(gross - 1.0) > _TOLERANCE:
            raise ValueError(f"gross exposure {gross}, expected 1.0")


def rank_weights(
    scores: Mapping[str, float],
    top_fraction: float = 0.2,
    bottom_fraction: float = 0.2,
) -> TargetWeights:
    """Long the top fraction, short the bottom fraction, equal-weighted.

    Ties break by ticker, so a rerun on the same data gives the same book. The
    alternative is a portfolio that changes between runs for no reason anyone
    can see.

    Each leg carries half the gross, so the result is dollar neutral whether or
    not the legs hold the same number of names.
    """
    if not scores:
        return TargetWeights({})

    ranked = sorted(scores, key=lambda ticker: (-scores[ticker], ticker))

    n_long = max(1, int(len(ranked) * top_fraction))
    n_short = max(1, int(len(ranked) * bottom_fraction))
    if n_long + n_short > len(ranked):
        raise ValueError(
            f"{len(ranked)} names cannot fill a {top_fraction:.0%} long and "
            f"{bottom_fraction:.0%} short book without overlapping"
        )

    longs, shorts = ranked[:n_long], ranked[-n_short:]
    return TargetWeights({t: 0.5 / n_long for t in longs} | {t: -0.5 / n_short for t in shorts})


def turnover(previous: TargetWeights | None, new: TargetWeights) -> float:
    """Gross notional traded, as a fraction of book size.

    Every name in the new book counts against a starting position of zero, so
    the first rebalance turns over 1.0 — you have to buy the book before you
    can hold it.
    """
    before = previous.weights if previous else {}
    return sum(
        abs(new.weights.get(t, 0.0) - before.get(t, 0.0)) for t in set(before) | set(new.weights)
    )


def linear_cost(previous: TargetWeights | None, new: TargetWeights, bps: float) -> float:
    """Turnover times a fixed rate, as a fraction of book size.

    No market impact and no size dependence, so this says nothing about
    capacity — see docs/ASSUMPTIONS.md.
    """
    return turnover(previous, new) * bps / 10_000
