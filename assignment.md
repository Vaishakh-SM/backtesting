# Quantitative Developer — Take-Home Assignment

Thanks for taking the time to do this. We've tried to keep it short and
realistic. It loosely reflects the kind of work you'd actually do: building the
tooling that lets researchers run, test, and analyze strategies.

This is a **development** exercise, not a research one. We are **not** asking
you to find a profitable strategy or to have a view on markets. We want to see
how you build the tooling around it.

The objective of this project is to showcase your whole software engineering
practices, not just your coding skills. Think about how you would package,
document and test this software.

There are no constraints on libraries or tools here. You can use whatever you
need if you think that makes sense.

## The setup

A researcher has a strategy idea. We want you to build a platform that helps
going from "idea" to "something we can run, backtest, and see if it works". We
want you to build a small, clean piece of that pipeline.

You'll take **one simple, fully-specified strategy** (below) and build the
software that:

1. **Gets the data it needs**, reliably and reproducibly.
2. **Runs the strategy** over history (a backtest).
3. **Produces a report** a researcher could look at to decide what to do next.

Assume this is the *first* of many strategies the researcher will hand you. Build
it so the next one is easy to add.

## The strategy (deliberately trivial — not the point)

Implement **either** a short-term **reversal** or an ***N*-day momentum**
strategy — long/short and cross-sectional, over a universe of liquid US equities
(pick, say, 20–50 companies and fetch data through a public source):

- On each rebalance date (e.g. monthly), rank the universe by trailing return
  over the last *N* days (you choose *N*).
- Go **long** the top fraction (e.g. top 20%), **short** the bottom fraction,
  equal-weighted. Momentum buys the winners; reversal does the opposite.
- Hold until the next rebalance.

We will not judge the returns — we are more interested in the tool you develop.

## What to build

A small system with clear separation between:

- **Data** — a reusable way to fetch data.
- **Strategy / backtest** — the engine that turns the strategy above into
  positions and a P&L series over time. Designed so new strategies can reuse it.
- **Reporting** — the output and metrics to look at to assess the performance of
  the strategy.

## The report

Imagine the portfolio manager will look at your report and decide whether this strategy is worth pursuing.
**That decision is theirs, not yours** — your job is to give them the right
information. You should include metrics and analytics which would help them in making this decision.

## Deliverable

A git repository (a zip, or a link) containing runnable and deployable **python** code.

## Separately from the repo

You can send these to us separately from the git repository:

- **How you used AI tools, and where you accepted, changed, or rejected their
  output.** We use these tools too — we're interested in your judgment in using
  them, not whether you used them.
- Logs / chat history with the AI tools you used during development.

## Scope & expectations

- You have **one week** to return it, but it's designed to take roughly a
  **focused day** — please don't sink a week into it. We would much rather see a
  clean, well-structured *slice* than a sprawling, unfinished system.
- There is no hidden "correct" answer. Make reasonable assumptions, write them
  down, and move on.

If anything is genuinely blocking you, make a sensible assumption, note it, and
keep going — that itself is part of what we're looking for.

Have fun with it.
assignment 1.md
Displaying assignment 1.md.