"""The extension point. A new strategy is a new module in here, or in someone
else's package that declares the `qrt.strategies` entry point group."""

from qrt.strategy.base import Strategy, StrategyRef, StrategySpec, load_strategy

__all__ = ["Strategy", "StrategyRef", "StrategySpec", "load_strategy"]
