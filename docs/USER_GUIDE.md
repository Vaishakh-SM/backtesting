# User guide

How to do things. Why they are that way is in
[DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).

Every snippet here has been run.

## Two ways to drive it

Every task below is shown both ways, because they are for different situations.

| | **CLI** | **Python** |
|---|---|---|
| For | cron, a queue, a grid, CI | a notebook, iterating on an idea |
| Strategy | must be named in `STRATEGIES` | any object, including one defined in the cell |
| Parameters | a YAML config | arguments |
| Output | always written to `out/<id>/` | in memory; write it if you want it |

They are the same code. The CLI parses arguments and calls the same functions
Python does, so nothing is available from one and not the other.

---

## Pointing at the data

Everything that touches the store takes a *root*, and the root is the only
thing that differs between a local directory and object storage.

**CLI** — `--root` on every command that reads or writes:

```bash
backtester ingest --root ./data/us-equities                    # local (the default)
backtester ingest --root s3://research/us-equities             # object storage
backtester ingest --root s3://research/us-equities --region eu-west-1
```

**Python** — a `DatasetRef`, built once and passed around:

```python
from backtester.data.dataset import DatasetRef

ref = DatasetRef("./data/us-equities")                              # local
ref = DatasetRef("s3://research/us-equities", {"region": "us-east-1"})
```

There is one type for both. `DatasetRef` reads the `://` in the root and works
out the rest, so no code below ever asks which kind it has.

### Credentials

They come from the environment, the same as any AWS tool, and never from a
config file or a spec — those get committed, and a spec travels through a
queue. Only the region and an optional endpoint are configuration.

**CLI** — export them, as normal:

```bash
export AWS_ACCESS_KEY_ID=...  AWS_SECRET_ACCESS_KEY=...   # or an instance role
export AWS_ENDPOINT_URL=http://minio:9000                 # only for non-AWS S3
```

**Python** — a notebook usually has no exported environment, so set it in the
first cell, before building the reference:

```python
import os

os.environ["AWS_ACCESS_KEY_ID"] = "..."
os.environ["AWS_SECRET_ACCESS_KEY"] = "..."
os.environ["AWS_ENDPOINT_URL"] = "http://minio:9000"      # only for non-AWS S3

ref = DatasetRef("s3://research/us-equities", {"region": "us-east-1"})
latest_knowledge_ts(ref)          # from here on, identical to local
```

Nothing else changes. The same `ref` goes to `ingest`, `run_backtest` and
everything else, whichever kind it is.

### Trying it without an AWS account

`docker compose up` starts MinIO, which speaks the S3 API, then ingests and
runs against it. That is how the S3 path here was tested end to end, including
a check that the polars and duckdb readers return identical data.

```bash
docker compose up
```

---

## Getting data in

The only step that touches the network, and the only writer. Re-running appends
only what changed, so it is safe to run on a schedule or by hand.

**CLI**:

```bash
backtester ingest                                       # local, ./data/us-equities
backtester ingest --root s3://research/us-equities      # same job, object storage
```

**Python** — the root is in the `ref`, so local versus S3 is that one line:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from backtester.conventions import TZ
from backtester.data.ingest import ingest

ref = DatasetRef("./data/us-equities")                              # or:
ref = DatasetRef("s3://research/us-equities", {"region": "us-east-1"})

now = datetime.now(ZoneInfo(TZ))
summary = ingest(
    ref,
    tickers=["AAPL", "MSFT", "NVDA"],
    start=datetime(2015, 1, 1, tzinfo=ZoneInfo(TZ)),
    end=now,
    ingested_at=now,        # stamps restatements; passed in, not read from the clock
)
print(summary)   # ingested_at=...  actions=199, prices=15030, universe=30
```

A second run of the same thing prints `actions=0, prices=0, universe=0`: rows
identical to ones already held are not written, so re-running costs a fetch and
nothing else.

---

## Running a backtest

**CLI** — the strategy must be named in `STRATEGIES`, and the parameters live
in a config:

```bash
backtester run configs/momentum.yaml
# out/33a52d230ed265ec  59 periods  final equity 1.0694
# out/34da444833259034  59 periods  final equity 1.0090
# out/a7ca452c5dcaadf9  59 periods  final equity 1.3931

backtester run configs/momentum.yaml --root s3://research/us-equities --out /out
```

Three lines because a config file is a list of backtests. Each entry is written
out in full, so the file reads as exactly the runs it produces; YAML's own
anchors keep the shared settings in one place.

```yaml
- &base
  strategy:
    name: trailing_return
    params: {lookback_sessions: 20, direction: 1, top_fraction: 0.2}
  universe: us-liquid-30
  start: 2020-01-01
  end: 2025-01-01
  cost_bps: 10.0

- <<: *base                       # everything above, with these changes
  strategy:
    name: trailing_return
    params: {lookback_sessions: 60, direction: 1, top_fraction: 0.2}

