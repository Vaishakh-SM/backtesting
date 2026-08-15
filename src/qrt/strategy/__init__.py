"""The extension point.

A new strategy is a module in here plus one line in the mapping below.

The mapping exists for exactly one reason: a config file or a queue message
names a strategy as a string, and something has to turn `"trailing_return"`
into the class. Code that already has the class — a notebook, a test — passes
the object and never touches this.

It is read-only. Nothing registers itself at import time, so what is available
is whatever this file says, and reading the file tells you the whole answer.
"""

from types import MappingProxyType
from typing import Any

from qrt.strategy.base import Strategy, StrategyRef, StrategySpec
from qrt.strategy.portfolio import Allocation, linear_cost, rank_weights, turnover
from qrt.strategy.trailing_return import TrailingReturn

STRATEGIES: MappingProxyType[str, type[Strategy]] = MappingProxyType(
    {
        "trailing_return": TrailingReturn,
    }
)


def available() -> list[str]:
    return sorted(STRATEGIES)


def load_strategy(ref: StrategyRef) -> Strategy:
    """Build a strategy from a name and parameters.

    Called when a spec is built, so a bad name or bad parameters fail there
    rather than eighty rebalances into a run, and again on whichever node ends
    up executing it.
    """
    strategy = STRATEGIES.get(ref.name)
    if strategy is None:
        raise ValueError(f"unknown strategy {ref.name!r}; available: {', '.join(available())}")

    try:
        return strategy(**ref.params)
    except TypeError as exc:
        raise ValueError(f"bad parameters for {ref.name!r}: {exc}") from exc


def as_ref(strategy: Strategy) -> StrategyRef | None:
    """The name this strategy is known by, or None if it is not in the mapping.

    None means a spec holding it cannot be rebuilt elsewhere, so a result from
    it is not reproducible from its own description.
    """
    for name, cls in STRATEGIES.items():
        if type(strategy) is cls:
            return StrategyRef(name, _parameters(strategy))
    return None


def _parameters(strategy: Strategy) -> dict[str, Any]:
    """Constructor arguments, read back off the instance.

    Relies on a strategy storing what it was given. Documented in
    docs/adding-a-strategy.md rather than enforced, because the alternative is
    making every strategy a dataclass and that is a heavier constraint than
    this is worth.
    """
    return {k.lstrip("_"): v for k, v in vars(strategy).items()}


__all__ = [
    "STRATEGIES",
    "Allocation",
    "Strategy",
    "StrategyRef",
    "StrategySpec",
    "TrailingReturn",
    "as_ref",
    "available",
    "linear_cost",
    "load_strategy",
    "rank_weights",
    "turnover",
]
