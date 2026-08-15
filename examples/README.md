# examples

Complete, runnable versions of the snippets in the top-level README. Run
`backtester ingest` first so there is data to read.

| File | What it shows |
|---|---|
| [`custom_strategy.py`](custom_strategy.py) | A strategy that is not a sign flip of the shipped one, run from a live object with no registration |
| [`parallel_sweep.py`](parallel_sweep.py) | Six backtests across processes, then one report over all of them |

```bash
python examples/custom_strategy.py
python examples/parallel_sweep.py
backtester report out/* --out out/report.html
```

These are illustrations rather than part of the package, so they are not
installed and not covered by the test suite. CI does lint and type-check them,
which is enough to keep them from going stale silently.
