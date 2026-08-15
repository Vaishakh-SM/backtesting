# qrt

A small platform for taking a cross-sectional long/short equity strategy from
an idea to a backtest and a report.

Built so that adding the next strategy means writing one method, not touching
the engine.

## Quickstart

```bash
make install                  # uv sync
make ingest                   # fetch market data — the only step that needs network
make backtest                 # run over what was ingested
qrt report out/* --out out/report.html
```

Ingesting thirty names over ten years takes about 17 seconds and lands ~4 MB.
A backtest over that data takes about 2 seconds.

## How it fits together

```
ingest  ──►  append-only store  ──►  backtest  ──►  report
(periodic)   (parquet, bitemporal)   (per spec)     (one html file)
```

Four packages, depending one way only — `report → backtest → strategy → data`.
A test asserts that direction, because reversing it caused a circular import
every other test missed.

| Package | Job |
|---|---|
| `qrt.data` | fetching, storing, and reading back point-in-time |
| `qrt.strategy` | the extension point — where new signals go |
| `qrt.backtest` | running a strategy over history as a unit of work |
| `qrt.report` | metrics and the html output |

## Two ideas worth knowing before reading the code

**Ingestion and backtesting are separate.** Ingestion is a periodic job that
fetches from a vendor and appends. Backtests read only what has already landed,
so they run offline and never depend on vendor uptime.

**Every row carries two timestamps.** `event_ts` is what the row is about,
`knowledge_ts` is when we learned it. Nothing is ever updated — a restatement
appends a new row. A strategy deciding at time `t` sees only `event_ts <= t`
*and* `knowledge_ts <= t`, so a correction made later cannot leak backwards
into an earlier decision.

---

## Adding a strategy

A strategy answers one question: **given this moment, what should the book
hold?** It never fetches data, never writes a date filter, and never sees the
future — the window it is handed is already bounded.

Write one file:

```python
# src/qrt/strategy/vol_adjusted.py
import polars as pl

from qrt.data.schema import PRICES
from qrt.data.view import MarketView
from qrt.strategy import Allocation, Strategy, rank_weights


class VolAdjustedMomentum(Strategy):
    """Trailing return per unit of realised volatility."""

    def __init__(self, lookback_sessions: int = 60, top_fraction: float = 0.2):
        self._lookback_sessions = lookback_sessions
        self.top_fraction = top_fraction

    @property
    def lookback_sessions(self) -> int:
        return self._lookback_sessions          # how much history you need

    def allocate(self, view: MarketView) -> Allocation:
        prices = view.read(PRICES).sort("event_ts")

        stats = (
            prices.with_columns(pl.col("close").pct_change().over("ticker").alias("ret"))
            .group_by("ticker")
            .agg(
                (pl.col("close").last() / pl.col("close").first() - 1).alias("total"),
                pl.col("ret").std().alias("vol"),
            )
            .filter(pl.col("vol") > 0)
        )

        scores = {r["ticker"]: r["total"] / r["vol"] for r in stats.iter_rows(named=True)}
        return rank_weights(scores, self.top_fraction, self.top_fraction)
```

Then add one line so a config file or a queue message can name it:

```python
# src/qrt/strategy/__init__.py
STRATEGIES = MappingProxyType({
    "trailing_return": TrailingReturn,
    "vol_adjusted": VolAdjustedMomentum,      # <-- added
})
```

That is the whole contract. Sizing is yours — `rank_weights` covers
equal-weighted buckets, but nothing stops you weighting by conviction, capping
positions, or holding every name. The engine takes whatever `Allocation` you
return and measures what it earned.

**Two things worth knowing:**

- `lookback_sessions` counts **trading sessions**, not calendar days. Sixty
  calendar days is about forty-one sessions.
- Prices are raw. `qrt.data.dividends.dividend_adjusted` is there if you want
  total-return prices; using it is your decision, not the platform's.

Working from a notebook? You need none of the registration — pass the object
directly:

```python
result = run_backtest(replace(spec, strategy=VolAdjustedMomentum(30)), ref)
```

The result still gets saved. It simply records that it cannot be rebuilt from
its own description, because a worker elsewhere has no way to look it up.

---

## Backtesting it

Point a config at the strategy by name:

```yaml
# configs/vol_adjusted.yaml
strategy:
  name: vol_adjusted
  params:
    lookback_sessions: 60
    top_fraction: 0.2

universe: us-liquid-30
start: 2020-01-01
end: 2024-12-31
rebalance_frequency: M          # M | W | D
execution_lag_sessions: 1       # decide on close of t, hold from t+1
cost_bps: 10.0
point_in_time: true
```

```bash
qrt backtest configs/vol_adjusted.yaml
# out/e671fcfc7cfdc059  59 periods  final equity 1.3968
```

The result is written, not printed. `out/<id>/` holds `spec.json`,
`returns.parquet`, `positions.parquet` and `scores.parquet`. The directory name
is a hash of the spec, so **re-running the same backtest overwrites rather than
duplicating**, and different parameters land in different directories.

---

## Running many backtests in parallel

