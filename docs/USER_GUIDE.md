# User guide

How to do things. Why they are that way is in
[DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).

Every snippet here has been run.

---

## Where the data lives

One type, whether local or remote. The root says which.

```python
from backtester.data.dataset import DatasetRef

ref = DatasetRef("./data/us-equities")                              # local
ref = DatasetRef("s3://research/us-equities", {"region": "us-east-1"})
```

Credentials come from the environment, the same as any AWS tool — never from a
config file or a spec. In a notebook, set them before you build the reference:

```python
import os

os.environ["AWS_ACCESS_KEY_ID"] = "..."          # or already exported, or an instance role
os.environ["AWS_SECRET_ACCESS_KEY"] = "..."
os.environ["AWS_ENDPOINT_URL"] = "http://minio:9000"   # only for non-AWS S3

ref = DatasetRef("s3://research/us-equities", {"region": "us-east-1"})
latest_knowledge_ts(ref)          # works exactly as it does locally
```

Nothing else changes. The same reference goes to `ingest`, `run_backtest` and
everything else.

## Getting data in

```bash
backtester ingest                                    # local, ./data/us-equities
backtester ingest --root s3://research/us-equities   # object storage
```

Re-running appends only what changed, so it is safe to run on a schedule or by
hand. From Python:

```python
from backtester.data.ingest import ingest

ingest(ref, tickers=["AAPL", "MSFT"], start=..., end=..., ingested_at=datetime.now(NY))
```

## Running a backtest

**From a notebook** — pass the strategy object, no registration:

```python
from backtester.engine.runner import run_backtest
from backtester.engine.spec import BacktestSpec
from backtester.data.polars_reader import latest_knowledge_ts
from backtester.strategy import TrailingReturn

result = run_backtest(
    BacktestSpec(
        universe=("AAPL", "MSFT", "NVDA"),
        start=at_close(2020, 1, 1),           # the engine works in exchange closes
        end=at_close(2024, 12, 31),           # (a two-line helper; see the example)
        strategy=TrailingReturn(lookback_sessions=60),
        as_of_knowledge=latest_knowledge_ts(ref),   # pin the cutoff once
    ),
    ref,
)

result.returns        # one row per holding period: turnover, cost, net_return, equity
result.positions      # what was held, per rebalance
result.scores         # what the strategy thought, per rebalance
```

**From the CLI** — the strategy needs a name in `STRATEGIES`, and a config:

```bash
backtester run configs/momentum.yaml
# out/a7ca452c5dcaadf9  59 periods  final equity 1.3931
```

## Metrics from a result

```python
from backtester.report.metrics import compute

compute(result)["net_sharpe"]        # 0.75
compute(result)                      # every metric, keyed
```

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

To run it from a config, add a line:

```python
# backtester/strategy/__init__.py
STRATEGIES = MappingProxyType({
    "trailing_return": TrailingReturn,
    "vol_adjusted": VolAdjustedMomentum,
})
```

Runnable version: [`examples/custom_strategy.py`](../examples/custom_strategy.py).

## Running many at once

`run_backtest` is a pure function and results are content-addressed, so workers
need no coordination.

```python
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from backtester.engine.store import save_result

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

A spec is pure data, so it serialises and travels in a queue message.

```python
# submitter
message = json.dumps(spec.to_dict())         # 376 bytes
spec.content_id()                            # "3bb80c5b8061562a" — where the result lands
```

```python
# worker: same image, resolves the strategy by name
spec = BacktestSpec.from_dict(json.loads(message))
save_result(run_backtest(spec, DatasetRef(os.environ["STORE_ROOT"])), Path("/out"))
```

Nothing coordinates. The content hash decides the directory, so N workers write
to N distinct places and a redelivered message overwrites rather than
duplicating.

Use a `StrategyRef` rather than a live object: a worker can only rebuild a
strategy it can look up. A spec holding a live object reports
`is_reproducible() == False` and has no `content_id`.

## Reading results back

```python
from backtester.engine.store import load_result, load_results

result = load_result(Path("out/a7ca452c5dcaadf9"))
results = load_results(sorted(Path("out").iterdir()))    # for one report over many
```

## Reports

```bash
backtester report out/* --out out/report.html
```

```python
from backtester.report.html import render

render(results, Path("out/report.html"))
```

One self-contained file: a tab per run plus a comparison, a sortable and
filterable table, equity and drawdown with a hover crosshair.

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
