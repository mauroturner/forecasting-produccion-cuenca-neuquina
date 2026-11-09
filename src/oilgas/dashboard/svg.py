"""Small SVG charts for the dashboard design: previews with real numbers, no scripts and no external files.

Every function returns one ``<svg>`` string. Colors are CSS custom properties (``--series-1`` ... and the
text and grid tokens) declared by the page, so light and dark mode swap in one place. A chart has a
``role="img"`` and an ``aria-label``; hovering a point or a bar shows its value (native ``<title>``).
Lines are 2 px, bars are thin with a rounded end, the grid is recessive and a legend is drawn from two
series on; a series that is missing a value breaks its line instead of drawing a false one.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from html import escape

SERIES_COLORS = tuple(f"var(--series-{i})" for i in range(1, 9))
MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM = 52, 12, 10, 26
LEGEND_HEIGHT = 18


def format_number(value: float, digits: int = 1) -> str:
    """A number in Spanish: ``1,2 M``, ``350 mil``, ``12,5``; whole numbers have no decimals."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    magnitude = abs(value)
    for limit, divisor, suffix in ((1e9, 1e9, " mil M"), (1e6, 1e6, " M"), (1e4, 1e3, " mil")):
        if magnitude >= limit:
            text = f"{value / divisor:.{digits}f}".rstrip("0").rstrip(".")
            return text.replace(".", ",") + suffix
    if magnitude >= 100 or float(value).is_integer():
        return f"{value:,.0f}".replace(",", ".")
    return f"{value:.{digits}f}".rstrip("0").rstrip(".").replace(".", ",")


def nice_ticks(low: float, high: float, count: int = 4) -> list[float]:
    """About `count` round tick values covering ``[low, high]`` (at least two)."""
    if not math.isfinite(low) or not math.isfinite(high):
        return [0.0, 1.0]
    if high <= low:
        high = low + (abs(low) or 1.0)
    raw = (high - low) / max(count, 1)
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)
    first = math.floor(low / step) * step
    ticks = []
    value = first
    while value <= high + step * 0.999:
        ticks.append(round(value, 10))
        value += step
        if len(ticks) > 12:
            break
    return ticks


def _finite(value) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(value)


def _empty(width: int, height: int, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{escape(title)}: sin datos">'
        f'<text x="{width / 2:.0f}" y="{height / 2:.0f}" text-anchor="middle" class="svg-note">Sin datos</text></svg>'
    )


def _legend(names: Sequence[str], colors: Sequence[str], width: int, dashed: Sequence[str] = ()) -> str:
    """A row of swatches and names (always present from two series on; identity never rests on color alone)."""
    parts, x = [], MARGIN_LEFT
    for name, color in zip(names, colors, strict=True):
        dash = ' stroke-dasharray="4 3"' if name in dashed else ""
        parts.append(f'<line x1="{x}" y1="9" x2="{x + 16}" y2="9" stroke="{color}" stroke-width="2"{dash}/>')
        parts.append(f'<text x="{x + 20}" y="13" class="svg-legend">{escape(name)}</text>')
        x += 28 + 6.2 * len(name)
        if x > width - 40:
            break
    return "".join(parts)


def _axes(x0: float, x1: float, y0: float, y1: float, ticks: list[float], scale) -> str:
    out = []
    for tick in ticks:
        y = scale(tick)
        out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" class="svg-grid"/>')
        out.append(f'<text x="{x0 - 6}" y="{y + 4:.1f}" text-anchor="end" class="svg-tick">{escape(format_number(tick))}</text>')
    out.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" class="svg-axis"/>')
    return "".join(out)


