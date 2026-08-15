# Assumptions

Every judgement call made while building this, with the reasoning. Where an
assumption is known to be wrong-but-acceptable, that is stated rather than
glossed.

---

## Data source and ingestion

**Market data comes from Yahoo Finance via `yfinance`.** It is free, needs no
credentials, and covers the liquid US equities this exercise calls for. It is
not a production-grade source: no SLA, no support, and it has been known to
change its interface without notice. The design isolates it behind an ingestion
boundary so replacing it is a contained change.

**Ingestion is modelled as a periodic job.** The system assumes data arrives via
a scheduled process — a cron job, an Airflow DAG, whatever the deployment
provides — that queries the source and appends what it finds.

**No scheduler is actually configured here.** The ingestion job is invoked
manually via the CLI. This is deliberate: the scheduling mechanism is
environment-specific and not what this exercise is assessing, and a job that can
be run by hand is a job that can be run by cron. The design assumption that
matters is that ingestion is *decoupled from and asynchronous to* the backtest —
backtests never fetch.

**Consequently, backtests run offline.** They read only data that ingestion has
already landed. A backtest never depends on vendor uptime, rate limits, or
network access, which is what makes results reproducible and CI viable.

---

## Data model

**Data is modelled as an append-only bitemporal log.** Every row carries two
timestamps:

| Field | Meaning |
|---|---|
| `event_ts` | what the row is *about* — the bar's date, the ex-date of a dividend |
| `knowledge_ts` | when we *learned* it — stamped by the ingestion job |

**Nothing is ever updated or deleted.** When a vendor restates a value, the
ingestion job appends a new row with the same `event_ts` and a later
`knowledge_ts`. The old row remains.

**Reads resolve to the latest observation not after a knowledge cutoff** — filter
`knowledge_ts <= K`, then take the most recent row per `(ticker, event_ts)`.

Rationale: financial data is restated. Prices are retroactively adjusted for
splits and dividends, so "the price of AAPL on 2020-01-02" is not one fact but a
sequence of assertions about that day, each made at a different time. A store
that overwrites cannot reproduce a past result, and worse, cannot tell you that
the number changed.

**Both time axes are bounded when a strategy reads data.** A decision made on
date `t` sees `event_ts <= t` *and* `knowledge_ts <= t`. Bounding only the first
allows a subtler form of lookahead: using a restated price that did not exist at
the time of the decision.

**Backfilled history carries no real knowledge times, and this limits what the
knowledge axis can do for it.** `knowledge_ts` is stamped with when *we* learned
a row, which for a backfill is the moment the backfill ran. Yahoo does not
publish when it first asserted a value, so there is no way to recover the true
history of belief. That stamp is honest — we genuinely knew nothing in 2020 —
but it means per-rebalance knowledge filtering over backfilled data would
correctly return nothing at all.

So the knowledge axis protects runs going forward, where observations
accumulate over time and restatements are recorded as they arrive. For a
backtest over freshly backfilled history, the event axis does all the work and
the knowledge cutoff should be set at or after the backfill.

Rather than let that fail silently as empty windows, the engine compares the
earliest `knowledge_ts` in the store against the first rebalance and refuses the
run with an explanation. Fabricating plausible knowledge times instead was
considered and rejected: it would make the store assert things about the past
that we never actually believed, which defeats the point of recording belief.

**The ingestion job is the only writer.** Nothing else in the system writes to
the store — backtests and reports are strictly read-only. This is what makes the
append-only guarantee cheap to hold: there is no concurrent-write coordination,
no locking, and no reconciliation between writers.

Consequently the data layer does not expose a write interface. `DataSource`
answers *where a dataset lives*; ingestion resolves the layout through it and
writes a new partition per batch. Putting writes behind the same abstraction as
reads would mean owning schema validation, type coercion, and eventually
migrations — a persistence layer built to serve exactly one caller.

**The table schema is declared once as an Arrow schema per table**, referenced by
the writer and inherited by readers from the parquet footer. A malformed column
fails loudly on read rather than being silently coerced.

