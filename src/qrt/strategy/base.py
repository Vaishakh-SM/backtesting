"""What a strategy is, and how one gets resolved by name."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from qrt.data.view import MarketView


class Strategy(ABC):
    """A pure function of a snapshot, plus a declaration of what it needs.

    Strategies hold no state. They do not see the stream of events, do not
    manage buffers, and never need resetting between runs. Getting data to
    them is the engine's job.

    That keeps them trivially testable: build a snapshot, call the function,
    check the scores. No ordering to reproduce, no hidden state to explain a
    wrong answer.
    """

    @property
    @abstractmethod
    def lookback_sessions(self) -> int:
        """How many sessions of history generate_signal needs before the
        current one.

        Sessions, not calendar days. Sixty calendar days is about forty-one
        sessions, so a strategy asking in calendar time would quietly receive
        two thirds of the history it meant — and nothing would look wrong.

        The engine turns this into a window bound through the trading calendar,
        and skips rebalances that do not have this much history behind them.
        """

    @abstractmethod
    def generate_signal(self, view: MarketView) -> Mapping[str, float]:
        """ticker -> score. Higher means more attractive to hold long."""


@dataclass(frozen=True)
class StrategyRef:
    """A strategy named as a string, as a config file or a queue message
    carries it. qrt.strategy.load_strategy turns one into an object."""

    name: str
    params: Mapping[str, Any] = field(default_factory=dict)


# Code that already has the class passes the object. A config file or a queue
# message can only carry a name, so those use a StrategyRef.
StrategySpec = Strategy | StrategyRef
