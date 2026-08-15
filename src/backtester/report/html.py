"""One self-contained HTML file.

No external assets, so it opens from an attachment, from object storage, or
from a laptop with no network — which is where a report actually gets read.

The order is what a reader needs, not what is easiest to generate: what was run
and what it excludes first, then the numbers as a table you can sort and
filter, then the charts. A table buried under three charts is a table nobody
finds.

With several runs there is a tab per run and one comparing them all, because
"how did these differ" and "what did this one do" are different questions and
answering both on one page answers neither.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from backtester.engine.spec import BacktestResult
from backtester.report.charts import Series, legend, line_chart
from backtester.report.metrics import METRICS, compute

MAX_SERIES = 8  # the categorical ceiling; past it identity stops being readable

# (result, label, metrics) for each run being reported on.
Measured = Sequence[tuple[BacktestResult, str, Mapping[str, float]]]

# Short enough to be read rather than skipped. The long form is in
# docs/ASSUMPTIONS.md; what belongs here is enough for a reader to know a
# Sharpe on this page is optimistic, and why.
CAVEATS = [
    (
        "Survivorship bias",
        "The universe was picked for liquidity today, so anything that delisted is missing.",
    ),
    (
        "No market impact",
        "Costs are flat basis points on turnover, so nothing here speaks to capacity.",
    ),
    ("No borrow or financing", "A real short leg costs money to hold."),
    ("Idealised execution", "Filled in full at the next close, no slippage."),
    (
        "Price return",
        "The shipped strategy ignores dividends, which biases it against high "
        "yielders. Adjustment is available but not applied.",
    ),
]

_STYLE = """
:root {
  color-scheme: light;
  --surface: #fcfcfb; --plane: #f9f9f7;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --hairline: rgba(11,11,11,0.10);
  --wash: rgba(11,11,11,0.04);
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
    --wash: rgba(255,255,255,0.05);
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
  --wash: rgba(255,255,255,0.05);
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
  --series-4: #c98500; --series-5: #d55181; --series-6: #008300;
  --series-7: #9085e9; --series-8: #e66767;
}

* { box-sizing: border-box; }
body {
  margin: 0; padding: 28px 20px 72px;
  background: var(--plane); color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 1060px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 3px; letter-spacing: -0.01em; }
h2 { font-size: 13px; margin: 0 0 14px; letter-spacing: 0.04em;
     text-transform: uppercase; color: var(--muted); font-weight: 600; }
h3 { font-size: 13px; margin: 0 0 10px; color: var(--muted); font-weight: 600;
     letter-spacing: 0.04em; text-transform: uppercase; }
p { margin: 0 0 12px; color: var(--ink-2); }
.sub { color: var(--muted); font-size: 13px; margin: 0; }

.card { background: var(--surface); border: 1px solid var(--hairline);
        border-radius: 10px; padding: 20px 22px; margin-bottom: 16px; }

/* Header. The theme control is a utility, not the subject of the page. */
.topbar { display: flex; align-items: baseline; justify-content: space-between;
          gap: 16px; margin-bottom: 22px; }
.theme { border: 0; background: none; color: var(--muted); font: inherit;
         font-size: 11px; padding: 0; cursor: pointer; flex: none;
         letter-spacing: 0.03em; opacity: 0.7; }
.theme:hover { color: var(--ink-2); opacity: 1; }

/* Context: what was run, and what it leaves out. Both above the fold. */
.context { display: grid; grid-template-columns: minmax(240px, 340px) 1fr; gap: 32px; }
@media (max-width: 720px) { .context { grid-template-columns: 1fr; gap: 22px; } }
dl { margin: 0; display: grid; grid-template-columns: max-content 1fr;
     gap: 5px 18px; font-size: 13px; }
dt { color: var(--muted); } dd { margin: 0; font-variant-numeric: tabular-nums; }
.caveats { margin: 0; padding: 0; list-style: none; font-size: 13px; columns: 2;
           column-gap: 28px; }
@media (max-width: 900px) { .caveats { columns: 1; } }
.caveats li { margin: 0 0 9px; color: var(--ink-2); break-inside: avoid; }
.caveats b { color: var(--ink); font-weight: 600; }

