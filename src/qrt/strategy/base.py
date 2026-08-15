"""What a strategy is, and how one gets resolved by name."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from qrt.data.view import MarketView

ENTRY_POINT_GROUP = "qrt.strategies"


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
    def lookback(self) -> timedelta:
        """How far back generate_signal needs to see.

        The engine uses it as the lower bound of the query it runs for each
        rebalance, and to skip rebalances without enough history yet.
        """

    @abstractmethod
    def generate_signal(self, view: MarketView) -> Mapping[str, float]:
        """ticker -> score. Higher means more attractive to hold long."""


@dataclass(frozen=True)
class StrategyRef:
    """A registered strategy by name, resolvable on any worker that has the
    package installed."""

    name: str
    params: Mapping[str, Any] = field(default_factory=dict)


# Local runs take either. Remote runs need a StrategyRef, because a worker can
# only rebuild a strategy it can look up.
StrategySpec = Strategy | StrategyRef


def load_strategy(ref: StrategyRef) -> Strategy:
    """Resolve through entry points and construct with `params`.

    Called when a spec is built so a bad name or bad params fail immediately,
    and again in the worker that runs it.
    """
    raise NotImplementedError


def registered() -> Mapping[str, str]:
    """name -> import path, for `qrt strategies`."""
    raise NotImplementedError
