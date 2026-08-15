# Design decisions

What was decided and why, grouped by the part of the system it concerns. How to
*use* any of it is in [USER_GUIDE.md](USER_GUIDE.md).

Assumptions about the *market* — survivorship bias, costs, execution — are in
[ASSUMPTIONS.md](ASSUMPTIONS.md). This file is about the *software*.

---

## Storage

**Parquet, fixed.** Not configurable. Nothing here needs a second format, and
supporting one costs more than it returns.

**Local disk and object storage, and nothing else.** It is the only storage
difference that matters, because it is what lets workers on a grid read the
same data.

**One type carries the difference.** A dataset reference holds the path prefix
and the setup a reader needs. Everything else works without knowing which it is
talking to, and the layout convention lives in one function.

```python
@dataclass(frozen=True)
class DatasetRef:
    root: str                                   # "/data/us-equities" or "s3://bucket/..."
    storage_options: Mapping[str, str] = ...    # region, credentials, endpoint

    @property
    def is_remote(self) -> bool:
        return "://" in self.root               # the root already says which
```

There is no `LocalDataset` and no `S3Dataset`. The two differ in a prefix and
some connection settings, and a second type would only be a place for them to
drift apart.

**Query engines are described, not abstracted.** A dataset reference exposes a
method per engine returning *configuration*, never a live connection —
otherwise describing where files live would mean importing every engine.

```python
    def as_polars(self) -> dict[str, Any]:      # kwargs for scan_parquet
        ...
    def as_duckdb(self) -> Sequence[str]:       # SQL to run before querying
        ...                                     # empty for a local root
```

Supporting another engine is another `as_*` method. There is no query-engine
interface, because in practice only a few engines exist and a method each is
cheaper than a hierarchy.

**Credentials come from the environment, never from a spec or a config file.**
Those get committed, and a spec travels through a queue. Only the region and an
optional endpoint are configuration.

polars and pyarrow read `AWS_*` themselves, so writes and the default reader
need nothing further. DuckDB does not, so `as_duckdb` passes them explicitly —
which is the kind of difference that is invisible until someone switches engine
in production.

Polars and DuckDB are both wired up. Polars is the default; both read parquet,
push filters down, and read object storage directly. A test asserts they return
identical frames, since nothing else forces them to agree.

**One writer.** Only the ingestion job writes. That is why there is no locking,
no write interface on the read path, and no reconciliation between writers.

**Schemas live with the code that writes them**, as named constants — readers
get the schema back from the parquet footer, so it is a write-side concern. A
dictionary keyed by table name would fail on a typo at runtime; constants fail
at import.

**No ORM.** It would only ever declare column types. Sessions, relationships
and query building are never used, because queries go through SQL or Polars
directly.

**Each table declares what identifies a row** and what counts as its content.
Two rows sharing a key are the same fact asserted twice, and only the newest is
read. Corporate actions key on *kind* as well as ticker and date, because a
dividend and a split can share an ex-date: two facts about that day, not one
correcting the other.

---

## Time, and what we knew when

The distinguishing idea in the whole system. Everything in this section follows
from one problem: financial data is restated, so "the price on this date" is
not a fact but a sequence of assertions about that date, each made at a
different time.

**Every row carries two timestamps.** `event_ts` is what the row is about;
`knowledge_ts` is when we learned it. Rows are appended, never updated. A
restatement is a new row.

Both are timestamps rather than dates, and both are timezone aware. Daily bars
are what we have, not a limit of the model — a date on the event axis would
rule out intraday data by type.

**A daily bar is stamped at the exchange close**, not at midnight. A bar is not
knowable until the session ends, and that is also when a signal is computed.
The close hour is one constant shared by ingestion and the calendar; if those
two ever disagreed, a rebalance would exclude its own day's bar, so they are
not allowed to be defined separately.

**`knowledge_ts` is decided per row, not per batch:**

| Case | Stamped |
|---|---|
| Not seen before | at its `event_ts` |
| Contradicts a row we hold | at the ingestion time |
| Identical to a row we hold | not written at all |

First observations take their event time because exchange prices are published
at the close with no revision lag — the bar for a given day really was public
that day, so this models publication rather than inventing it. The same rule
would be a lie for anything with a reporting lag, such as earnings.

**The second rule is the one that matters.** Yahoo restates prices after a
split, so a re-fetch in 2026 returns different 2020 prices. Stamping those at
their event time would claim we knew split-adjusted numbers in 2020, and let a
point-in-time backtest see the future through the knowledge axis rather than
the event axis. Comparing against the store at write time is what separates the
two cases.

**Dropping unchanged rows** makes a re-run genuinely idempotent rather than
appending agreeing duplicates for reads to hide. The log then holds exactly the
first observations plus the real corrections.

**Comparison is exact, not tolerance-based.** A tolerance would silently
swallow small genuine corrections. Parquet round-trips f64 exactly, and a
second ingestion of unchanged data writes zero rows in practice, so there is no
float jitter to absorb.

**Backdating a correction is allowed.** Writing a row with an earlier
`knowledge_ts` is a real operation: a vendor with a genuine point-in-time feed
supplies real publication times, and a fix to our own normalisation may be a
value that truly was available then.

What is refused is a correction carrying the *same* `knowledge_ts` as the row
it corrects. Two rows sharing a key and an instant have no defined winner, so a
reader would pick one arbitrarily. The ambiguity is the bug, not the direction.

**Reads are bounded on both axes.** A decision at time `t` sees only
`event_ts <= t` and `knowledge_ts <= t`. Bounding only the first would let a
price restated later leak into a past decision.

**A strategy chooses the shape it works in**, independently of which engine
fetched the window. Arrow is the common currency between engines, so polars,
pandas and arrow are each one call away whichever reader was used.

