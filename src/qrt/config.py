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


def load_backtest(path: Path) -> BacktestConfig:
    return BacktestConfig(**yaml.safe_load(path.read_text()))
