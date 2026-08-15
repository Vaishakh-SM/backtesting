"""One self-contained HTML file.

No external assets, so it opens from an attachment, from object storage, or
from a laptop with no network — which is where a report actually gets read.

What it puts in front of a PM, in order: what was run, the headline numbers,
the equity curve, what trading cost, the full table, and the assumptions that
make the numbers optimistic. The last section is not an appendix. A report that
shows a Sharpe without saying the universe is survivorship-biased is worse than
no report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from qrt.backtest.spec import BacktestResult
from qrt.report.charts import Series, legend, line_chart
from qrt.report.metrics import METRICS, compute

MAX_SERIES = 8  # the categorical ceiling; past it identity stops being readable

# (result, label, metrics) for each run being reported on.
Measured = Sequence[tuple[BacktestResult, str, Mapping[str, float]]]

_STYLE = """
:root {
  color-scheme: light;
  --surface: #fcfcfb; --plane: #f9f9f7;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --hairline: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a;
  --series-4: #eda100; --series-5: #e87ba4; --series-6: #008300;
  --series-7: #4a3aa7; --series-8: #e34948;
  --good: #0ca30c; --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface: #1a1a19; --plane: #0d0d0d;
    --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --hairline: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
    --series-4: #c98500; --series-5: #d55181; --series-6: #008300;
    --series-7: #9085e9; --series-8: #e66767;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface: #1a1a19; --plane: #0d0d0d;
  --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --hairline: rgba(255,255,255,0.10);
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
  --series-4: #c98500; --series-5: #d55181; --series-6: #008300;
  --series-7: #9085e9; --series-8: #e66767;
}

* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 20px 72px;
  background: var(--plane); color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 960px; margin: 0 auto; }
h1 { font-size: 24px; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 15px; margin: 0 0 16px; letter-spacing: 0.02em;
     text-transform: uppercase; color: var(--ink-2); }
h3 { font-size: 14px; margin: 0 0 10px; color: var(--ink-2); font-weight: 600; }
p { margin: 0 0 12px; color: var(--ink-2); }
.sub { color: var(--muted); font-size: 13px; margin-bottom: 28px; }

.card {
  background: var(--surface); border: 1px solid var(--hairline);
  border-radius: 10px; padding: 22px 24px; margin-bottom: 20px;
}

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 2px;
        background: var(--hairline); border-radius: 8px; overflow: hidden; }
.kpi { background: var(--surface); padding: 14px 16px; }
.kpi .label { font-size: 12px; color: var(--muted); }
.kpi .value { font-size: 26px; margin-top: 2px; letter-spacing: -0.02em; }
.kpi .note { font-size: 11px; color: var(--muted); margin-top: 2px; }
.pos { color: var(--good); } .neg { color: var(--critical); }

.chart { width: 100%; height: auto; display: block; }
.chart .grid { stroke: var(--grid); stroke-width: 1; }
.chart .axis, .chart .baseline { stroke: var(--axis); stroke-width: 1; }
.chart .tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.chart .line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.chart .area { stroke: none; opacity: 0.16; }
.chart .endlabel { font-size: 11px; font-weight: 600; }

.s1 { stroke: var(--series-1); } .s1.area, .s1.endlabel, .s1.swatch { fill: var(--series-1); }
.s2 { stroke: var(--series-2); } .s2.area, .s2.endlabel, .s2.swatch { fill: var(--series-2); }
.s3 { stroke: var(--series-3); } .s3.area, .s3.endlabel, .s3.swatch { fill: var(--series-3); }
.s4 { stroke: var(--series-4); } .s4.area, .s4.endlabel, .s4.swatch { fill: var(--series-4); }
.s5 { stroke: var(--series-5); } .s5.area, .s5.endlabel, .s5.swatch { fill: var(--series-5); }
.s6 { stroke: var(--series-6); } .s6.area, .s6.endlabel, .s6.swatch { fill: var(--series-6); }
.s7 { stroke: var(--series-7); } .s7.area, .s7.endlabel, .s7.swatch { fill: var(--series-7); }
.s8 { stroke: var(--series-8); } .s8.area, .s8.endlabel, .s8.swatch { fill: var(--series-8); }

.legend { list-style: none; display: flex; flex-wrap: wrap; gap: 16px;
          margin: 14px 0 0; padding: 0; font-size: 13px; color: var(--ink-2); }