def line_chart(
    series: dict[str, list[tuple[float, float]]],
    width: int,
    height: int,
    title: str,
    *,
    dashed: Sequence[str] = (),
    band: Sequence[tuple[float, float, float]] | None = None,
    band_label: str = "P10-P90",
    x_ticks: Sequence[tuple[float, str]] = (),
    unit: str = "",
    reference: tuple[str, float] | None = None,
) -> str:
    """Lines of ``(x, y)`` points. `band` is a shaded range ``(x, low, high)``; `reference` a horizontal line ``(name, y)``."""
    points = [(x, y) for pts in series.values() for x, y in pts if _finite(x) and _finite(y)]
    if not points:
        return _empty(width, height, title)
    names = list(series)
    colors = [SERIES_COLORS[i % len(SERIES_COLORS)] for i in range(len(names))]
    legend_rows = len(names) + (1 if band else 0) + (1 if reference else 0)
    top = MARGIN_TOP + (LEGEND_HEIGHT if legend_rows >= 2 else 0)
    x0, x1, y0, y1 = MARGIN_LEFT, width - MARGIN_RIGHT, top, height - MARGIN_BOTTOM
    xs = [p[0] for p in points] + ([b[0] for b in band] if band else [])
    ys = [p[1] for p in points] + ([b[2] for b in band] if band else []) + ([reference[1]] if reference else [])
    x_lo, x_hi = min(xs), max(xs)
    ticks = nice_ticks(0.0 if min(ys) >= 0 else min(ys), max(ys))
    y_lo, y_hi = ticks[0], ticks[-1]

    def sx(x: float) -> float:
        return x0 + (x - x_lo) / ((x_hi - x_lo) or 1.0) * (x1 - x0)

    def sy(y: float) -> float:
        return y1 - (y - y_lo) / ((y_hi - y_lo) or 1.0) * (y1 - y0)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{escape(title)}">']
    out.append(f"<title>{escape(title)}</title>")
    if legend_rows >= 2:
        legend_names, legend_colors = list(names), list(colors)
        if band:
            legend_names.append(band_label)
            legend_colors.append("var(--series-1)")
        out.append(_legend(legend_names, legend_colors, width, dashed))
    out.append(_axes(x0, x1, y0, y1, ticks, sy))
    for x, label in x_ticks:
        anchor = "end" if sx(x) > x1 - 28 else "middle"  # the last label must not run out of the frame
        out.append(f'<text x="{sx(x):.1f}" y="{height - 8}" text-anchor="{anchor}" class="svg-tick">{escape(label)}</text>')
    if band:
        ordered = sorted(band)
        upper = " ".join(f"{sx(x):.1f},{sy(hi):.1f}" for x, _, hi in ordered)
        lower = " ".join(f"{sx(x):.1f},{sy(lo):.1f}" for x, lo, _ in reversed(ordered))
        out.append(f'<polygon points="{upper} {lower}" class="svg-band"><title>{escape(band_label)}</title></polygon>')
    if reference:
        y = sy(reference[1])
        out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" class="svg-reference"/>')
        out.append(f'<text x="{x0 + 4}" y="{y - 4:.1f}" class="svg-tick">{escape(reference[0])}</text>')
    for name, color in zip(names, colors, strict=True):
        dash = ' stroke-dasharray="5 4"' if name in dashed else ""
        segment: list[tuple[float, float]] = []
        segments = []
        for x, y in series[name]:
            if _finite(x) and _finite(y):
                segment.append((x, y))
            elif segment:
                segments.append(segment)
                segment = []
        if segment:
            segments.append(segment)
        for seg in segments:
            if len(seg) == 1:
                out.append(f'<circle cx="{sx(seg[0][0]):.1f}" cy="{sy(seg[0][1]):.1f}" r="3" fill="{color}"/>')
            else:
                path = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in seg)
                out.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"{dash}/>')
        if len(series[name]) <= 80:  # a wide hit target with the value, for the hover
            for x, y in series[name]:
                if _finite(x) and _finite(y):
                    out.append(
                        f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="5" class="svg-hit"><title>{escape(name)}: {escape(format_number(y))} {escape(unit)}</title></circle>'
                    )
    out.append("</svg>")
    return "".join(out)


