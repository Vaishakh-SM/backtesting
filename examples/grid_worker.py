"""Run one message from a queue. The other half of grid_submit.py.

    echo "$message" | STORE_ROOT=./data/us-equities OUT_ROOT=out \
        python examples/grid_worker.py

Reads one spec on stdin, runs it, writes the result, prints where it went.
A real deployment swaps stdin for a queue client and this file for the same
five lines; nothing else changes.

Where the data is and where results go are environment, not part of the
message. The same message therefore runs against a local directory here and
against s3:// on a grid, and produces the same answer, which is the point of
keeping physical location out of a spec.

Nothing coordinates between workers. The result directory is named by a hash
of the spec, so N workers write to N distinct places, and a message delivered
twice overwrites its own output rather than producing a second answer.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from backtester.data.dataset import DatasetRef
from backtester.engine.runner import run_backtest
from backtester.engine.spec import BacktestSpec
from backtester.engine.store import save_result


def main() -> None:
    spec = BacktestSpec.from_dict(json.loads(sys.stdin.read()))

    root = os.environ["STORE_ROOT"]
    region = {"region": os.environ.get("AWS_REGION", "us-east-1")} if "://" in root else {}
    ref = DatasetRef(root, region)

    directory = save_result(run_backtest(spec, ref), Path(os.environ["OUT_ROOT"]))
    print(f"{spec.content_id()}  ->  {directory}")


if __name__ == "__main__":
    main()