.legend li { display: flex; align-items: center; gap: 7px; }
.swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; stroke: none; }

.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th, td { padding: 9px 12px; text-align: right; border-bottom: 1px solid var(--hairline);
         font-variant-numeric: tabular-nums; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; font-variant-numeric: normal; }
thead th { color: var(--muted); font-weight: 600; font-size: 12px;
           text-transform: uppercase; letter-spacing: 0.03em; }
tbody tr:last-child td { border-bottom: none; }
td .note { display: block; font-size: 11px; color: var(--muted); font-variant-numeric: normal; }

dl { margin: 0; display: grid; grid-template-columns: max-content 1fr;
     gap: 6px 20px; font-size: 13.5px; }
dt { color: var(--muted); } dd { margin: 0; font-variant-numeric: tabular-nums; }

.caveats li { margin-bottom: 9px; color: var(--ink-2); }
.caveats { padding-left: 20px; margin: 0; }
.empty { color: var(--muted); font-style: italic; }
footer { color: var(--muted); font-size: 12px; text-align: center; margin-top: 32px; }
footer code { font-size: 11.5px; }

/* Theme control. The page follows the system by default; this overrides it. */
.theme { display: flex; gap: 2px; padding: 2px; border-radius: 8px;
         background: var(--hairline); }
.theme button { border: 0; background: transparent; color: var(--muted);
                font: inherit; font-size: 12px; padding: 5px 11px;
                border-radius: 6px; cursor: pointer; }
.theme button[aria-pressed="true"] { background: var(--surface); color: var(--ink); }
.topbar { display: flex; align-items: flex-start; justify-content: space-between;
          gap: 16px; }

/* Sortable table */
table.sortable th[data-sort] { cursor: pointer; user-select: none; }
table.sortable th[data-sort]:hover { color: var(--ink); }
table.sortable th[aria-sort]::after { content: " \2191"; }
table.sortable th[aria-sort="descending"]::after { content: " \2193"; }
tbody tr:hover td { background: var(--hairline); }

/* Hover layer */
.plot { position: relative; margin: 0; }
.hover-target { fill: transparent; }
.crosshair { stroke: var(--axis); stroke-width: 1; visibility: hidden; }
.tooltip { position: absolute; pointer-events: none; z-index: 2;
           background: var(--surface); border: 1px solid var(--hairline);
           border-radius: 7px; padding: 8px 10px; font-size: 12px;
           box-shadow: 0 2px 10px rgba(0,0,0,0.10); min-width: 132px; }
.tooltip .when { color: var(--muted); margin-bottom: 5px; }
.tooltip .row { display: flex; align-items: center; gap: 7px;
                justify-content: space-between; }
.tooltip .row span:last-child { font-variant-numeric: tabular-nums; color: var(--ink); }
.tooltip .name { display: flex; align-items: center; gap: 6px; color: var(--ink-2); }

.legend .toggle { border: 0; background: transparent; font: inherit;
                  color: var(--ink-2); cursor: pointer; padding: 2px 0;
                  display: flex; align-items: center; gap: 7px; }