def bar_chart(values: list[tuple[str, float]], width: int, height: int, title: str, *, unit: str = "") -> str:
    """Horizontal bars, one per ``(label, value)``, with the label at the left and the value at the end of the bar."""
    values = [(label, value) for label, value in values if _finite(value)]
    if not values:
        return _empty(width, height, title)
    label_width = min(max(len(label) for label, _ in values) * 6.2 + 8, width * 0.45)
    x0, x1 = label_width, width - 56
    top, bottom = 4, height - 4
    slot = (bottom - top) / len(values)
    bar = min(14.0, slot * 0.6)
    peak = max(max(v for _, v in values), 0.0) or 1.0
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{escape(title)}">', f"<title>{escape(title)}</title>"]
    out.append(f'<line x1="{x0}" y1="{top}" x2="{x0}" y2="{bottom}" class="svg-axis"/>')
    for i, (label, value) in enumerate(values):
        y = top + i * slot + (slot - bar) / 2
        length = max(value, 0.0) / peak * (x1 - x0)
        shown = escape(label if len(label) * 6.2 <= label_width - 8 else label[: int((label_width - 8) / 6.2) - 1] + "…")
        out.append(f'<text x="{x0 - 6}" y="{y + bar / 2 + 4:.1f}" text-anchor="end" class="svg-tick">{shown}</text>')
        out.append(
            f'<path d="M{x0},{y:.1f} h{max(length - 4, 0):.1f} a4,4 0 0 1 4,4 v{max(bar - 8, 0):.1f} a4,4 0 0 1 -4,4 h-{max(length - 4, 0):.1f} z" '
            f'fill="var(--series-1)"><title>{escape(label)}: {escape(format_number(value))} {escape(unit)}</title></path>'
        )
        out.append(f'<text x="{x0 + length + 5:.1f}" y="{y + bar / 2 + 4:.1f}" class="svg-value">{escape(format_number(value))}</text>')
    out.append("</svg>")
    return "".join(out)


def grouped_bar_chart(
    groups: list[tuple[str, dict[str, float]]], width: int, height: int, title: str, *, percent: bool = False
) -> str:
    """Vertical bars: one cluster per group label, one bar per series name (legend always present)."""
    names = list(dict.fromkeys(name for _, values in groups for name in values))
    if not groups or not names or not any(_finite(v) for _, vals in groups for v in vals.values()):
        return _empty(width, height, title)
    colors = [SERIES_COLORS[i % len(SERIES_COLORS)] for i in range(len(names))]
    top = MARGIN_TOP + LEGEND_HEIGHT
    x0, x1, y0, y1 = MARGIN_LEFT, width - MARGIN_RIGHT, top, height - MARGIN_BOTTOM
    peak = max(v for _, vals in groups for v in vals.values() if _finite(v))
    ticks = nice_ticks(0.0, peak if peak > 0 else 1.0)
    y_hi = ticks[-1]

    def sy(y: float) -> float:
        return y1 - y / (y_hi or 1.0) * (y1 - y0)

    def shown(value: float) -> str:
        return f"{value * 100:.0f} %" if percent else format_number(value)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{escape(title)}">', f"<title>{escape(title)}</title>"]
    out.append(_legend(names, colors, width))
    out.append(_axes(x0, x1, y0, y1, ticks, sy))
    slot = (x1 - x0) / len(groups)
    bar = min(18.0, slot * 0.8 / len(names))
    for i, (label, values) in enumerate(groups):
        cluster = bar * len(names)
        left = x0 + i * slot + (slot - cluster) / 2
        out.append(f'<text x="{x0 + i * slot + slot / 2:.1f}" y="{height - 8}" text-anchor="middle" class="svg-tick">{escape(label)}</text>')
        for j, name in enumerate(names):
            value = values.get(name)
            if not _finite(value):
                continue
            h = max(value, 0.0) / (y_hi or 1.0) * (y1 - y0)
            out.append(
                f'<rect x="{left + j * bar + 1:.1f}" y="{y1 - h:.1f}" width="{max(bar - 2, 1):.1f}" height="{h:.1f}" rx="2" fill="{colors[j]}">'
                f"<title>{escape(name)}, {escape(label)}: {escape(shown(value))}</title></rect>"
            )
    out.append("</svg>")
    return "".join(out)


