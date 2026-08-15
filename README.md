# backtester

Takes a cross-sectional long/short equity strategy from an idea to a backtest
and a report. Built so the next strategy is one method, not a change to the
engine.

## How to run

```bash
uv sync
source .venv/bin/activate          # or prefix each command below with `uv run`

backtester ingest                                 # fetch data; the only step needing network
backtester run configs/momentum.yaml              # -> out/<id>/
backtester report out/* --out out/report.html     # -> out/report.html
```

Thirty names over ten years: ~17s to ingest, ~4 MB, ~2s to backtest. Ingest
once; the backtest and report read what it landed and need no network.

## Shape

```
ingest  ──►  append-only store  ──►  backtest  ──►  report
(periodic)   (parquet, bitemporal)   (per spec)     (one html file)
```

| Package | Job |
|---|---|
| `backtester.data` | fetch, store, read back point-in-time |
| `backtester.strategy` | the extension point |
| `backtester.engine` | run a strategy over history as a unit of work |
| `backtester.report` | metrics and html |

Dependencies run one way, `report → engine → strategy → data`. A test asserts
it, because reversing it once caused a circular import every other test missed.

## Two ideas behind the design

**Ingestion is separate from backtesting.** A periodic job fetches and appends;
backtests read only what has landed, so they run offline and never depend on
vendor uptime.

**Every row carries two timestamps.** `event_ts` is what it is about,
`knowledge_ts` is when we learned it. Nothing is updated; a restatement
appends. A decision at time `t` sees `event_ts <= t` **and**
`knowledge_ts <= t`, so a later correction cannot leak backwards.

## Adding a strategy

One method. Given a moment, what should the book hold?

```python
class VolAdjustedMomentum(Strategy):
    lookback_sessions = 60            # history needed, in trading sessions

    def allocate(self, view: MarketView) -> Allocation:
        prices = view.read(PRICES)    # already bounded: no date filters, no future
        scores = ...                  # {ticker: score}
        return rank_weights(scores, top_fraction=0.2, bottom_fraction=0.2)
```

Sizing is yours. `rank_weights` does equal-weighted buckets; weight by
conviction, cap positions, or hold everything instead if you prefer. The engine
takes the `Allocation` and measures what it earned.

Complete and runnable: [`examples/custom_strategy.py`](examples/custom_strategy.py).

## Running one

**From a notebook.** Pass the object, no registration:

```python
result = run_backtest(
    BacktestSpec(
        universe=("AAPL", "MSFT", "NVDA"),
        start=at_close(2020, 1, 1),
        end=at_close(2024, 12, 31),
        strategy=VolAdjustedMomentum(60),
        as_of_knowledge=latest_knowledge_ts(ref),
    ),
    ref,
)
compute(result)["net_sharpe"]        # 0.27
```

**From the CLI.** Add a line to `STRATEGIES` in
`backtester/strategy/__init__.py` so a config can name it:

```yaml
# configs/vol_adjusted.yaml
strategy:
  name: vol_adjusted
  params: {lookback_sessions: 60, top_fraction: 0.2}
universe: us-liquid-30
start: 2020-01-01
end: 2024-12-31
rebalance_frequency: M          # M | W | D
execution_lag_sessions: 1       # decide on close of t, hold from t+1
cost_bps: 10.0
point_in_time: true
```

```bash
backtester run configs/vol_adjusted.yaml
# out/a7ca452c5dcaadf9  59 periods  final equity 1.39
```

The notebook path is for iterating; the CLI path is what a queue or a cron job
drives. A notebook-defined strategy still saves its result, but records that it
cannot be rebuilt, since nothing elsewhere can look the class up.

Results are written, not printed. `out/<id>/` holds `spec.json` and three
parquet files, named by a hash of the spec, so re-running overwrites and
different parameters land elsewhere.

## Many at once

`run_backtest` is pure and output is content-addressed, so workers need no
coordination.

```bash
python examples/parallel_sweep.py     # 6 backtests, ~5s
```

Two things in [`examples/parallel_sweep.py`](examples/parallel_sweep.py) that
are not guessable: use `spawn`, not the default `fork`, because polars keeps a
thread pool and forking deadlocks with no error at all. And resolve
`as_of_knowledge` once in the parent, or workers land on different cutoffs and
stop comparing like with like.

Same shape on a grid. A `BacktestSpec` is pure data, so it serialises to JSON
and travels in a queue message.

## The report

```bash
backtester report out/* --out out/report.html
```

One self-contained file, no external assets. Parameters and limitations up top,
a tab per run plus a comparison, a sortable and filterable table, then equity
and drawdown with a hover crosshair and clickable legend. Day, night or auto.

Past eight runs it says how many it omitted rather than truncating silently.

## Adding a metric

One function and one line. The renderer iterates `METRICS` and never names one.

```python
def worst_period(result: BacktestResult) -> float:
    return _number(result.returns["net_return"].min())

METRICS = (..., Metric(
    key="worst_period",
    label="Worst period",
    compute=worst_period,
    unit="percent",              # "percent" | "ratio"
    higher_is_better=True,       # None where neither direction is better
))
```

It gets a sortable column and its own tinting. Add its key to `headline` in
`report/html.py` to put it in the KPI tiles.

## Deployment

Two jobs, neither a service, with the store between them. That gap is why a
backtest runs offline and never depends on vendor uptime.

**Ingestion** touches the network and writes to the store. It produces no
artifact; the store *is* the output.

```bash
backtester ingest                                     # run it whenever you want data
```

Run it on demand. In production it would sit on a schedule, but nothing here
configures one, because a job that runs by hand runs under cron unchanged:

```cron
0 6 * * 1-5  docker run --rm -v /srv/data:/data backtester ingest --root /data/us-equities
```

**Backtests** read the store and write an artifact. They coordinate with
nothing, so run as many in parallel as you like.

Everything above runs from a checkout. The image is for running it somewhere
that is not your machine: a scheduler host, a grid worker, CI. Same commands,
no Python on the host.

```bash
docker build -t backtester .
docker run --rm -v "$PWD/data:/data" backtester ingest --root /data/us-equities
docker run --rm -v "$PWD/data:/data:ro" -v "$PWD/out:/out" backtester \
  run configs/momentum.yaml --root /data/us-equities --out /out
```

Object storage changes one thing:

```bash
backtester run configs/momentum.yaml --root s3://research/us-equities --region us-east-1
```

`docker compose up` runs that shape against MinIO with no AWS account.

Logs go to stderr, not files: cron mails them, Docker captures them, a
scheduler collects them. No secrets, since the data source is public.

## More

- [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) — every judgement call, including
  the ones that make these results optimistic
- [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md) — what was decided, and why
- [`examples/`](examples/) — runnable versions of everything above

```bash
make check      # lint, types, tests
```

221 tests, all offline. CI runs them on Python 3.11 to 3.13, then builds the
container and runs commands inside it, because building is not running.
