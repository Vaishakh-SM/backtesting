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

**A first observation is stamped at the time it was published, not the time we
happened to fetch it.** For daily exchange prices those are the same thing in
substance: the bar for a given session really was public at that session's
close, with no revision lag. Stamping it there models publication rather than
inventing it, and it is what lets a point-in-time backtest run over backfilled
history at all.

This assumption is specific to exchange prices. It would be false for anything
with a genuine reporting lag — earnings, restated fundamentals, index
membership — where the publication date is weeks after the period described,
and where a stamp taken from the event date would be a fabrication.

**A restatement is stamped at the time we learned it.** Yahoo restates prices
after a split, so a re-fetch returns different numbers for periods we already
hold. Those rows carry the ingestion time. Stamping them at their event
timestamp would assert that we knew split-adjusted 2020 prices in 2020, which
would let a backtest see the future through the knowledge axis rather than the
event axis — a subtler lookahead than the usual kind, and harder to notice.

**Ingestion therefore compares against the store before writing.** Rows
identical to what we already hold are not written. A re-run over unchanged data
appends nothing, so re-running is genuinely idempotent, and the log contains
exactly the first observations plus the real corrections.

**What this does not give us is Yahoo's own revision history.** We record when
*we* first saw a value and when we saw it change. If Yahoo silently corrected a
figure between our runs, we date that correction to our run rather than to
theirs. A vendor with a proper point-in-time feed would supply the real
publication timestamps; the schema is already shaped to take them.

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

**Re-running an ingestion for a period already covered writes nothing.** Rows
that match what the store already holds are dropped at write time, so a re-run
is idempotent rather than appending agreeing duplicates for reads to hide.
Verified against the live vendor: a second full run over ten years of thirty
tickers appends zero rows.

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

**A strategy's lookback is counted in trading sessions, not calendar days.**
Sixty sessions back from 28 June 2024 is 3 April, spanning 86 calendar days. A
window asked for as "sixty days" of calendar time would have contained about
forty-one sessions — two thirds of the intended history, with nothing looking
wrong in the output.

Strategies declare the count; the engine turns it into a window bound through
the trading calendar. Strategies never touch the calendar themselves, because
delivering data is the engine's job.

**Signals are computed on the close of date `t`; positions are held from `t+1`.**
The one-day execution lag is configurable but defaults to 1. Assuming execution
at the same close used to generate the signal is the single most common way a
backtest reports impossible performance.

**Dividend adjustment is available but optional, and the shipped strategy uses
it.** On an ex-date a price drops by roughly the dividend, so returns computed
on raw closes read every distribution as a loss.

Measured on this universe rather than assumed: dividend yields span 6.0% a year
(PFE at 6.0%, several names at zero), which is up to 1.58% of return over a
sixty-session window. That reshuffles eight of thirty ranks but did not change
which names fell in the top or bottom fifth on the date checked — return
dispersion over sixty sessions is an order of magnitude larger. So for a
cross-sectional rank it is a second-order effect.

It matters more for P&L, where a book long high yielders and short zero
yielders genuinely receives and pays that cash.

Left as a utility rather than applied automatically, because whether a signal
should see total return or price return is the strategy author's decision, not
the platform's.

A fuller system would trade at raw prices and book the dividend as cash. For a
weight-based dollar-neutral backtest with no financing the two are equivalent;
that equivalence breaks once borrow cost or margin is modelled, which is out of
scope below.

**Splits are not adjusted in our code.** Yahoo already back-adjusts its price
history for them, verified against AAPL's 2020 4-for-1. Split rows are still
stored, because they are what tells us a restatement happened, and because a
vendor supplying genuinely raw prices would need them.

**Adjustment is relative to the end of the window being read**, so price levels
are comparable only within one window. Returns are unaffected, and returns are
all a strategy should use them for.

**Positions are target weights as a fraction of gross notional**, dollar-neutral
(weights sum to zero) and unlevered (absolute weights sum to one).

**The backtest is scale-invariant and carries no capital figure.** With
weight-based positions and a turnover-proportional cost model, returns, Sharpe
and drawdown are identical regardless of portfolio size. Notional appears only as
a presentation parameter in the report.

**Rebalancing is monthly by default**, on the last trading day of the month —
the last day the exchange was actually open, not the 31st. Sessions come from a
maintained NYSE calendar rather than from the data, so a ticker with a gap
cannot quietly move a rebalance, and unscheduled closures such as the two days
Hurricane Sandy shut the exchange in 2012 are respected.

**Every session is treated as a full day ending at 16:00, including early
closes.** NYSE shuts at 13:00 on roughly four days a year. We ignore that:
ingestion stamps every bar at 16:00 and the calendar stamps every rebalance at
16:00, so the two always agree.

The simplification is deliberate, and stating it is the point — mixing the two
conventions would be worse than either. A rebalance stamped at a true 13:00
close would exclude that day's own bar from its own window, since the bar is
stamped 16:00. That is a silently short window roughly once a year, which is
exactly the kind of error a backtest absorbs without complaining.

It becomes wrong if intraday data is added, where an early close genuinely
truncates the session.

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
