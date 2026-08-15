"""Inline SVG charts.

Drawn by hand rather than with a plotting library so the report stays a single
file with no external assets — it opens from an email attachment, from S3, or
from a laptop with no network.

Marks are thin, gridlines are solid hairlines one shade off the surface, and
colour is applied through CSS custom properties so light and dark are two
selected palettes rather than one flipped.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

WIDTH = 860
HEIGHT = 300
PAD_LEFT = 56
PAD_RIGHT = 132  # room for the direct label at the end of each line
LABEL_CHARS = 22  # beyond this a label runs off the canvas; the legend carries the rest
PAD_TOP = 16
PAD_BOTTOM = 34


@dataclass(frozen=True)
class Series:
    label: str
    x: Sequence[datetime]
    y: Sequence[float]
    slot: int  # categorical slot, 1-based, assigned per entity and never recycled


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    """Round tick values, so the axis reads 1.0, 1.2, 1.4 rather than 1.037."""
    if high <= low:
        return [low]
    raw = (high - low) / count
    scale = len(f"{int(abs(raw))}") - 1 if abs(raw) >= 1 else -_leading_zeros(raw)
    magnitude = 10**scale
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    first = (low // step) * step
    ticks = []
    while first <= high + step / 2:
        if first >= low - step / 2:
            ticks.append(round(first, 10))
        first += step
    return ticks


def _leading_zeros(value: float) -> int:
    zeros = 0
    while value < 1 and zeros < 12:
        value *= 10
        zeros += 1
    return zeros


def line_chart(
    series: Sequence[Series],
    *,
    y_format: str = "{:.2f}",
    baseline: float | None = None,
    fill: bool = False,
) -> str:
    """A time series plot. One line per entity, direct-labelled at its end.

    `baseline` draws a reference rule — 1.0 for an equity curve, 0 for a
    drawdown — so a reader can see the sign of the thing without reading the
    axis.
    """
    if not series or not any(s.y for s in series):
        return '<p class="empty">Nothing to plot.</p>'

    xs = [x.timestamp() for s in series for x in s.x]
    ys = [y for s in series for y in s.y]
    if baseline is not None:
        ys.append(baseline)

    x_lo, x_hi = min(xs), max(xs)
    ticks = _nice_ticks(min(ys), max(ys))
    y_lo, y_hi = min(min(ys), ticks[0]), max(max(ys), ticks[-1])

    def px(value: float) -> float:
        span = x_hi - x_lo or 1
        return PAD_LEFT + (value - x_lo) / span * (WIDTH - PAD_LEFT - PAD_RIGHT)

    def py(value: float) -> float:
        span = y_hi - y_lo or 1
        return HEIGHT - PAD_BOTTOM - (value - y_lo) / span * (HEIGHT - PAD_TOP - PAD_BOTTOM)

    parts = [f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" class="chart">']

    for tick in ticks:
        y = py(tick)
        parts.append(
            f'<line class="grid" x1="{PAD_LEFT}" y1="{y:.1f}" '
            f'x2="{WIDTH - PAD_RIGHT}" y2="{y:.1f}"/>'
        )
        parts.append(
            f'<text class="tick" x="{PAD_LEFT - 8}" y="{y + 4:.1f}" text-anchor="end">'
            f"{y_format.format(tick)}</text>"
        )

    if baseline is not None:
        y = py(baseline)
        parts.append(
            f'<line class="baseline" x1="{PAD_LEFT}" y1="{y:.1f}" '
            f'x2="{WIDTH - PAD_RIGHT}" y2="{y:.1f}"/>'
        )

    for when in _date_ticks([x for s in series for x in s.x]):
        x = px(when.timestamp())
        parts.append(
            f'<text class="tick" x="{x:.1f}" y="{HEIGHT - 12}" '
            f'text-anchor="middle">{when:%b %Y}</text>'
        )

    for s in series:
        points = " ".join(
            f"{px(x.timestamp()):.1f},{py(y):.1f}" for x, y in zip(s.x, s.y, strict=True)
        )
        if fill:
            floor = py(baseline if baseline is not None else y_lo)
            first, last = px(s.x[0].timestamp()), px(s.x[-1].timestamp())
            area = f"{first:.1f},{floor:.1f} {points} {last:.1f},{floor:.1f}"
            parts.append(f'<polygon class="area s{s.slot}" points="{area}"/>')
        parts.append(f'<polyline class="line s{s.slot}" points="{points}"/>')

        # Direct label at the end of the line: identity is never colour alone,
        # and the light palette needs the relief anyway.
        end_x, end_y = px(s.x[-1].timestamp()), py(s.y[-1])
        parts.append(
            f'<text class="endlabel s{s.slot}" x="{end_x + 8:.1f}" y="{end_y + 4:.1f}">'
            f"{_escape(_clip(s.label))}</text>"
        )

    floor_y = HEIGHT - PAD_BOTTOM
    parts.append(
        f'<line class="axis" x1="{PAD_LEFT}" y1="{floor_y}" '
        f'x2="{WIDTH - PAD_RIGHT}" y2="{floor_y}"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _clip(label: str) -> str:
    """Truncate rather than let a label run off the canvas. The legend and the
    table both carry the full text."""
    return label if len(label) <= LABEL_CHARS else label[: LABEL_CHARS - 1] + "\u2026"


def _date_ticks(dates: Sequence[datetime], count: int = 6) -> list[datetime]:
    ordered = sorted(set(dates))
    if len(ordered) <= count:
        return ordered
    step = (len(ordered) - 1) / (count - 1)
    return [ordered[round(i * step)] for i in range(count)]


def legend(series: Sequence[Series]) -> str:
    """Always present for two or more series, so identity never rests on colour
    alone. A single series is named by the heading instead."""
    if len(series) < 2:
        return ""
    items = "".join(
        f'<li><span class="swatch s{s.slot}"></span>{_escape(s.label)}</li>' for s in series
    )
    return f'<ul class="legend">{items}</ul>'