**Re-running an ingestion for a period already covered appends duplicate
observations rather than failing.** Under append-only semantics this is correct —
it is a new observation that happens to agree with the old one — and reads
deduplicate anyway. The cost is storage growth, accepted as negligible at this
scale.

**OHLCV and corporate actions are stored as separate tables, and dividend
adjustment is derived in code.** Storing a vendor's adjusted close directly
would mean the entire price history silently changes on every distribution. We
store Yahoo's unadjusted close and its dividends, and derive the adjustment,
which keeps that logic unit-testable and lets any knowledge cutoff be
reconstructed.

**Yahoo's "unadjusted" close is already split-adjusted.** This was verified
rather than assumed: AAPL's close for 2020-08-28 comes back as 124.81, not the
~499 that actually traded, with the 4-for-1 split flagged on the 2020-08-31
ex-date. Dividends are genuinely not folded in (124.81 against an adjusted
120.97), so only the dividend half of the adjustment is ours to do.

**Every ingestion re-fetches full history per ticker, not just the new tail.**
Because a split retroactively restates a ticker's whole series, an incremental
batch covering only recent bars would leave the store mixing pre-split and
post-split conventions, and a lookback window straddling that boundary would
compute a fictitious return. Re-fetching makes each batch internally
consistent, and the append-only log keeps the superseded version readable.

The cost is storage: a full refresh writes the whole history again rather than
a delta. At thirty names over ten years that is ~3.6 MB per run, which is not
worth optimising. It would be at a thousand names, where the fix is to write a
delta only when no action has occurred, and a full series when one has.

---

## Universe

**The universe is a static, hand-picked list of liquid US equities**, held fixed
across the whole backtest.

**This is survivorship-biased and the results are therefore optimistic.** The
names are chosen because they are liquid and well-known *today*, which is
information that did not exist at the start of the backtest window. Companies
that were liquid in 2015 and subsequently delisted or collapsed are absent
entirely.

This is a known, deliberate limitation. The schema carries a `universe` table
with `event_ts` and `knowledge_ts` so that point-in-time membership can be
introduced without redesign, but it is populated with a constant list here.

---

## Backtest conventions

**Signals are computed on the close of date `t`; positions are held from `t+1`.**
The one-day execution lag is configurable but defaults to 1. Assuming execution
at the same close used to generate the signal is the single most common way a
backtest reports impossible performance.

**Positions are target weights as a fraction of gross notional**, dollar-neutral
(weights sum to zero) and unlevered (absolute weights sum to one).

**The backtest is scale-invariant and carries no capital figure.** With
weight-based positions and a turnover-proportional cost model, returns, Sharpe
and drawdown are identical regardless of portfolio size. Notional appears only as
a presentation parameter in the report.

**Rebalancing is monthly by default**, on the last trading day of the month.

**No financing, borrow cost, or margin is modelled.** A real long/short book pays
to borrow the short leg and earns or pays on cash balances. Ignoring this
overstates net performance, most materially for hard-to-borrow names.

---

## Costs

**Transaction costs are modelled as a linear function of turnover**, in basis
points, applied at each rebalance.

**This ignores market impact and is therefore optimistic for large sizes.** A
linear cost model has no notion of capacity: it charges the same rate for $1m
and $1bn. Given the universe is large-cap and rebalancing is monthly, the error
is small at plausible research sizes, but the model should not be used to argue
capacity.

**No slippage, partial fills, or trading halts are modelled.** Every target
weight is assumed achievable at the reference price.

---

## Out of scope

Stated so their absence is not mistaken for oversight:

- Point-in-time universe membership (schema supports it; not populated)
- Borrow costs, financing, and margin
- Market impact and capacity analysis
- Intraday data, or any bar frequency other than daily
- Corporate actions beyond splits and cash dividends
- Multi-currency or non-US instruments
- Risk model, factor decomposition, or optimiser-based construction
