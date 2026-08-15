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

9b. Each table declares what identifies a row and what counts as its content.
Two rows sharing a key are the same fact asserted twice, and only the newest is
read. Actions key on kind as well as ticker and date, because a dividend and a
split can share an ex-date and are two facts about that day rather than one
correcting the other.

10. Every row carries two timestamps. event_ts is what the row is about,
knowledge_ts is when we learned it. Rows are appended, never updated. A
restatement is a new row.

10a. Both are timestamps, not dates, and both are timezone aware in
America/New_York. Daily bars are what we have now, not a limit of the model.
Using a date for the event axis would rule out intraday data by type.

10b. A daily bar is stamped at the exchange close, not at midnight. Yahoo dates
bars at midnight, but a bar is not knowable until the session ends, and that is
also when a signal is computed.

10b1. The close hour is one constant shared by ingestion and the calendar.
Ingestion stamps bars with it and the calendar stamps rebalance instants with
it. If those two ever disagreed, a rebalance would exclude its own day's bar,
so they are not allowed to be defined separately.

10c. Ingestion re-fetches full history for every ticker on every run. Yahoo's
prices are already split-adjusted, so a new split restates a ticker's entire
series. A batch covering only recent bars would leave the store mixing two
conventions, and a lookback window crossing the boundary would compute a
return that never happened.

10d. knowledge_ts is decided per row, not per ingestion batch:

  - a row we have not seen before is stamped at its event_ts
  - a row that contradicts one we hold is stamped at the ingestion time
  - a row identical to one we hold is not written at all

10e. First observations are stamped at event_ts because exchange prices are
published at the close with no revision lag. The bar for a given day really
was public that day, so this models publication rather than inventing it. The
same rule would be a lie for data with a genuine reporting lag, such as
earnings, which is not published on the day it describes.

10f. The lie the second rule avoids is the important one. Yahoo restates prices
after a split, so a re-fetch in 2026 returns different 2020 prices. Stamping
those at their event_ts would claim we knew the split-adjusted numbers in 2020,
which would let a point-in-time backtest see the future through the knowledge
axis. Comparing against the store at write time is what separates the two
cases.

10g. Dropping unchanged rows makes a re-run genuinely idempotent rather than
appending duplicates and relying on reads to hide them. It also means the log
holds exactly the first observations plus the real corrections, and removes the
storage cost of re-fetching full history.

8a. Vendor calls are retried with exponential backoff; nothing else is. A
public API we do not control is the only part of this system that fails for
reasons unrelated to our inputs.

8b. A symbol that does not exist is not retried. Nothing about the request will
change on a second attempt, so retrying only spends time and rate limit. The
distinction comes from yfinance's own exception types rather than from matching
on error text.

10i. Backdating a correction is allowed. Writing a row with a knowledge_ts
earlier than now is a real operation: a vendor with a genuine point-in-time
feed supplies real publication times, and a fix to our own normalisation may be
a value that truly was available at the time.

10j. What is refused is a correction carrying the same knowledge_ts as the row
it corrects. Two rows sharing a key and an instant have no defined winner, so a
reader would pick one arbitrarily. The ambiguity is the bug, not the direction,
so the check is on ties rather than on backdating.

10h. Comparison is exact, not tolerance-based. A tolerance would silently
swallow small genuine corrections. Parquet round-trips f64 exactly, and a
second ingestion of unchanged data writes zero rows in practice, so there is no
float jitter to absorb.

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

15. A strategy answers one question: given this moment, what should the book
hold. It returns an Allocation — weights as fractions of gross notional, plus
the scores it computed on the way if it has any worth showing.

15a. Sizing belongs to the strategy, not the engine. The engine fetches data,
walks the rebalance calendar and measures what the book earned; it has no
opinion about how a portfolio is shaped. An engine that called rank_weights
itself would have decided that portfolios are made by ranking into buckets,
which is a research choice wearing infrastructure clothes.

15b. Weight is not a function of score. Even with equal-weighted buckets, a
name up 61% and one up 14% are held identically, while rank six and rank seven
differ by an entire position for a fraction of a percent. Volatility scaling,
position caps, correlation, sector limits and turnover all make a
higher-scoring name worth holding less. That is why sizing is a decision rather
than a calculation.

15c. Scores travel with the allocation so a report can show both. Where they
diverge is where portfolio construction overrode the signal, which is worth
being able to see.

15d. Costs stay on the spec. They are an assumption about the world rather than
about the signal, so one strategy should be runnable under several.

16. There is no capital or notional in the spec. A weight-based dollar-neutral
backtest gives the same returns and Sharpe at any size. Notional is only used to
display dollar figures in the report.
