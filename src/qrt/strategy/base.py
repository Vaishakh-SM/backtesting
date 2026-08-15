"""What a strategy is."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from qrt.backtest.portfolio import Allocation
from qrt.data.view import MarketView


class Strategy(ABC):
    """Given a moment in time, what should the book hold?

    Strategies hold no state. They do not see the stream of events, do not
    manage buffers, and never need resetting between runs. Getting data to them
    is the engine's job; deciding what to hold is theirs.

    That keeps them trivially testable: build a snapshot, call the function,
    check the book. No ordering to reproduce, no hidden state to explain a
    wrong answer.
    """

    @property
    @abstractmethod
    def lookback_sessions(self) -> int:
        """How many sessions of history `allocate` needs before the current one.

        Sessions, not calendar days. Sixty calendar days is about forty-one
        sessions, so a strategy asking in calendar time would quietly receive
        two thirds of the history it meant — and nothing would look wrong.

        The engine turns this into a window bound through the trading calendar,
        and skips rebalances without this much history behind them.

        A constant satisfies this: `lookback_sessions = 30` on the subclass is
        enough. A property is only needed when it varies per instance.
        """

    @abstractmethod
    def allocate(self, view: MarketView) -> Allocation:
        """The target book for this moment, as fractions of gross notional.

        Sizing lives here rather than in the engine because weight is not a
        function of score once anything real is involved — volatility, position
        caps, correlation between names, sector limits and turnover all make a
        higher-scoring name worth holding less of. `rank_weights` covers the
        simple case of equal-weighted buckets.
        """


@dataclass(frozen=True)
class StrategyRef:
    """A strategy named as a string, as a config file or a queue message
    carries it. qrt.strategy.load_strategy turns one into an object."""

    name: str
    params: Mapping[str, Any] = field(default_factory=dict)


# Code that already has the class passes the object. A config file or a queue
# message can only carry a name, so those use a StrategyRef.
StrategySpec = Strategy | StrategyRef
