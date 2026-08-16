"""Turn a parameter sweep into queue messages, one per line.

    python examples/grid_submit.py > queue.jsonl

Prints what a submitter would publish. Pair it with grid_worker.py:

    python examples/grid_submit.py | while read -r m; do
        echo "$m" | STORE_ROOT=./data/us-equities OUT_ROOT=out python examples/grid_worker.py
    done

Needs data: `backtester ingest` first.

The submitter holds everything the workers must agree on. Two things in
particular:

  as_of_knowledge is resolved here, once. A worker resolving "latest" itself
  could land on a different cutoff, and the sweep would stop comparing like
  with like.

  The strategy is named, not an object. A message carries a name and its
  parameters; a worker rebuilds the strategy from the registry, so it can run a
  stock image with none of your code in it.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backtester.config import load_universe
from backtester.conventions import CLOSE_HOUR, TZ
from backtester.data.dataset import DatasetRef
from backtester.data.polars_reader import latest_knowledge_ts
from backtester.engine.spec import BacktestSpec
from backtester.strategy import StrategyRef

ROOT = DatasetRef("./data/us-equities")


def at_close(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, CLOSE_HOUR, tzinfo=ZoneInfo(TZ))


def main() -> None:
    universe = tuple(load_universe(Path("configs/universe.yaml")).tickers)
    cutoff = latest_knowledge_ts(ROOT)

    for lookback in (20, 60, 120):
        spec = BacktestSpec(
            universe=universe,
            start=at_close(2020, 1, 1),
            end=at_close(2024, 12, 31),
            strategy=StrategyRef("trailing_return", {"lookback_sessions": lookback}),
            as_of_knowledge=cutoff,
        )
        # content_id is where the result will land, so a submitter can record
        # what it asked for without waiting for anything to finish.
        print(json.dumps(spec.to_dict()))


if __name__ == "__main__":
    main()