/* Tabs */
.tabs { display: flex; gap: 4px; flex-wrap: wrap; margin: 0 0 16px;
        border-bottom: 1px solid var(--hairline); }
.tabs button { border: 0; background: none; font: inherit; font-size: 13px;
               color: var(--muted); padding: 9px 13px; cursor: pointer;
               border-bottom: 2px solid transparent; margin-bottom: -1px; }
.tabs button:hover { color: var(--ink-2); }
.tabs button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--series-1); }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 1px; background: var(--hairline); border-radius: 8px; overflow: hidden; }
.kpi { background: var(--surface); padding: 13px 15px; }
.kpi .label { font-size: 11.5px; color: var(--muted); }
.kpi .value { font-size: 25px; margin-top: 1px; letter-spacing: -0.02em; }
.kpi .note { font-size: 11px; color: var(--muted); margin-top: 1px; }
.pos { color: var(--good); } .neg { color: var(--critical); }

/* Table */
.tools { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.tools input { flex: 1; max-width: 280px; font: inherit; font-size: 13px;
               padding: 7px 11px; border-radius: 7px; color: var(--ink);
               border: 1px solid var(--hairline); background: var(--plane); }
.tools input::placeholder { color: var(--muted); }
.tools .count { font-size: 12px; color: var(--muted); }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 9px 11px; text-align: right; border-bottom: 1px solid var(--hairline);
         font-variant-numeric: tabular-nums; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; font-variant-numeric: normal; }
thead th { color: var(--muted); font-weight: 600; font-size: 11px; letter-spacing: 0.04em;
           text-transform: uppercase; position: sticky; top: 0; background: var(--surface); }
tbody tr:hover td { background: var(--wash); }
tbody tr:last-child td { border-bottom: none; }
table.sortable th[data-sort] { cursor: pointer; user-select: none; padding-right: 20px;
                               position: relative; }
table.sortable th[data-sort]::after { content: "\\2195"; position: absolute; right: 7px;
                                      opacity: 0.35; font-weight: 400; }
table.sortable th[data-sort]:hover { color: var(--ink); }
table.sortable th[data-sort]:hover::after { opacity: 0.7; }
table.sortable th[aria-sort="ascending"] { color: var(--ink); }
table.sortable th[aria-sort="descending"] { color: var(--ink); }
table.sortable th[aria-sort="ascending"]::after { content: "\\2191"; opacity: 1; }
table.sortable th[aria-sort="descending"]::after { content: "\\2193"; opacity: 1; }
.swatch-cell { display: inline-block; width: 9px; height: 9px; border-radius: 2px;
               margin-right: 8px; vertical-align: middle; }

/* Charts */
.chart { width: 100%; height: auto; display: block; }
.chart .grid { stroke: var(--grid); stroke-width: 1; }
.chart .axis, .chart .baseline { stroke: var(--axis); stroke-width: 1; }
.chart .tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.chart .line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.chart .area { stroke: none; opacity: 0.15; }
.chart .endlabel { font-size: 11px; font-weight: 600; }

.s1 { stroke: var(--series-1); }
.s1.area, .s1.endlabel, .s1.swatch { fill: var(--series-1); }
.s1.swatch, .s1.swatch-cell { background: var(--series-1); }
.s2 { stroke: var(--series-2); }
.s2.area, .s2.endlabel, .s2.swatch { fill: var(--series-2); }
.s2.swatch, .s2.swatch-cell { background: var(--series-2); }
.s3 { stroke: var(--series-3); }
.s3.area, .s3.endlabel, .s3.swatch { fill: var(--series-3); }
.s3.swatch, .s3.swatch-cell { background: var(--series-3); }
.s4 { stroke: var(--series-4); }
.s4.area, .s4.endlabel, .s4.swatch { fill: var(--series-4); }
.s4.swatch, .s4.swatch-cell { background: var(--series-4); }
.s5 { stroke: var(--series-5); }
.s5.area, .s5.endlabel, .s5.swatch { fill: var(--series-5); }
.s5.swatch, .s5.swatch-cell { background: var(--series-5); }
.s6 { stroke: var(--series-6); }
.s6.area, .s6.endlabel, .s6.swatch { fill: var(--series-6); }
.s6.swatch, .s6.swatch-cell { background: var(--series-6); }
.s7 { stroke: var(--series-7); }
.s7.area, .s7.endlabel, .s7.swatch { fill: var(--series-7); }
.s7.swatch, .s7.swatch-cell { background: var(--series-7); }
.s8 { stroke: var(--series-8); }
.s8.area, .s8.endlabel, .s8.swatch { fill: var(--series-8); }
.s8.swatch, .s8.swatch-cell { background: var(--series-8); }
.swatch-cell { stroke: none; }

