# examples

Complete, runnable versions of the snippets in the top-level README. Run
`backtester ingest` first so there is data to read.

| File | What it shows |
|---|---|
| [`custom_strategy.py`](custom_strategy.py) | A strategy that is not a sign flip of the shipped one, run from a live object with no registration |
| [`parallel_sweep.py`](parallel_sweep.py) | Six backtests across processes, then one report over all of them |
| [`grid_submit.py`](grid_submit.py) + [`grid_worker.py`](grid_worker.py) | The same sweep as messages a queue could carry, and a worker that runs one |

```bash
python examples/custom_strategy.py
python examples/parallel_sweep.py
backtester report out/* --out out/report.html
```

The grid pair is two processes rather than one, so it is a pipeline. Substitute
a queue for the loop and this is the deployed shape:

```bash
python examples/grid_submit.py | while read -r message; do
    echo "$message" | STORE_ROOT=./data/us-equities OUT_ROOT=out python examples/grid_worker.py
done
```

```
7d86e6742c78f137  ->  out/7d86e6742c78f137
85ec88486a52e855  ->  out/85ec88486a52e855
3c070a38bc2f0db1  ->  out/3c070a38bc2f0db1
```

Feed the same message in twice and it prints the same directory: the name is a
hash of the spec, so a queue that delivers twice does not produce two answers.

These are illustrations rather than part of the package, so they are not
installed and not covered by the test suite. CI does lint and type-check them,
which is enough to keep them from going stale silently.