- <<: *base                       # entries can differ in anything, not just params
  cost_bps: 25.0
```

A single backtest is written plainly, with no list. Because entries are whole
configs, one file can compare different strategies, cost assumptions or date
ranges, not only different parameters.

The result is written, never printed: `out/<id>/` holds `spec.json` and three
parquet files, named by a hash of the spec.

Progress goes to stderr and result lines to stdout, so
`backtester run ... > runs.txt` collects only the directories. `--quiet` for
errors only, `--debug` for every rebalance and every skipped window.

**Python** — pass the strategy object; nothing needs registering, so a class
defined in the cell above works:

```python
from backtester.data.polars_reader import latest_knowledge_ts
from backtester.engine.runner import run_backtest
from backtester.engine.spec import BacktestSpec
from backtester.strategy import TrailingReturn

result = run_backtest(
    BacktestSpec(
        universe=("AAPL", "MSFT", "NVDA"),
        start=at_close(2020, 1, 1),         # the engine works in exchange closes;
        end=at_close(2024, 12, 31),         # `at_close` is a two-line helper, see below
        strategy=TrailingReturn(lookback_sessions=60),
        as_of_knowledge=latest_knowledge_ts(ref),   # pin the cutoff once
    ),
    ref,
)

result.returns      # one row per holding period: turnover, cost, net_return, equity
result.positions    # what was held, per rebalance
result.scores       # what the strategy thought, per rebalance
```

```python
def at_close(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, CLOSE_HOUR, tzinfo=ZoneInfo(TZ))
```

Keeping the result rather than just looking at it:

```python
from backtester.engine.store import save_result
save_result(result, Path("out"))        # -> out/<id>/, same layout the CLI writes
```

## Metrics from a result

Python only; the CLI puts them in the report.

```python
from backtester.report.metrics import compute

