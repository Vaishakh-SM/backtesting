# qrt

A small platform for taking a cross-sectional long/short equity strategy from
an idea to a backtest and a report.

Built so that adding the next strategy means writing one function, not
touching the engine.

## Quickstart

```bash
make install                  # uv sync
make ingest                   # fetch market data (the only step that needs network)
make backtest                 # run over what was ingested
```

The report lands in `out/`.

## How it fits together

```
ingest  ──►  append-only store  ──►  backtest  ──►  report
(periodic)   (parquet, bitemporal)   (per spec)     (one html file)
```

Four packages, depending one way only:

| Package | Job |
|---|---|
| `qrt.data` | fetching, storing, and reading back point-in-time |
| `qrt.strategy` | the extension point — where new signals go |
| `qrt.backtest` | walking a strategy over history as a unit of work |
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

## Adding a strategy

Subclass `Strategy`, declare how much history you need, return scores:

```python
class MyStrategy(Strategy):
    @property
    def lookback_sessions(self) -> int:
        return 30

    def generate_signal(self, view: MarketView) -> Mapping[str, float]:
        prices = dividend_adjusted(view.read(PRICES), view.read(ACTIONS))
        ...
        return {"AAPL": 0.4, "MSFT": -0.1}
```

Add one line to `STRATEGIES` in `qrt/strategy/__init__.py` and a config file or
a queue message can name it. Code that already has the class — a notebook, a
test — passes the object and skips that entirely.

The view is already bounded in time, so there is no way to write a lookahead
bug into a strategy. See `docs/adding-a-strategy.md`.

## Running it distributed

The dataset root is the only thing that changes:

```bash
qrt backtest configs/momentum.yaml --root s3://research/us-equities
```

`docker compose up` runs the whole thing against MinIO — one writer, several
readers — if you want to see that work without an AWS account.

## Reading further

- `docs/ASSUMPTIONS.md` — every judgement call, including the ones that make
  these results optimistic
- `docs/DESIGN_DECISIONS.md` — what was decided and why
- `docs/limitations.md` — what was deliberately left out

## Development

```bash
make check      # lint, types, tests
```

Tests run offline against committed fixtures.
