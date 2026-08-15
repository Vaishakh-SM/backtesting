"""What a strategy hands back, and helpers for building it.

Lives with the strategy rather than the engine because it is the strategy's
output type. Having it under qrt.backtest made the two packages import each
other, which worked only because of the order pytest happened to import them
in — `import qrt.strategy` on its own raised.

A strategy answers "given this moment, what should the book hold". Weight is
not a function of score once anything real is involved — volatility scaling,
position caps, correlated names, sector neutrality and turnover all make a
higher-scoring name worth less. That decision belongs to the strategy, which is
why the engine takes an Allocation rather than building one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Allocation:
    """A target book, and optionally the reasoning behind it.

    `weights` are fractions of gross notional, not dollars. A weight-based
    dollar-neutral book gives identical returns at any size, so the portfolio
    value enters only at reporting.

    `scores` are whatever the strategy computed on the way — carried so a
    report can show where construction overrode the signal, and ignored by
    everything else. Optional, because not every strategy has a meaningful
    intermediate.

    The invariants are checked here because they are what breaks silently: a
    book that has quietly stopped being neutral, or has levered itself, still
    produces a plausible equity curve.
    """

    weights: Mapping[str, float]
    scores: Mapping[str, float] = field(default_factory=dict)

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
) -> Allocation:
    """Long the top fraction, short the bottom fraction, equal-weighted.

    A helper for strategies, not something the engine applies. Only the
    ordering of `scores` is used, so a name scoring +61% and one scoring +14%
    are held identically — that is what equal-weighted means, and a strategy
    wanting conviction to matter should size differently.

    Ties break by ticker, so a rerun on the same data gives the same book
    rather than one that changes for no reason a reader can see.

    Each leg carries half the gross, so the result is neutral whether or not
    the legs hold the same number of names.
    """
    if not scores:
        return Allocation({})

    ranked = sorted(scores, key=lambda ticker: (-scores[ticker], ticker))

    n_long = max(1, int(len(ranked) * top_fraction))
    n_short = max(1, int(len(ranked) * bottom_fraction))
    if n_long + n_short > len(ranked):
        raise ValueError(
            f"{len(ranked)} names cannot fill a {top_fraction:.0%} long and "
            f"{bottom_fraction:.0%} short book without overlapping"
        )

    longs, shorts = ranked[:n_long], ranked[-n_short:]
    return Allocation(
        weights={t: 0.5 / n_long for t in longs} | {t: -0.5 / n_short for t in shorts},
        scores=dict(scores),
    )


def turnover(previous: Allocation | None, new: Allocation) -> float:
    """Gross notional traded, as a fraction of book size.

    Every name in the new book counts against a starting position of zero, so
    the first rebalance turns over 1.0 — you have to buy the book before you
    can hold it.
    """
    before = previous.weights if previous else {}
    return sum(
        abs(new.weights.get(t, 0.0) - before.get(t, 0.0)) for t in set(before) | set(new.weights)
    )


def linear_cost(previous: Allocation | None, new: Allocation, bps: float) -> float:
    """Turnover times a fixed rate, as a fraction of book size.

    No market impact and no size dependence, so this says nothing about
    capacity — see docs/ASSUMPTIONS.md.
    """
    return turnover(previous, new) * bps / 10_000