`run_backtest` is a pure function and results are content-addressed, so workers
need no coordination — they write to distinct directories by construction.

```python
# sweep.py
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from qrt.backtest.engine import run_backtest
from qrt.backtest.spec import BacktestSpec
from qrt.backtest.store import save_result
from qrt.config import load_universe
from qrt.conventions import TZ
from qrt.data.dataset import DatasetRef
from qrt.data.polars_reader import latest_knowledge_ts
from qrt.strategy import StrategyRef

NY = ZoneInfo(TZ)
ROOT, OUT = DatasetRef("./data/us-equities"), Path("out")


def one(spec: BacktestSpec) -> str:
    return str(save_result(run_backtest(spec, ROOT), OUT))


if __name__ == "__main__":
    universe = tuple(load_universe(Path("configs/universe.yaml")).tickers)
    cutoff = latest_knowledge_ts(ROOT)     # resolved ONCE, shared by every worker

    specs = [
        BacktestSpec(
            universe=universe,
            start=datetime(2020, 1, 1, 16, tzinfo=NY),
            end=datetime(2024, 12, 31, 16, tzinfo=NY),
            strategy=StrategyRef("trailing_return",
                                 {"lookback_sessions": n, "direction": d}),
            as_of_knowledge=cutoff,
        )
        for n in (20, 60, 120)
        for d in (1, -1)
    ]

    # spawn, NOT the default fork — see below.
    with ProcessPoolExecutor(max_workers=6, mp_context=mp.get_context("spawn")) as pool:
        for directory in pool.map(one, specs):
            print(directory)
```

```bash
python sweep.py            # 6 backtests in ~5s
```

**Use `spawn`, not the default `fork`.** Polars keeps a thread pool, and
forking a process that has already used it deadlocks — the sweep hangs with no
error at all. This bit us; it is not theoretical.

**Resolve `as_of_knowledge` once, in the parent.** If each worker called
`latest_knowledge_ts` itself they could land on different cutoffs, and the
sweep would stop comparing like with like.

The same shape works on a real grid. A `BacktestSpec` is pure data — no
connections, no live objects — so it serialises to JSON and travels in a queue
message. Each node runs the same image, resolves the strategy by name, and
writes its result. Nothing coordinates, because the content hash decides where
each result lands.

---

## One report over many runs

```bash
qrt report out/* --out out/report.html
# out/report.html  6 run(s)
```

One self-contained HTML file covering every run: headline metrics per run, all
equity curves on one axis, drawdowns, a full metric table, what was run, and
what the numbers exclude. No external assets — it opens from an email
attachment or from object storage.

Runs are labelled by whatever distinguishes them, so a sweep over two
parameters reads `direction 1 lookback 60` rather than a dump of every setting
they share. Columns are sorted, so the document is the same however the shell
expanded the glob.

Past eight runs the report says how many it omitted rather than truncating
silently — beyond that the colours stop being tellable apart.

Reporting reads files and re-runs nothing, so last month's results can be
re-rendered with new charts.

---

## Deployment

This is a **batch job, not a service.** No API, no uptime SLA: build an image,
run it, collect an artifact.

```bash
docker build -t qrt .

# Ingest — the only step that touches the network. Run this on a schedule.
docker run --rm -v "$PWD/data:/data" qrt \
  ingest --root /data/us-equities

# Backtest — offline, reads what ingestion landed.
docker run --rm -v "$PWD/data:/data:ro" -v "$PWD/out:/out" qrt \
  backtest configs/momentum.yaml --root /data/us-equities --out /out

docker run --rm -v "$PWD/out:/out" qrt report /out/<id> --out /out/report.html
```

**Scheduling.** Ingestion is a periodic job; nothing here configures a
scheduler, because that is environment-specific and a job that runs by hand
runs under cron. What matters to the design is that ingestion is decoupled from
and asynchronous to the backtest.

```cron
0 6 * * 1-5  docker run --rm -v /srv/qrt/data:/data qrt ingest --root /data/us-equities
```

**Object storage.** The only thing that changes is the dataset root:

```bash
qrt backtest configs/momentum.yaml --root s3://research/us-equities --region us-east-1
```

`docker compose up` runs the whole shape against MinIO — one writer, several
readers — with no AWS account. Workers only read, so they need no coordination
between them; that is what append-only buys.

**Logs** go to stderr and are not written to files. Cron mails them, Docker
captures them, a scheduler collects them — writing our own would duplicate that
and add rotation and cleanup problems the platform already solves.

**No secrets** are needed: the data source is public. A paid vendor changes
that.

---

## Reading further

- `docs/ASSUMPTIONS.md` — every judgement call, including the ones that make
  these results optimistic
- `docs/DESIGN_DECISIONS.md` — what was decided and why
- `docs/limitations.md` — what was deliberately left out

## Development

```bash
make check      # lint, types, tests
```

208 tests, all offline — the vendor call is substituted and everything
downstream runs for real. CI runs the same checks on Python 3.11 to 3.13, then
builds the container and runs commands inside it, because building is not
running.
