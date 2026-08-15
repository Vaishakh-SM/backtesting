"""Run a parameter sweep across processes, then report on all of it.

    python examples/parallel_sweep.py

Six backtests in about five seconds. Needs data: `backtester ingest` first.

Two things here are not guessable:

  spawn, not fork. Polars keeps a thread pool, and forking a process that has
  already used it deadlocks. The sweep hangs with no error and no output.

  as_of_knowledge is resolved once, in the parent. If each worker resolved
  "latest" itself they could land on different cutoffs, and the sweep would
  stop comparing like with like.
"""

from __future__ import annotations

import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backtester.config import load_universe
from backtester.conventions import CLOSE_HOUR, TZ
from backtester.data.dataset import DatasetRef
from backtester.data.polars_reader import latest_knowledge_ts
from backtester.engine.runner import run_backtest
from backtester.engine.spec import BacktestSpec
from backtester.engine.store import save_result
from backtester.strategy import StrategyRef

ROOT = DatasetRef("./data/us-equities")
OUT = Path("out")


def at_close(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, CLOSE_HOUR, tzinfo=ZoneInfo(TZ))


def one(spec: BacktestSpec) -> str:
    """Run in a worker. Content-addressed output, so nothing coordinates."""
    return str(save_result(run_backtest(spec, ROOT), OUT))


def main() -> None:
    universe = tuple(load_universe(Path("configs/universe.yaml")).tickers)
    cutoff = latest_knowledge_ts(ROOT)

    specs = [
        BacktestSpec(
            universe=universe,
            start=at_close(2020, 1, 1),
            end=at_close(2024, 12, 31),
            # Named rather than a live object, so a worker can rebuild it.
            strategy=StrategyRef("trailing_return", {"lookback_sessions": n, "direction": d}),
            as_of_knowledge=cutoff,
        )
        for n in (20, 60, 120)
        for d in (1, -1)
    ]

    with ProcessPoolExecutor(max_workers=6, mp_context=mp.get_context("spawn")) as pool:
        directories = list(pool.map(one, specs))

    for directory in directories:
        print(directory)
    print(f"\n{len(directories)} runs. Report on all of them:")
    print(f"  backtester report {OUT}/* --out {OUT}/report.html")


if __name__ == "__main__":
    main()
