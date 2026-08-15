"""The report.

Rendering cannot be checked the way a number can, so these test the properties
that would make the file wrong rather than ugly: it must open with no network,
every value must be reachable without relying on colour, and the caveats that
make the numbers optimistic must be in the document rather than only in the
repository.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from qrt.report.html import MAX_SERIES, render
from qrt.report.metrics import METRICS
from tests.report.test_metrics import result_with


def report(tmp_path: Path, runs: int = 1, **kwargs: object) -> str:
    from dataclasses import replace

    from qrt.strategy.base import StrategyRef

    results = []
    for i in range(runs):
        base = result_with([0.02, -0.01] * 6)
        spec = replace(
            base.spec,
            strategy=StrategyRef("trailing_return", {"lookback_sessions": 20 * (i + 1)}),
        )
        results.append(replace(base, spec=spec))

    path = render(results, tmp_path / "report.html", **kwargs)  # type: ignore[arg-type]
    return path.read_text()


def test_it_is_self_contained(tmp_path: Path) -> None:
    """No stylesheet, no script, no font, no image. A report gets read from an
    attachment or from object storage, where a fetch would simply fail."""
    html = report(tmp_path)
    external = re.findall(r'(?:src|href)="(?!#)[^"]+"', html)
    assert external == []


def test_every_metric_reaches_the_page(tmp_path: Path) -> None:
    """The table is the relief for three light-mode series colours sitting
    below 3:1 against the surface — so every value has to be in it."""
    html = report(tmp_path)
    for metric in METRICS:
        assert metric.label in html, metric.key


def test_the_reader_is_pointed_at_what_the_numbers_exclude(tmp_path: Path) -> None:
    """A Sharpe carries assumptions that change whether anyone should believe
    it. The full write-up lives in the repository; the report has to say so."""
    assert "ASSUMPTIONS.md" in report(tmp_path)


def test_runs_are_labelled_by_what_differs(tmp_path: Path) -> None:
    """Three runs that differ only in lookback are labelled by lookback, not by
    every parameter they share — which is both clearer and the reason the
    labels fit on the canvas."""
    html = report(tmp_path, runs=3)
    assert "lookback 20" in html
    assert "lookback 60" in html
    assert "top" not in re.findall(r'class="endlabel[^>]*>([^<]+)<', html)[0]


def test_endpoint_labels_fit_the_canvas(tmp_path: Path) -> None:
    """A label running off the plot is the failure this catches. Measured
    against the viewBox rather than eyeballed."""
    html = report(tmp_path, runs=3)
    width = int(re.search(r'viewBox="0 0 (\d+)', html).group(1))  # type: ignore[union-attr]

    placed = re.findall(r'class="endlabel s\d" x="([\d.]+)" y="[\d.]+">([^<]+)<', html)
    assert placed
    for x, label in placed:
        # 11px sans averages under 6px per character.
        assert float(x) + len(label) * 6 <= width, f"{label!r} overflows"


def test_a_single_run_needs_no_legend(tmp_path: Path) -> None:
    """One series is named by the heading. A legend box for it is furniture."""
    assert '<ul class="legend">' not in report(tmp_path, runs=1)


def test_several_runs_are_always_legended(tmp_path: Path) -> None:
    """Identity is never colour alone."""
    html = report(tmp_path, runs=3)
    assert html.count('<ul class="legend">') >= 1
    assert len(re.findall(r'class="toggle" data-slot="\d"', html)) >= 3


def test_colour_slots_are_assigned_in_order_and_never_reused(tmp_path: Path) -> None:
    """A run keeps its hue across every chart in the document, so a reader who
    learned "lookback 60 is orange" is not misled by the next plot."""
    html = report(tmp_path, runs=3)
    for chart in re.findall(r"<svg viewBox.*?</svg>", html, re.S):
        slots = re.findall(r'class="line s(\d)"', chart)
        assert slots == ["1", "2", "3"]


def test_more_runs_than_colours_are_dropped_and_said_so(tmp_path: Path) -> None:
    """Past the categorical ceiling the hues stop being tellable apart.
    Silently truncating would read as "these are all of them"."""
    html = report(tmp_path, runs=MAX_SERIES + 2)
    assert "omitted" in html
    assert (
        len(re.findall(r'class="line s\d"', re.search(r"<svg.*?</svg>", html, re.S).group()))
        == MAX_SERIES
    )  # type: ignore[union-attr]


def test_dark_mode_is_selected_not_flipped(tmp_path: Path) -> None:
    """Its own steps for the dark surface, under both the OS setting and an
    explicit theme choice."""
    html = report(tmp_path)
    assert "prefers-color-scheme: dark" in html
    assert '[data-theme="dark"]' in html
    assert "#3987e5" in html  # the dark step of slot 1, not the light one reused


def test_an_empty_report_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no results"):
        render([], tmp_path / "empty.html")


def test_the_spec_is_recorded_so_a_reader_can_reproduce_it(tmp_path: Path) -> None:
    html = report(tmp_path)
    for field in ("Universe", "Period", "Rebalance", "Costs", "Data as known at"):
        assert field in html


# --- the interactive layer -------------------------------------------------


def test_the_theme_can_be_chosen_not_only_inherited(tmp_path: Path) -> None:
    """Auto follows the system, and the two explicit choices override it — a
    report gets read on someone else's screen at someone else's settings."""
    html = report(tmp_path)
    for choice in ("system", "light", "dark"):
        assert f"data-theme='{choice}'" in html
    assert "localStorage" in html


def test_the_table_can_be_sorted_on_any_metric(tmp_path: Path) -> None:
    """Runs are rows because the question is which of these is better, and
    that is a sort. Raw values ride along, since the displayed text is
    formatted and would sort as a string."""
    html = report(tmp_path, runs=3)

    assert len(re.findall(r"th data-sort=", html)) == len(METRICS) + 1
    assert len(re.findall(r"<tr><td data-value=", html)) == 3

    values = re.findall(r'<td data-value="(-?[\d.e]+)"', html)
    assert values, "sortable cells must carry the unformatted number"
    for raw in values:
        float(raw)


def test_charts_carry_their_plotted_geometry(tmp_path: Path) -> None:
    """The hover layer reads what was drawn rather than recomputing the scales,
    so the crosshair cannot drift from the line it is tracking."""
    import json

    html = report(tmp_path, runs=3)
    payloads = re.findall(r"data-chart='([^']+)'", html)
    assert len(payloads) == 2  # equity and drawdown

    chart = json.loads(payloads[0])
    assert len(chart["series"]) == 3
    for series in chart["series"]:
        x, y, value, when = series["points"][0]
        assert isinstance(value, float) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", when)


def test_interaction_adds_no_external_dependency(tmp_path: Path) -> None:
    """All of it inline. A report that needs a CDN is a report that stops
    working the moment it is emailed."""
    html = report(tmp_path, runs=3)
    assert "<script>" in html
    assert re.findall(r"<script[^>]+src=", html) == []


def test_hiding_a_series_does_not_hide_its_numbers(tmp_path: Path) -> None:
    """Legend toggles are presentational. Every value stays in the table, which
    is also the relief for the light-mode contrast warning."""
    html = report(tmp_path, runs=3)
    assert 'class="toggle"' in html
    assert html.count("<tr><td data-value=") == 3