.legend { list-style: none; display: flex; flex-wrap: wrap; gap: 6px 18px;
          margin: 12px 0 0; padding: 0; font-size: 12.5px; }
.legend .toggle { border: 0; background: none; font: inherit; color: var(--ink-2);
                  cursor: pointer; padding: 2px 0; display: flex; align-items: center;
                  gap: 7px; }
.legend .toggle[aria-pressed="false"] { opacity: 0.38; text-decoration: line-through; }
.swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.hidden-series { display: none; }

.plot { position: relative; margin: 0; }
.hover-target { fill: transparent; }
.crosshair { stroke: var(--axis); stroke-width: 1; visibility: hidden; }
.tooltip { position: absolute; pointer-events: none; z-index: 2; background: var(--surface);
           border: 1px solid var(--hairline); border-radius: 7px; padding: 8px 10px;
           font-size: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.12); min-width: 150px; }
.tooltip .when { color: var(--muted); margin-bottom: 5px; }
.tooltip .row { display: flex; align-items: center; gap: 10px; justify-content: space-between; }
.tooltip .row span:last-child { font-variant-numeric: tabular-nums; color: var(--ink); }
.tooltip .name { display: flex; align-items: center; gap: 6px; color: var(--ink-2); }

.empty { color: var(--muted); font-style: italic; }
footer { color: var(--muted); font-size: 12px; text-align: center; margin-top: 28px; }
"""

# Inline, because the report has to work from an attachment with no network.
# Everything here is presentational: switching tab, hiding a series, sorting or
# filtering changes what is easy to read, never what the numbers are.
_SCRIPT = """
(function () {
  const root = document.documentElement;
  const KEY = "backtester-theme";

  const THEMES = ["system", "light", "dark"];
  const FACE = { system: "\u25d1 auto", light: "\u25cb day", dark: "\u25cf night" };
  let current = "system";

  function applyTheme(choice) {
    current = choice;
    if (choice === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", choice);
    document.querySelectorAll(".theme").forEach(function (b) { b.innerHTML = FACE[choice]; });
    try { localStorage.setItem(KEY, choice); } catch (e) { /* private mode */ }
  }

  let saved = "system";
  try { saved = localStorage.getItem(KEY) || "system"; } catch (e) { /* ignore */ }
  applyTheme(THEMES.indexOf(saved) === -1 ? "system" : saved);

  document.querySelectorAll(".theme").forEach(function (b) {
    b.addEventListener("click", function () {
      applyTheme(THEMES[(THEMES.indexOf(current) + 1) % THEMES.length]);
    });
  });

  // --- tabs ---------------------------------------------------------------
  document.querySelectorAll(".tabs button").forEach(function (tab) {
    tab.addEventListener("click", function () {
      document.querySelectorAll(".tabs button").forEach(function (t) {
        t.setAttribute("aria-selected", String(t === tab));
      });
      document.querySelectorAll(".panel").forEach(function (p) {
        p.hidden = p.id !== tab.dataset.panel;
      });
    });
  });

  // --- sort ---------------------------------------------------------------
  document.querySelectorAll("table.sortable").forEach(function (table) {
    const body = table.tBodies[0];
    table.querySelectorAll("th[data-sort]").forEach(function (th) {
      th.addEventListener("click", function () {
        const column = Number(th.dataset.sort);
        const descending = th.getAttribute("aria-sort") !== "descending";
        Array.from(body.rows).sort(function (a, b) {
          const x = a.cells[column].dataset.value, y = b.cells[column].dataset.value;
          const nx = parseFloat(x), ny = parseFloat(y);
          const cmp = (isNaN(nx) || isNaN(ny)) ? String(x).localeCompare(String(y)) : nx - ny;
          return descending ? -cmp : cmp;
        }).forEach(function (r) { body.appendChild(r); });
        table.querySelectorAll("th").forEach(function (o) { o.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", descending ? "descending" : "ascending");
      });
    });
  });

  // --- filter -------------------------------------------------------------
  document.querySelectorAll("[data-filters]").forEach(function (input) {
    const table = document.getElementById(input.dataset.filters);
    const count = input.parentElement.querySelector(".count");
    const total = table.tBodies[0].rows.length;
    input.addEventListener("input", function () {
      const needle = input.value.trim().toLowerCase();
      let shown = 0;
      Array.from(table.tBodies[0].rows).forEach(function (row) {
        const hit = !needle || row.cells[0].textContent.toLowerCase().indexOf(needle) !== -1;
        row.hidden = !hit;
        if (hit) shown += 1;
      });
      if (count) count.textContent = shown === total ? total + " runs" : shown + " of " + total;
    });
  });

  // --- chart hover --------------------------------------------------------
  document.querySelectorAll(".plot[data-chart]").forEach(function (figure) {
    const chart = JSON.parse(figure.dataset.chart);
    const svg = figure.querySelector("svg");
    const crosshair = figure.querySelector(".crosshair");
    const tip = figure.querySelector(".tooltip");
    const percent = chart.format.indexOf("%") !== -1;

    function visible(slot) { return !svg.querySelector(".line.s" + slot + ".hidden-series"); }

    svg.addEventListener("mousemove", function (event) {
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
        html += '<div class="row"><span class="name"><span class="swatch s' + s.slot
              + '"></span>' + s.label + "</span><span>" + value + "</span></div>";
      });
      tip.innerHTML = html;
      tip.hidden = false;
      const left = (nearest[0] / scale) + 14;
      const flip = left + tip.offsetWidth > box.width;
      tip.style.left = (flip ? left - tip.offsetWidth - 28 : left) + "px";
      tip.style.top = "10px";
    });

    svg.addEventListener("mouseleave", function () {
      crosshair.style.visibility = "hidden";
      tip.hidden = true;
    });
  });

  // --- legend toggles -----------------------------------------------------
  document.querySelectorAll(".legend .toggle").forEach(function (button) {
    button.addEventListener("click", function () {
      const on = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", String(on));
      button.closest("section").querySelectorAll(".s" + button.dataset.slot)
        .forEach(function (mark) {
          if (mark.closest(".legend")) return;
          mark.classList.toggle("hidden-series", !on);
        });
    });
  });
})();
"""


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
    # expanded the arguments in — `out/*` gives content-hash order.
    ordered = sorted(zip(results, _labels(list(results)), strict=True), key=lambda pair: pair[1])
    shown = ordered[:MAX_SERIES]
    dropped = len(ordered) - len(shown)
    measured = [(result, label, compute(result)) for result, label in shown]

    body = [
        _header([result for result, _ in shown]),
        _context([result for result, _ in shown], display_notional),
        _tabs(measured),
        _all_runs_panel(measured, dropped),
        *(_run_panel(entry, i) for i, entry in enumerate(measured)),
        "<footer>Generated by backtester. Every number is reproducible from the "
        "parameters above.</footer>",
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


# --- naming ----------------------------------------------------------------


def _labels(results: Sequence[BacktestResult]) -> list[str]:
    """Name each run by what distinguishes it from the others.

    Printing every parameter produces labels wider than the chart and buries
    the one thing that actually changed. Where three runs differ only in
    lookback, the labels are "lookback 20", "lookback 60", "lookback 120".
    """
    params = [dict(getattr(r.spec.strategy, "params", {})) for r in results]
    keys = {key for p in params for key in p}
    varying = sorted(key for key in keys if len({p.get(key) for p in params}) > 1)

    labels = []
    for result, values in zip(results, params, strict=True):
        strategy = result.spec.strategy
        name = str(getattr(strategy, "name", type(strategy).__name__))
        labels.append(
            " ".join(f"{_short(k)} {values.get(k)}" for k in varying) if varying else name
        )
    return labels


def _short(parameter: str) -> str:
    """Drop the unit suffix — the docs carry it."""
    return parameter.removesuffix("_sessions").removesuffix("_fraction").replace("_", " ")


# --- sections --------------------------------------------------------------


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
        "<button type='button' class='theme' title='Switch between auto, day and "
        "night'>&#9681; auto</button>"
        "</div>"
    )


def _context(results: Sequence[BacktestResult], notional: float) -> str:
    """Parameters and limitations, side by side, above everything.

    A reader decides how much to believe the numbers before reading them, so
    both belong before the first chart rather than in an appendix.
    """
    spec = results[0].spec
    rows = {
        "Universe": f"{len(spec.universe)} names",
        "Period": f"{spec.start:%Y-%m-%d} to {spec.end:%Y-%m-%d}",
        "Rebalance": {"M": "monthly", "W": "weekly", "D": "daily"}.get(
            spec.rebalance_frequency, spec.rebalance_frequency
        ),
        "Execution": _execution(spec.execution_lag_sessions),
        "Costs": f"{spec.cost_bps:.0f} bps of turnover",
        "Data visibility": (
            "each decision sees only what was known then"
            if spec.point_in_time
            else "every read pinned to one cutoff"
        ),
        "Data as known at": f"{results[0].knowledge_ts:%Y-%m-%d %H:%M}",
        "Display notional": f"${notional:,.0f} (presentation only)",
    }
    if not all(r.reproducible for r in results):
        # Only worth a line when it is bad news: a strategy written ad hoc
        # cannot be looked up by name, so nothing can rebuild this run from
        # what was recorded.
        rows["Cannot be re-run"] = "strategy was not registered by name"
    details = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows.items())
    caveats = "".join(f"<li><b>{title}.</b> {text}</li>" for title, text in CAVEATS)

    return (
        "<section class='card context'>"
        f"<div><h3>Parameters</h3><dl>{details}</dl></div>"
        f"<div><h3>What these numbers exclude</h3><ul class='caveats'>{caveats}</ul></div>"
        "</section>"
    )


def _execution(lag: int) -> str:
    if lag == 0:
        return "at the signal close"
    return "next close" if lag == 1 else f"{lag} sessions after the signal"


def _tabs(measured: Measured) -> str:
    """One tab per run plus a comparison, when there is more than one run."""
    if len(measured) < 2:
        return ""
    buttons = [
        "<button type='button' role='tab' aria-selected='true' data-panel='all'>All runs</button>"
    ]
    buttons += [
        f"<button type='button' role='tab' aria-selected='false' data-panel='run{i}'>"
        f"{label}</button>"
        for i, (_, label, _) in enumerate(measured)
    ]
    return f"<nav class='tabs' role='tablist'>{''.join(buttons)}</nav>"


def _all_runs_panel(measured: Measured, dropped: int) -> str:
    """Table first, then charts. A table under three charts is a table nobody
    scrolls to."""
    sections = [_table(measured, dropped)]
    if len(measured) == 1:
        sections.insert(0, _kpis(measured))
    sections += [_equity(measured), _drawdown(measured)]
    return f"<div class='panel' id='all'>{''.join(sections)}</div>"


def _run_panel(entry: tuple[BacktestResult, str, Mapping[str, float]], index: int) -> str:
    """One run on its own: its headline numbers, then its curves.

    Colour follows the run, so a name that is orange in the comparison is
    orange here too.
    """
    result, label, values = entry
    single: Measured = [(result, label, values)]
    slot = index + 1

    equity = Series(
        label, result.returns["held_to"].to_list(), result.returns["equity"].to_list(), slot
    )
    curve = result.returns["equity"]
    drawdown = Series(
        label, result.returns["held_to"].to_list(), (curve / curve.cum_max() - 1.0).to_list(), slot
    )

    return (
        f"<div class='panel' id='run{index}' hidden>"
        f"{_kpis(single)}"
        "<section class='card'><h2>Equity, net of costs</h2>"
        f"{line_chart([equity], baseline=1.0)}</section>"
        "<section class='card'><h2>Drawdown</h2>"
        f"{line_chart([drawdown], y_format='{:.0%}', baseline=0.0, fill=True)}</section>"
        "</div>"
    )


def _kpis(measured: Measured) -> str:
    """Headline numbers. Not ranked — which one is best is the reader's call,
    and this report deliberately does not make it."""
    headline = ("net_sharpe", "annualised_return", "max_drawdown", "cost_drag")
    by_key = {m.key: m for m in METRICS}

    cards = []
    for _, label, values in measured:
        tiles = "".join(
            f"<div class='kpi'><div class='label'>{by_key[key].label}</div>"
            f"<div class='value {_tone(by_key[key].higher_is_better, values[key])}'>"
            f"{_format(values[key], by_key[key].unit)}</div>"
            f"<div class='note'>{by_key[key].note}</div></div>"
            for key in headline
        )
        heading = f"<h3>{label}</h3>" if len(measured) > 1 else ""
        cards.append(f"{heading}<div class='kpis'>{tiles}</div>")

    return f"<section class='card'><h2>Headline</h2>{''.join(cards)}</section>"


def _table(measured: Measured, dropped: int) -> str:
    """Every metric for every run, one row per run.

    Runs as rows rather than columns because the question is which of these is
    better, and that is a sort. It also stays readable as runs are added.

    The table is not optional. Three of the light-mode series colours sit below
    3:1 against the surface, and the rule for that is relief — every value
    reachable without relying on colour.
    """
    heads = "".join(
        f'<th data-sort="{i + 1}" title="{metric.note or metric.label}">{metric.label}</th>'
        for i, metric in enumerate(METRICS)
    )
    rows = []
    for i, (_, label, values) in enumerate(measured):
        cells = "".join(
            f'<td data-value="{values[m.key]}" class="{_tone(m.higher_is_better, values[m.key])}">'
            f"{_format(values[m.key], m.unit)}</td>"
            for m in METRICS
        )
        swatch = f"<span class='swatch-cell s{i + 1}'></span>"
        rows.append(f'<tr><td data-value="{label}">{swatch}{label}</td>{cells}</tr>')

    omitted = (
        f"<p>{dropped} further run(s) omitted: past eight the colours stop being "
        "tellable apart. Report on them separately.</p>"
        if dropped
        else ""
    )
    tools = (
        "<div class='tools'>"
        "<input type='search' data-filters='metrics' placeholder='Filter runs…' "
        "aria-label='Filter runs'>"
        f"<span class='count'>{len(measured)} runs</span></div>"
        if len(measured) > 1
        else ""
    )
    return (
        "<section class='card'><h2>All metrics</h2>"
        f"{tools}"
        "<div class='scroll'><table class='sortable' id='metrics'><thead><tr>"
        f'<th data-sort="0">Run</th>{heads}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>{omitted}</section>"
    )


def _equity(measured: Measured) -> str:
    series = [
        Series(label, r.returns["held_to"].to_list(), r.returns["equity"].to_list(), i + 1)
        for i, (r, label, _) in enumerate(measured)
    ]
    return (
        "<section class='card'><h2>Equity, net of costs</h2>"
        "<p>Growth of one unit of gross notional, after costs. Hover for values; "
        "click a name to hide it.</p>"
        f"{line_chart(series, baseline=1.0)}{legend(series)}</section>"
    )


def _drawdown(measured: Measured) -> str:
    series = []
    for i, (result, label, _) in enumerate(measured):
        equity = result.returns["equity"]
        series.append(
            Series(
                label,
                result.returns["held_to"].to_list(),
                (equity / equity.cum_max() - 1.0).to_list(),
                i + 1,
            )
        )
    return (
        "<section class='card'><h2>Drawdown</h2>"
        "<p>Distance below the previous peak. This is what decides whether a strategy "
        "is holdable, not whether it is profitable.</p>"
        f"{line_chart(series, y_format='{:.0%}', baseline=0.0, fill=len(series) == 1)}"
        f"{legend(series)}</section>"
    )


# --- formatting ------------------------------------------------------------


def _format(value: float, unit: str) -> str:
    return f"{value:.1%}" if unit == "percent" else f"{value:.2f}"


def _tone(higher_is_better: bool | None, value: float) -> str:
    """Colour only where a direction genuinely exists. Turnover and the leg
    split are neither good nor bad, and tinting them would assert otherwise."""
    if higher_is_better is None or value == 0:
        return ""
    good = value > 0 if higher_is_better else value < 0
    return "pos" if good else "neg"


__all__ = ["render"]
