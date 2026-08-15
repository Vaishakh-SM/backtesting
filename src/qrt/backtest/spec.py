"""What to run, and where to run it.

Two types, deliberately. A spec is everything that changes the answer. A job is
everything about dispatching it. Keeping them apart is what lets the same spec
run here or on a grid and produce the same result.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
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
    execution_lag_sessions: int = 1  # decide on close of t, hold from the next session

    # An assumption about the world rather than about the signal, so it stays
    # here. Sizing does not: a strategy decides what it holds.
    cost_bps: float = 10.0

    # Same spec, different code, different answer.
    code_version: str = ""

    def is_reproducible(self) -> bool:
        """A spec holding a live object cannot be rebuilt from itself."""
        return isinstance(self.strategy, StrategyRef)

    def content_id(self) -> str | None:
        """Hash of the canonical form, or None if not reproducible.

        Same content_id means same result, so it names the output directory and
        doubles as a cache key: a queue that delivers a job twice writes the
        same place rather than twice.

        None for a spec holding a live strategy object, because nothing can
        guarantee two machines would rebuild the same thing.
        """
        if not isinstance(self.strategy, StrategyRef):
            return None
        return hashlib.sha256(_canonical(self).encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        """The form that goes on the wire and into spec.json.

        Requires the strategy as a name and parameters. qrt.backtest.store
        converts a live object where it can.
        """
        if not isinstance(self.strategy, StrategyRef):
            raise ValueError(
                "this spec holds a live strategy object, which cannot be serialised. "
                "Use qrt.strategy.as_ref to name it first."
            )
        return {
            "strategy": {"name": self.strategy.name, "params": dict(self.strategy.params)},
            "universe": list(self.universe),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "as_of_knowledge": self.as_of_knowledge.isoformat(),
            "point_in_time": self.point_in_time,
            "rebalance_frequency": self.rebalance_frequency,
            "execution_lag_sessions": self.execution_lag_sessions,
            "cost_bps": self.cost_bps,
            "code_version": self.code_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> BacktestSpec:
        return cls(
            universe=tuple(raw["universe"]),
            start=datetime.fromisoformat(raw["start"]),
            end=datetime.fromisoformat(raw["end"]),
            strategy=StrategyRef(raw["strategy"]["name"], raw["strategy"]["params"]),
            as_of_knowledge=datetime.fromisoformat(raw["as_of_knowledge"]),
            point_in_time=raw["point_in_time"],
            rebalance_frequency=raw["rebalance_frequency"],
            execution_lag_sessions=raw["execution_lag_sessions"],
            cost_bps=raw["cost_bps"],
            code_version=raw.get("code_version", ""),
        )


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


def _canonical(spec: BacktestSpec) -> str:
    """Sorted keys and no whitespace, so the hash depends on the content rather
    than on how the dictionary happened to be built."""
    return json.dumps(spec.to_dict(), sort_keys=True, separators=(",", ":"))
