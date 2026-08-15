# Design decisions

1. Data is stored as parquet files. The format is fixed, not configurable.
Nothing in the system needs a second format, and supporting one costs more than
it returns.

2. Local disk and S3 are both supported. This is the only storage difference
that matters, because it is what lets workers on a grid read the same data.

3. DatasetRef holds the two things that differ between local and S3: the path
prefix, and the setup a reader needs. Everything else in the codebase works
without knowing which one it is talking to.

4. DatasetRef.table(name) builds the path for a table. The layout convention is
written down in one place, so changing it later means changing one function.

5. DatasetRef exposes as_duckdb() and as_polars(). These return configuration,
not connections. Returning connections would mean importing every engine just
to describe where files live.

6. New query engines are added as new as_* methods. There is no query engine
abstraction. In practice there are only a few engines anyone uses, so a method
per engine is cheaper than an interface.

7. The query engine is not chosen yet. DuckDB and Polars are both viable. Both
read parquet, both push filters down, and both read S3 directly.

8. Data is written only by the ingestion job. Nothing else writes. This is why
there is no locking and no write interface on the read path.

9. Column schemas live with the ingestion code, as named constants. They are
only needed when writing, because readers get the schema back from the parquet
footer. A dictionary keyed by table name would fail on a typo at runtime;
constants fail at import.

9a. No ORM. It would only be used to declare column types. Sessions,
relationships and query building are never used, because queries go through SQL
or Polars directly.

10. Every row carries two timestamps. event_ts is what the row is about,
knowledge_ts is when we learned it. Rows are appended, never updated. A
restatement is a new row.

10a. Both are timestamps, not dates, and both are timezone aware in
America/New_York. Daily bars are what we have now, not a limit of the model.
Using a date for the event axis would rule out intraday data by type.

10b. A daily bar is stamped at the exchange close, not at midnight. Yahoo dates
bars at midnight, but a bar is not knowable until the session ends, and that is
also when a signal is computed.

10c. Ingestion re-fetches full history for every ticker on every run. Yahoo's
prices are already split-adjusted, so a new split restates a ticker's entire
series. A batch covering only recent bars would leave the store mixing two
conventions, and a lookback window crossing the boundary would compute a
return that never happened.

10d. knowledge_ts is stamped with when we actually learned a row. For
backfilled history that is the moment of the backfill, which is honest but
means the knowledge axis offers no protection for backfilled data. The engine
detects this and refuses rather than silently returning empty windows.
Fabricating plausible knowledge times was rejected — a store that asserts
beliefs we never held is worse than one that admits it does not know.

11. Reads are bounded on both timestamps. A decision made at time t sees only
event_ts <= t and knowledge_ts <= t. Bounding only the first would let a price
that was restated later leak into a past decision.

12. BacktestSpec is what changes the answer. BacktestJob is what schedules it.
They are separate so the same spec can be run anywhere and still produce the
same result.

13. Strategies can be passed as live objects or referenced by name. Live objects
work locally. Named references work on a grid, because the worker can rebuild
them. A strategy written ad hoc reports itself as not reproducible rather than
pretending otherwise.

14. Strategy is the only real extension point. It is a base class because the
engine is handed one and calls it without knowing which strategy it is. Other
choices are made once at startup, so they are functions or parameters.

14a. Getting data to the strategy is the engine's job. Buffering, streaming and
querying all sit in the engine. None of it is visible to a strategy.

14b. Strategies hold no state. A strategy declares how far back it needs to
see, and is handed a snapshot. It does not see the stream and does not manage
a buffer. This keeps strategies testable: build a snapshot, call the function,
check the scores. No event ordering to reproduce, nothing to reset between
runs.

14c. lookback is configuration, not state. Declaring how much history is needed
is a strategy parameter. Implementing the window that supplies it is plumbing.

14d. The engine runs one query per rebalance. Each query fetches the lookback
window ending at that rebalance and hands the result to the strategy. The time
bounds are in the query, so a strategy cannot see past them.

14e. Consecutive windows overlap, so rows are read more than once. How many
times is lookback divided by rebalance interval. Monthly rebalancing with a
60 day lookback reads each row about 3 times, which is not worth avoiding.
Daily rebalancing with the same lookback reads each row 60 times, which is.

14f. The alternative is one ordered query, walked forward, with a rolling
buffer holding the last lookback of data. It reads every row once, but it
touches every row in Python to maintain the buffer, while the current approach
stays inside the query engine. At our size the current approach is both simpler
and faster. Switch when rebalances become frequent enough that 14e dominates.
Strategy code does not change either way, because a strategy only ever sees a
MarketView.

15. Strategies return a plain mapping of ticker to score. There is no Signal
type, because it would only add a timestamp the caller already has.

15a. Portfolio construction and costs are not built yet. Current focus is
loading data reliably, and running a backtest as a unit of work that can be
scheduled on a grid. Sizing and cost parameters will sit on the spec as plain
fields when they are added, so that one signal can be run under several
assumptions.

16. There is no capital or notional in the spec. A weight-based dollar-neutral
backtest gives the same returns and Sharpe at any size. Notional is only used to
display dollar figures in the report.