def scatter_chart(points: list[tuple[float, float, str]], width: int, height: int, title: str, *, radius: float = 2.2) -> str:
    """Points ``(x, y, group)`` on equal axes (a map without a map service); the legend names the groups."""
    points = [p for p in points if _finite(p[0]) and _finite(p[1])]
    if not points:
        return _empty(width, height, title)
    groups = list(dict.fromkeys(g for _, _, g in points))
    colors = {g: SERIES_COLORS[i % len(SERIES_COLORS)] for i, g in enumerate(groups)}
    x0, x1, y0, y1 = 8, width - 8, MARGIN_TOP + LEGEND_HEIGHT, height - 8
    x_lo, x_hi = min(p[0] for p in points), max(p[0] for p in points)
    y_lo, y_hi = min(p[1] for p in points), max(p[1] for p in points)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{escape(title)}">', f"<title>{escape(title)}</title>"]
    out.append(_legend(groups, [colors[g] for g in groups], width + MARGIN_LEFT))
    scale = min((x1 - x0) / ((x_hi - x_lo) or 1.0), (y1 - y0) / ((y_hi - y_lo) or 1.0))  # one scale for both axes: shapes are not stretched
    left = x0 + ((x1 - x0) - (x_hi - x_lo) * scale) / 2
    bottom = y1 - ((y1 - y0) - (y_hi - y_lo) * scale) / 2
    for x, y, group in points:
        cx = left + (x - x_lo) * scale
        cy = bottom - (y - y_lo) * scale
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" fill="{colors[group]}" fill-opacity="0.75"/>')
    out.append("</svg>")
    return "".join(out)


def treemap(values: list[tuple[str, float]], width: int, height: int, title: str) -> str:
    """Rectangles with areas proportional to the values (slice and dice, largest first); labels where they fit."""
    values = sorted(((label, v) for label, v in values if _finite(v) and v > 0), key=lambda item: -item[1])
    if not values:
        return _empty(width, height, title)
    total = sum(v for _, v in values)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{escape(title)}">', f"<title>{escape(title)}</title>"]
    rects = []

    def place(items: list[tuple[str, float]], x: float, y: float, w: float, h: float, horizontal: bool) -> None:
        if not items:
            return
        if len(items) == 1:
            rects.append((items[0], x, y, w, h))
            return
        head, rest = items[0], items[1:]
        share = head[1] / sum(v for _, v in items)
        if horizontal:
            place([head], x, y, w * share, h, not horizontal)
            place(rest, x + w * share, y, w * (1 - share), h, not horizontal)
        else:
            place([head], x, y, w, h * share, not horizontal)
            place(rest, x, y + h * share, w, h * (1 - share), not horizontal)

    place(values, 1.0, 1.0, width - 2.0, height - 2.0, True)
    for i, ((label, value), x, y, w, h) in enumerate(rects):
        color = f"var(--series-{i % 3 + 1})"
        out.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w - 2, 1):.1f}" height="{max(h - 2, 1):.1f}" rx="3" fill="{color}" fill-opacity="0.35" stroke="{color}" stroke-width="1.5">'
            f"<title>{escape(label)}: {escape(format_number(value))} ({value / total * 100:.0f} %)</title></rect>"
        )
        if w > 7 * len(label) + 10 and h > 22:
            out.append(f'<text x="{x + 6:.1f}" y="{y + 15:.1f}" class="svg-on-fill">{escape(label)}</text>')
    out.append("</svg>")
    return "".join(out)
