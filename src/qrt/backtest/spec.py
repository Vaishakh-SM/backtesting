"""What to run, and where to run it.

Two types, deliberately. A spec is everything that changes the answer. A job is
everything about dispatching it. Keeping them apart is what lets the same spec
run here or on a grid and produce the same result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from qrt.data.dataset import DatasetRef
from qrt.strategy.base import StrategyRef, StrategySpec


@dataclass(frozen=True)
class BacktestSpec:
    """Everything that changes the answer. Pure data, hashable, serialisable.

    Holds no scheduling details, no connections, and no physical location —
    where the data happens to sit is deployment, not part of the result.
    """

    universe: tuple[str, ...]
    start: datetime
    end: datetime
    strategy: StrategySpec

    # Resolved when the spec is built, never in the worker, so a fan-out cannot
    # end up with a different cutoff on every machine.
    as_of_knowledge: datetime

    # True: each rebalance also caps knowledge at its own timestamp, so a
    # restatement cannot leak backwards into an earlier decision.
    # False: every read pins to as_of_knowledge, which is how you reproduce an
    # old run exactly, or measure how much restated data flatters the result.
    point_in_time: bool = True

    rebalance_frequency: str = "M"  # "M" | "W" | "D"
    execution_lag_days: int = 1  # decide on close of t, hold from t+1

    # Same spec, different code, different answer.
    code_version: str = ""

    # Portfolio construction and costs are not modelled yet. Their parameters
    # land here as plain fields when they are.

    def is_reproducible(self) -> bool:
        """A spec holding a live object cannot be rebuilt from itself."""
        return isinstance(self.strategy, StrategyRef)

    def content_id(self) -> str | None:
        """Hash of the canonical form, or None if not reproducible.

        Same content_id means same result, so it doubles as a cache key.
        """
        raise NotImplementedError


@dataclass(frozen=True)
class BacktestJob:
    """A unit of work. Scheduling details only."""

    spec: BacktestSpec
    ref: DatasetRef  # where this worker reads from
    output_uri: str
    run_id: str


@dataclass(frozen=True)
class BacktestResult:
    spec: BacktestSpec
    knowledge_ts: datetime  # what the run actually read
    reproducible: bool
    scores: Any  # per rebalance: ticker -> score
    positions: Any
    returns: Any
