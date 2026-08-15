"""Backtest results on disk.

Running a backtest and reporting on it are separate steps because they have
different costs and different lifetimes. A run walks sixty rebalances; a report
is a few aggregations over what it produced. Re-rendering should not re-run,
and a report over five parameter sets should not require holding five runs in
one process.

One directory per run, named by the spec's content id:

    out/<content_id>/
        spec.json          what was run
        returns.parquet    one row per holding period
        positions.parquet  one row per name held
        scores.parquet     one row per name ranked

Two runs of the same spec write the same directory, so a queue that delivers a
job twice does not produce two answers.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import polars as pl

from qrt.backtest.spec import BacktestResult, BacktestSpec
from qrt.strategy import as_ref
from qrt.strategy.base import Strategy, StrategyRef

SPEC_FILE = "spec.json"
FRAMES = ("returns", "positions", "scores")


def save_result(result: BacktestResult, root: Path) -> Path:
    """Write a result under `root`, returning the directory it landed in.

    A spec built from a live strategy object is named for it where the strategy
    is one we can look up. Where it is not — something defined in a notebook —
    the result is still written, and records that it cannot be rebuilt from its
    own description.
    """
    spec = _nameable(result.spec)
    named = isinstance(spec.strategy, StrategyRef)

    # Authoritative here rather than taking the engine's word for it: the
    # engine only knows the spec it was handed, while this can consult the
    # registry and name a live object. The question the file answers is "can
    # this be rebuilt from spec.json", which is decided at write time.
    content_id = spec.content_id() if named else None
    directory = root / (content_id or _fallback_name(result))
    directory.mkdir(parents=True, exist_ok=True)

    payload = (spec.to_dict() if named else _unnameable(spec)) | {
        "content_id": content_id,
        "reproducible": named,
        "knowledge_ts": result.knowledge_ts.isoformat(),
    }
    (directory / SPEC_FILE).write_text(json.dumps(payload, indent=2, sort_keys=True))

    for name in FRAMES:
        getattr(result, name).write_parquet(directory / f"{name}.parquet")

    return directory


def load_result(directory: Path) -> BacktestResult:
    """Read back what save_result wrote."""
    raw = json.loads((directory / SPEC_FILE).read_text())
    frames = {name: pl.read_parquet(directory / f"{name}.parquet") for name in FRAMES}

    return BacktestResult(
        spec=BacktestSpec.from_dict(raw),
        knowledge_ts=datetime.fromisoformat(raw["knowledge_ts"]),
        reproducible=raw["reproducible"],
        **frames,
    )


def load_results(directories: Sequence[Path]) -> list[BacktestResult]:
    """Read several runs, for a report that compares them."""
    return [load_result(d) for d in directories]


def _nameable(spec: BacktestSpec) -> BacktestSpec:
    """Swap a live strategy object for its registered name, if it has one."""
    if not isinstance(spec.strategy, Strategy):
        return spec

    ref = as_ref(spec.strategy)
    return spec if ref is None else replace(spec, strategy=ref)


def _unnameable(spec: BacktestSpec) -> dict[str, object]:
    """spec.json for a strategy the registry does not know — one written in a
    notebook, say.

    The numbers are still worth keeping, so this records everything that can be
    recorded and names the class for a human. The strategy name is prefixed so
    that trying to load it fails loudly rather than resolving to something
    else that happens to share a name.
    """
    placeholder = StrategyRef(
        f"unregistered:{type(spec.strategy).__name__}", _parameters(spec.strategy)
    )
    return dict(replace(spec, strategy=placeholder).to_dict())


def _parameters(strategy: object) -> dict[str, object]:
    return {k.lstrip("_"): v for k, v in vars(strategy).items()}


def _fallback_name(result: BacktestResult) -> str:
    """For a strategy with no registered name, so the run is still filed
    somewhere a person can find it."""
    return f"adhoc-{result.knowledge_ts.strftime('%Y%m%dT%H%M%S')}"