.legend .toggle[aria-pressed="false"] { opacity: 0.4; text-decoration: line-through; }
.hidden-series { display: none; }
"""

# Inline, because the report has to work from an attachment with no network.
# Everything here is presentational: hiding a series or sorting a column
# changes what is easy to read, never what the numbers are.
_SCRIPT = """
(function () {
  const root = document.documentElement;
  const KEY = "qrt-theme";

  function applyTheme(choice) {
    if (choice === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", choice);
    document.querySelectorAll(".theme button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.theme === choice));
    });
    try { localStorage.setItem(KEY, choice); } catch (e) { /* private mode */ }
  }

  let saved = "system";
  try { saved = localStorage.getItem(KEY) || "system"; } catch (e) { /* ignore */ }
  applyTheme(saved);
  document.querySelectorAll(".theme button").forEach(function (b) {
    b.addEventListener("click", function () { applyTheme(b.dataset.theme); });
  });

  // --- sortable table ------------------------------------------------------
  document.querySelectorAll("table.sortable").forEach(function (table) {
    const body = table.tBodies[0];
    table.querySelectorAll("th[data-sort]").forEach(function (th) {
      th.addEventListener("click", function () {
        const column = Number(th.dataset.sort);
        const descending = th.getAttribute("aria-sort") !== "descending";
        const rows = Array.from(body.rows);

        rows.sort(function (a, b) {
          const x = a.cells[column].dataset.value;
          const y = b.cells[column].dataset.value;
          const nx = parseFloat(x), ny = parseFloat(y);
          const cmp = (isNaN(nx) || isNaN(ny)) ? String(x).localeCompare(String(y)) : nx - ny;
          return descending ? -cmp : cmp;
        });

        rows.forEach(function (r) { body.appendChild(r); });
        table.querySelectorAll("th").forEach(function (o) { o.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", descending ? "descending" : "ascending");
      });
    });
  });

  // --- chart hover ---------------------------------------------------------
  document.querySelectorAll(".plot[data-chart]").forEach(function (figure) {
    const chart = JSON.parse(figure.dataset.chart);
    const svg = figure.querySelector("svg");
    const crosshair = figure.querySelector(".crosshair");
    const tip = figure.querySelector(".tooltip");
    const percent = chart.format.indexOf("%") !== -1;

    function visible(slot) {
      return !svg.querySelector('.line.s' + slot + '.hidden-series');
    }

    function show(event) {
      const box = svg.getBoundingClientRect();
      const scale = svg.viewBox.baseVal.width / box.width;
      const x = (event.clientX - box.left) * scale;

      const shown = chart.series.filter(function (s) { return visible(s.slot); });
      if (!shown.length) return;

      let nearest = null;
      shown[0].points.forEach(function (p) {
        if (!nearest || Math.abs(p[0] - x) < Math.abs(nearest[0] - x)) nearest = p;
      });

      crosshair.setAttribute("x1", nearest[0]);
      crosshair.setAttribute("x2", nearest[0]);
      crosshair.style.visibility = "visible";

      let html = '<div class="when">' + nearest[3] + "</div>";
      shown.forEach(function (s) {
        let point = null;
        s.points.forEach(function (p) {
          if (!point || Math.abs(p[0] - nearest[0]) < Math.abs(point[0] - nearest[0])) point = p;
        });
        if (!point) return;
        const value = percent ? (point[2] * 100).toFixed(1) + "%" : point[2].toFixed(3);
        html += '<div class="row"><span class="name">'
              + '<span class="swatch s' + s.slot + '"></span>' + s.label
              + "</span><span>" + value + "</span></div>";
      });
      tip.innerHTML = html;
      tip.hidden = false;

      const left = (nearest[0] / scale) + 14;
      const flip = left + tip.offsetWidth > box.width;
      tip.style.left = (flip ? left - tip.offsetWidth - 28 : left) + "px";
      tip.style.top = "12px";
    }

    function hide() {
      crosshair.style.visibility = "hidden";
      tip.hidden = true;
    }

    svg.addEventListener("mousemove", show);
    svg.addEventListener("mouseleave", hide);
  });

  // --- legend toggles ------------------------------------------------------
  document.querySelectorAll(".legend .toggle").forEach(function (button) {
    button.addEventListener("click", function () {
      const on = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", String(on));
      const card = button.closest("section");
      card.querySelectorAll(".s" + button.dataset.slot).forEach(function (mark) {
        if (mark.closest(".legend")) return;
        mark.classList.toggle("hidden-series", !on);
      });
    });
  });
})();
"""

# One line in the footer rather than a section. The full write-up lives in
# docs/ASSUMPTIONS.md; what a reader needs here is to know it exists.
CAVEATS = [
    "The universe is a fixed list of names chosen for being liquid <em>today</em>, "
    "which was not knowable at the start of the window. Anything that delisted or "
    "collapsed is absent, so these results are optimistic by an amount this "
    "backtest cannot measure.",
    "Costs are a flat rate on turnover. There is no market impact and no size "
    "dependence, so the numbers say nothing about how much capital this could take.",
    "No borrow cost, financing or margin. A real long/short book pays to borrow "
    "the short leg; ignoring it flatters net performance.",
    "Signals are computed on the close and held from the next session. Execution "
    "is assumed to happen at that close in full, with no slippage or partial fills.",
    "Dividends are handled where a strategy asks for them, but the shipped "
    "strategy ranks on price return. On this universe that biases the ranking "
    "against high-yielding names.",
]


def render(
    results: Sequence[BacktestResult],
    output_path: Path,
    display_notional: float = 1_000_000.0,
) -> Path:
    """Write the report, return its path.

    `display_notional` scales P&L into dollars for presentation only. A
    weight-based dollar-neutral book gives identical returns at any size, so it
    changes no metric.
    """
    if not results:
        raise ValueError("no results to report on")

    # Sorted by label so the document is the same whatever order the shell
    # expanded the arguments in — `out/*` gives content-hash order, which is
    # arbitrary — and so related runs sit next to each other.
    ordered = sorted(zip(results, _labels(list(results)), strict=True), key=lambda pair: pair[1])
    shown = ordered[:MAX_SERIES]
    dropped = len(ordered) - len(shown)
    measured = [(result, label, compute(result)) for result, label in shown]

    body = [
        _header([result for result, _ in shown]),
        _kpis(measured),
        _equity(measured),
        _drawdown(measured),
        _table(measured, dropped),
        _spec_details([result for result, _ in shown], display_notional),
        "<footer>Generated by qrt. Every number is reproducible from the spec "
        "above. Known biases and what these results exclude: "
        "<code>docs/ASSUMPTIONS.md</code>.</footer>",
    ]

    html = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Backtest report</title><style>{_STYLE}</style></head>"
        f"<body><main>{''.join(body)}</main><script>{_SCRIPT}</script></body></html>"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    return output_path


# --- sections --------------------------------------------------------------


def _labels(results: Sequence[BacktestResult]) -> list[str]:
    """Name each run by what distinguishes it from the others.

    Printing every parameter produces labels wider than the chart and buries
    the one thing that actually changed. Where three runs differ only in
    lookback, the labels are "lookback 20", "lookback 60", "lookback 120".
    """
    params = [dict(getattr(r.spec.strategy, "params", {})) for r in results]
    varying = sorted(
        {key for p in params for key in p}
        - {key for key in {k for p in params for k in p} if len({p.get(key) for p in params}) == 1}
    )

    labels = []
    for result, values in zip(results, params, strict=True):
        strategy = result.spec.strategy
        name = str(getattr(strategy, "name", type(strategy).__name__))
        labels.append(
            " ".join(f"{_short(k)} {values.get(k)}" for k in varying) if varying else name
        )
    return labels


def _short(parameter: str) -> str:
    """Drop the unit suffix — the axis and the docs carry it."""
    return parameter.removesuffix("_sessions").removesuffix("_fraction").replace("_", " ")


def _header(results: Sequence[BacktestResult]) -> str:
    spec = results[0].spec
    runs = f"{len(results)} runs" if len(results) > 1 else "1 run"
    return (
        "<div class='topbar'><div>"
        "<h1>Backtest report</h1>"
        f"<p class='sub'>{runs} &middot; {len(spec.universe)} names &middot; "
        f"{spec.start:%b %Y} to {spec.end:%b %Y} &middot; "
        f"data as known at {results[0].knowledge_ts:%Y-%m-%d}</p>"
        "</div>"
        "<div class='theme' role='group' aria-label='Colour theme'>"
        "<button type='button' data-theme='system' aria-pressed='true'>Auto</button>"
        "<button type='button' data-theme='light' aria-pressed='false'>Day</button>"
        "<button type='button' data-theme='dark' aria-pressed='false'>Night</button>"
        "</div></div>"
    )


def _kpis(measured: Measured) -> str:
    """Headline numbers per run. Not ranked — which one is best is the reader's
    call, and this report deliberately does not make it."""
    headline = ("net_sharpe", "annualised_return", "max_drawdown", "cost_drag")
    by_key = {m.key: m for m in METRICS}

    cards = []
    for _, label, values in measured:
        tiles = []
        for key in headline:
            metric = by_key[key]
            value = values[key]
            tiles.append(
                f"<div class='kpi'><div class='label'>{metric.label}</div>"
                f"<div class='value {_tone(metric.higher_is_better, value)}'>"
                f"{_format(value, metric.unit)}</div>"
                f"<div class='note'>{metric.note}</div></div>"
            )
        heading = f"<h3>{label}</h3>" if len(measured) > 1 else ""
        cards.append(f"{heading}<div class='kpis'>{''.join(tiles)}</div>")

    return f"<section class='card'><h2>Headline</h2>{''.join(cards)}</section>"


def _equity(measured: Measured) -> str:
    series = [
        Series(label, r.returns["held_to"].to_list(), r.returns["equity"].to_list(), i + 1)
        for i, (r, label, _) in enumerate(measured)
    ]
    note = (
        "<p>Growth of one unit of gross notional, after costs. A flat line at 1.0 "
        "is a strategy that earned nothing.</p>"
    )
    return (
        f"<section class='card'><h2>Equity, net of costs</h2>{note}"
        f"{line_chart(series, baseline=1.0)}{legend(series)}</section>"
    )


def _drawdown(measured: Measured) -> str:
    series = []
    for i, (result, label, _) in enumerate(measured):
        equity = result.returns["equity"]
        drawdown = (equity / equity.cum_max() - 1.0).to_list()
        series.append(Series(label, result.returns["held_to"].to_list(), drawdown, i + 1))

    note = (
        "<p>Distance below the previous peak. This is the number that decides "
        "whether a strategy is holdable, not whether it is profitable.</p>"
    )
    return (
        f"<section class='card'><h2>Drawdown</h2>{note}"
        f"{line_chart(series, y_format='{:.0%}', baseline=0.0, fill=len(series) == 1)}"
        f"{legend(series)}</section>"
    )


def _table(measured: Measured, dropped: int) -> str:
    """Every metric for every run, one row per run.

    Runs as rows rather than columns because the question is "which of these is
    better", and that is a sort. Click a header to order by it.

    The table view is not optional. Three of the light-mode series colours sit
    below 3:1 against the surface, and the rule for that is relief — every
    value reachable without relying on colour.
    """
    heads = "".join(
        f'<th data-sort="{i + 1}" title="{metric.note or metric.label}">{metric.label}</th>'
        for i, metric in enumerate(METRICS)
    )
    rows = []
    for _, label, values in measured:
        cells = "".join(
            f'<td data-value="{values[metric.key]}" '
            f"class='{_tone(metric.higher_is_better, values[metric.key])}'>"
            f"{_format(values[metric.key], metric.unit)}</td>"
            for metric in METRICS
        )
        rows.append(f'<tr><td data-value="{label}">{label}</td>{cells}</tr>')

    omitted = (
        f"<p>{dropped} further run(s) omitted: past eight series the colours stop "
        "being tellable apart. Report on them separately.</p>"
        if dropped
        else ""
    )
    return (
        "<section class='card'><h2>All metrics</h2>"
        "<p>Click a column to sort. Every value in the charts is here too.</p>"
        f"<div class='scroll'><table class='sortable'><thead><tr>"
        f'<th data-sort="0">Run</th>{heads}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>{omitted}</section>"
    )


def _spec_details(results: Sequence[BacktestResult], notional: float) -> str:
    """What was run, so a reader can reproduce it or argue with it."""
    spec = results[0].spec
    rows = {
        "Universe": f"{len(spec.universe)} names",
        "Period": f"{spec.start:%Y-%m-%d} to {spec.end:%Y-%m-%d}",
        "Rebalance": {"M": "monthly", "W": "weekly", "D": "daily"}.get(
            spec.rebalance_frequency, spec.rebalance_frequency
        ),
        "Execution": f"close + {spec.execution_lag_sessions} session(s)",
        "Costs": f"{spec.cost_bps:.0f} bps of turnover",
        "Point in time": "yes" if spec.point_in_time else "no — pinned to one cutoff",
        "Data as known at": f"{results[0].knowledge_ts:%Y-%m-%d %H:%M}",
        "Display notional": f"${notional:,.0f} (presentation only)",
        "Reproducible": "yes" if all(r.reproducible for r in results) else "no",
    }
    items = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows.items())
    return f"<section class='card'><h2>What was run</h2><dl>{items}</dl></section>"


# --- formatting ------------------------------------------------------------


def _format(value: float, unit: str) -> str:
    return f"{value:.1%}" if unit == "percent" else f"{value:.2f}"


def _tone(higher_is_better: bool | None, value: float) -> str:
    """Colour only where a direction genuinely exists. Turnover and leg split
    are neither good nor bad, and tinting them would assert otherwise."""
    if higher_is_better is None or value == 0:
        return ""
    good = value > 0 if higher_is_better else value < 0
    return "pos" if good else "neg"


__all__ = ["render"]