compute(result)["net_sharpe"]        # 0.75
compute(result)                      # every metric, keyed
```

## Reports

**CLI**:

```bash
backtester report out/* --out out/report.html
```

**Python**:

```python
from backtester.engine.store import load_result, load_results
from backtester.report.html import render

results = load_results(sorted(Path("out").iterdir()))   # or a list you have in hand
render(results, Path("out/report.html"))
```

One self-contained file: a tab per run plus a comparison, a sortable and
filterable table, equity and drawdown with a hover crosshair.

---

## Choosing your dataframe

Inside a strategy, ask for the shape you want. Arrow is the common currency, so
all three are one call away whichever engine fetched the window.

```python
def allocate(self, view: MarketView) -> Allocation:
    prices = view.read(PRICES)                    # polars, the default
    prices = view.read(PRICES, fmt="pandas")      # pandas DataFrame
    prices = view.read(PRICES, fmt="arrow")       # pyarrow Table
```

## Writing a strategy

One method. The window is already bounded, so there are no date filters to
write and no way to see the future.

```python
from backtester.strategy import Allocation, Strategy, rank_weights

class VolAdjustedMomentum(Strategy):
    lookback_sessions = 60                        # trading sessions, not calendar days

    def allocate(self, view: MarketView) -> Allocation:
        prices = view.read(PRICES)
        scores = ...                              # {ticker: score}
        return rank_weights(scores, top_fraction=0.2, bottom_fraction=0.2)
```

Sizing is yours. `rank_weights` gives equal-weighted buckets; anything else is
just building the `Allocation` directly:

```python
        # conviction-weighted instead of equal-weighted
        longs = {t: s for t, s in scores.items() if s > 0}
        weights = {t: 0.5 * s / sum(longs.values()) for t, s in longs.items()}
        return Allocation(weights | shorts, scores)
```

The invariants are checked on construction: weights must net to zero and gross
to one.

**In Python that is all**, and the class is usable immediately. **To reach it
from the CLI** it needs a name, because a config can only refer to one:

```python
# backtester/strategy/__init__.py
STRATEGIES = MappingProxyType({
    "trailing_return": TrailingReturn,
    "vol_adjusted": VolAdjustedMomentum,
})
```

```yaml
# configs/vol_adjusted.yaml
strategy:
  name: vol_adjusted
  params: {lookback_sessions: 60, top_fraction: 0.2}
```

Runnable version: [`examples/custom_strategy.py`](../examples/custom_strategy.py).

---

## Running many at once

`run_backtest` is a pure function and results are content-addressed, so workers
need no coordination.

```python
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor

def one(spec):
    return str(save_result(run_backtest(spec, ROOT), Path("out")))

cutoff = latest_knowledge_ts(ROOT)                # resolved ONCE, in the parent
specs = [BacktestSpec(..., strategy=StrategyRef("trailing_return", {"lookback_sessions": n}),
                      as_of_knowledge=cutoff)
         for n in (20, 60, 120)]

with ProcessPoolExecutor(mp_context=mp.get_context("spawn")) as pool:
    directories = list(pool.map(one, specs))
```

Two things that are not guessable:

- **`spawn`, not the default `fork`.** Polars keeps a thread pool, and forking
  after it has been used deadlocks with no error and no output.
- **Resolve `as_of_knowledge` in the parent.** Each worker calling
  `latest_knowledge_ts` could land on a different cutoff, and the sweep would
  stop comparing like with like.

Runnable version: [`examples/parallel_sweep.py`](../examples/parallel_sweep.py).

## Running on a grid

A spec is pure data, so it serialises and travels in a queue message. Two
processes instead of one: a submitter that publishes, and workers that consume.

```python
# submitter: everything the workers must agree on is decided once, here
cutoff = latest_knowledge_ts(ref)
for lookback in (20, 60, 120):
    spec = BacktestSpec(
        ...,
        strategy=StrategyRef("trailing_return", {"lookback_sessions": lookback}),
        as_of_knowledge=cutoff,
    )
    print(json.dumps(spec.to_dict()))        # ~380 bytes; publish it
```

```python
# worker: rebuilds the strategy by name, so it runs a stock image with none of
# your code in it. Where the data is comes from the environment, not the message.
spec = BacktestSpec.from_dict(json.loads(sys.stdin.read()))
ref = DatasetRef(os.environ["STORE_ROOT"])
save_result(run_backtest(spec, ref), Path(os.environ["OUT_ROOT"]))
```

Runnable, and this is the whole deployment shape with a queue in place of the
loop: [`examples/grid_submit.py`](../examples/grid_submit.py) and
[`examples/grid_worker.py`](../examples/grid_worker.py).

```bash
python examples/grid_submit.py | while read -r message; do
    echo "$message" | STORE_ROOT=./data/us-equities OUT_ROOT=out python examples/grid_worker.py
done
```

```
7d86e6742c78f137  ->  out/7d86e6742c78f137
85ec88486a52e855  ->  out/85ec88486a52e855
3c070a38bc2f0db1  ->  out/3c070a38bc2f0db1
```

Nothing coordinates. The content hash decides the directory, so N workers write
to N distinct places, and feeding the same message in twice prints the same
directory rather than producing a second answer.

Two things the message must get right:

- **Name the strategy, do not pass an object.** A worker can only rebuild one it
  can look up. A spec holding a live object reports `is_reproducible() == False`
  and has no `content_id`, so there is nowhere for the result to go.
- **Resolve `as_of_knowledge` in the submitter.** Workers that each ask for
  "latest" can land on different cutoffs, and the sweep stops comparing like
  with like.

Keeping the store location out of the message is what lets the same message run
against a local directory here and `s3://` on a grid.

## Adding a metric

One function and one line. The renderer iterates `METRICS` and never names a
metric, so a new one gets a sortable column and its own tinting for free.

```python
# backtester/report/metrics.py
def worst_period(result: BacktestResult) -> float:
    return _number(result.returns["net_return"].min())

METRICS = (..., Metric(
    key="worst_period",
    label="Worst period",
    compute=worst_period,
    unit="percent",                # "percent" | "ratio"
    higher_is_better=True,         # None where neither direction is better
))
```

Add its key to `headline` in `report/html.py` to put it in the KPI tiles too.

---

## All of it, in one script

Data already in the store, through to a report over three parameter sets.
Change the first line and this runs against S3 instead.

```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backtester.conventions import CLOSE_HOUR, TZ
from backtester.data.dataset import DatasetRef
from backtester.data.polars_reader import latest_knowledge_ts
from backtester.engine.runner import run_backtest
from backtester.engine.spec import BacktestSpec
from backtester.engine.store import save_result
from backtester.report.html import render
from backtester.report.metrics import compute
from backtester.strategy import TrailingReturn


def at_close(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, CLOSE_HOUR, tzinfo=ZoneInfo(TZ))


ref = DatasetRef("./data/us-equities")      # or DatasetRef("s3://research/us-equities",
cutoff = latest_knowledge_ts(ref)           #                {"region": "us-east-1"})

results = []
for lookback in (20, 60, 120):
    spec = BacktestSpec(
        universe=("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL"),
        start=at_close(2020, 1, 1),
        end=at_close(2024, 12, 31),
        strategy=TrailingReturn(lookback_sessions=lookback),
        as_of_knowledge=cutoff,             # the same cutoff for all three, so they compare
    )
    result = run_backtest(spec, ref)
    save_result(result, Path("out"))
    results.append(result)
    print(f"lookback {lookback:>3}  sharpe {compute(result)['net_sharpe']:>6.2f}")

render(results, Path("out/report.html"))
```

```
lookback  20  sharpe   0.36
lookback  60  sharpe  -0.06
lookback 120  sharpe   0.68
```

The same three runs from the CLI, given a config per lookback:

```bash
backtester run configs/momentum_20.yaml
backtester run configs/momentum_60.yaml
backtester run configs/momentum_120.yaml
backtester report out/* --out out/report.html
```