---

## Ingestion

**Full history is re-fetched per ticker, every run.** Yahoo's prices are
already split-adjusted, so a new split restates a ticker's entire series. A
batch covering only recent bars would leave the store mixing two conventions,
and a lookback window crossing that boundary would compute a return that never
happened.

**Vendor calls are retried; nothing else is.** A public API we do not control
is the only part of this system that fails for reasons unrelated to our inputs.

**A symbol that does not exist is not retried.** Nothing about the request will
change on a second attempt, so retrying only spends time and rate limit. The
distinction comes from the vendor library's own exception types rather than
from matching on error text, which breaks the next time they reword a message.

---

## Strategies

**A strategy answers one question: given this moment, what should the book
hold?** It returns weights as fractions of gross notional, plus the scores it
computed on the way if it has any worth showing.

**It is the only real extension point**, and the only base class — the engine
is handed one and calls it without knowing which it is. Every other choice is
made once at startup, so those are functions or parameters.

```python
class Strategy(ABC):
    lookback_sessions: int                      # a constant satisfies this

    @abstractmethod
    def allocate(self, view: MarketView) -> Allocation: ...
```

Two methods' worth of surface. A strategy never fetches data, never writes a
date filter, and never learns where anything is stored.

**Sizing belongs to the strategy, not the engine.** The engine fetches data,
walks the calendar and measures what the book earned; it has no opinion about
how a portfolio is shaped. An engine that ranked into buckets itself would have
made a research choice while wearing infrastructure clothes.

**Weight is not a function of score.** Even with equal-weighted buckets, a name
up 61% and one up 14% are held identically, while rank six and rank seven
differ by an entire position over a fraction of a percent. Volatility scaling,
position caps, correlation, sector limits and turnover all make a
higher-scoring name worth holding less. Sizing is a decision, not a
calculation.

Scores travel alongside the weights so a report can show both. Where they
diverge is where portfolio construction overrode the signal, which is worth
being able to see.

**Strategies hold no state.** One declares how far back it needs to see and is
handed a snapshot. It does not see the stream and does not manage a buffer.
That keeps it testable: build a snapshot, call the function, check the result —
no ordering to reproduce, nothing to reset between runs.

The lookback is configuration, not state. Declaring how much history is needed
is a strategy parameter; implementing the window that supplies it is plumbing,
and belongs to the engine along with buffering and querying.

**A strategy can be a live object or a name.** Live objects work locally; named
references work on a grid, because a worker can rebuild them. One written ad
hoc reports itself as not reproducible rather than pretending otherwise.

```python
StrategySpec = Strategy | StrategyRef           # the object, or "name" + params
```

Registration is a line in a read-only mapping, so what exists is whatever that
file says. Nothing registers itself at import time.

---

## The engine

**A spec is what changes the answer; a job is what schedules it.** They are
separate types so the same spec runs anywhere and still produces the same
result.

```python
@dataclass(frozen=True)
class BacktestSpec:                 # pure data: no connections, no live objects
    universe: tuple[str, ...]       # so it serialises to JSON and rides a queue
    strategy: StrategySpec
    as_of_knowledge: datetime       # resolved once, never per worker
    ...
    def content_id(self) -> str | None:
        """Hash of the canonical form. Same spec, same directory."""

@dataclass(frozen=True)
class BacktestJob:                  # dispatch only
    spec: BacktestSpec
    ref: DatasetRef                 # where this worker reads from
    output_uri: str
    run_id: str
```

That split is what makes a grid work without coordination. `run_backtest(spec,
ref)` is a pure function, and the content hash decides where the result lands,
so N workers write to N distinct directories by construction and a redelivered
job overwrites rather than duplicating.

**There is no capital or notional in a spec.** A weight-based dollar-neutral
backtest gives the same returns and Sharpe at any size. Notional is a
presentation parameter, used only to display dollar figures.

**Costs stay on the spec** rather than the strategy. They are an assumption
about the world rather than about the signal, so one strategy should be
runnable under several.

**One query per rebalance.** Each fetches the lookback window ending at that
rebalance. The time bounds are in the query, so a strategy cannot see past them
however it is written.

Consecutive windows overlap, so rows are read more than once — lookback divided
by rebalance interval. Monthly rebalancing with a sixty-session lookback reads
each row about three times, which is not worth avoiding. Daily rebalancing with
the same lookback reads each row sixty times, which is.

The alternative is one ordered query walked forward with a rolling buffer. It
reads every row once, but touches every row in Python to maintain the buffer,
while the current approach stays inside the query engine. At this size the
simpler one is also the faster one. Switch when rebalances become frequent
enough that the overlap dominates; strategy code does not change either way,
because a strategy only ever sees a bounded window.

---

## Reporting

**Metrics are separate from rendering.** Metrics are unit-testable against
hand-computed cases; HTML is not.

**A metric is a function plus a description of itself.** No base class, because
nothing dispatches on a metric at runtime.

```python
@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    compute: Callable[[BacktestResult], float]
    unit: str = "ratio"                    # "ratio" | "percent"
    higher_is_better: bool | None = True   # None where neither direction is

METRICS = (..., Metric("hit_rate", "Periods positive", hit_rate, unit="percent"))
```

The renderer iterates `METRICS` and never names a metric, so a new one appears
in the table with a sortable column and its own tinting without the report
knowing it exists.

**The report is one self-contained file.** No external assets, so it opens from
an email attachment or from object storage — which is where a report actually
gets read.

**Interaction is presentational.** Hiding a series, sorting a column or
switching tab changes what is easy to read, never what the numbers are, and
every charted value is also in the table.
