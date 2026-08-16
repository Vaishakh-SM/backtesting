"""YAML config, validated on load.

A config that parses but is wrong should fail here, not eighty rebalances into
a run.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class UniverseConfig(BaseModel):
    name: str
    tickers: list[str] = Field(min_length=2)

    @field_validator("tickers")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate tickers")
        return v


class StrategyConfig(BaseModel):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class BacktestConfig(BaseModel):
    strategy: StrategyConfig
    universe: str
    start: date
    end: date
    rebalance_frequency: Literal["M", "W", "D"] = "M"
    execution_lag_sessions: int = Field(default=1, ge=0)
    point_in_time: bool = True
    cost_bps: float = Field(default=10.0, ge=0)

    @field_validator("end")
    @classmethod
    def _ordered(cls, v: date, info: Any) -> date:
        if (start := info.data.get("start")) and v <= start:
            raise ValueError("end must be after start")
        return v


def load_universe(path: Path) -> UniverseConfig:
    return UniverseConfig(**yaml.safe_load(path.read_text()))


def load_backtest(path: Path) -> list[BacktestConfig]:
    """The backtests a file describes. A list of them, or one on its own.

    Comparing parameter sets is the ordinary thing to do, so a file holds as
    many backtests as you like. Each is written out in full rather than derived
    from a base by some expansion rule, which keeps the file readable as exactly
    the set of runs it produces. Where that repeats too much, YAML's own anchors
    remove the repetition without this needing an opinion about it:

        - &base
          strategy: {name: trailing_return, params: {lookback_sessions: 20}}
          universe: us-liquid-30
          ...
        - <<: *base
          strategy: {name: trailing_return, params: {lookback_sessions: 60}}
    """
    raw = yaml.safe_load(path.read_text())
    entries = raw if isinstance(raw, list) else [raw]
    if not entries:
        raise ValueError(f"{path} describes no backtests")
    return [BacktestConfig(**entry) for entry in entries]
