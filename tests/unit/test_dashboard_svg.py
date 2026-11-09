"""The SVG previews: geometry, gaps, legends, escaping and the empty case (U11)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from oilgas.dashboard.svg import bar_chart, format_number, grouped_bar_chart, line_chart, nice_ticks, scatter_chart, treemap

SVG = "{http://www.w3.org/2000/svg}"


def parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)  # well-formed XML: it can be embedded in the page


def lines(root: ET.Element) -> list[ET.Element]:
    return list(root.iter(f"{SVG}polyline"))


def points_of(line: ET.Element) -> list[tuple[float, float]]:
    return [tuple(map(float, pair.split(","))) for pair in line.attrib["points"].split()]


# --- numbers and ticks ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [(0, "0"), (12.5, "12,5"), (350, "350"), (1234, "1.234"), (35_000, "35 mil"), (1_230_000, "1,23 M"), (2_000_000, "2 M"),
     (3_355_749, "3,36 M"), (float("nan"), "—"), (None, "—")],
)
def test_numbers_are_written_in_spanish(value, text: str) -> None:
    assert format_number(value, 2) == text


def test_ticks_are_round_and_cover_the_range() -> None:
    ticks = nice_ticks(0, 87)
    assert ticks[0] == 0 and ticks[-1] >= 87 and len(ticks) >= 3
    steps = {round(b - a, 9) for a, b in zip(ticks, ticks[1:], strict=False)}
    assert len(steps) == 1 and steps.pop() in (20.0, 25.0, 50.0, 10.0)
    assert nice_ticks(5, 5)[0] <= 5 <= nice_ticks(5, 5)[-1]
    assert nice_ticks(float("nan"), 1) == [0.0, 1.0]


# --- line chart -------------------------------------------------------------------------------------------------


def test_a_line_chart_draws_one_polyline_per_series_inside_its_frame() -> None:
    svg = line_chart({"Producido": [(0, 10), (1, 20), (2, 15)], "P50": [(2, 15), (3, 12)]}, 600, 200, "Petróleo")
    root = parse(svg)
    assert root.attrib["role"] == "img" and root.attrib["aria-label"] == "Petróleo"
    drawn = lines(root)
    assert len(drawn) == 2 and [len(points_of(d)) for d in drawn] == [3, 2]
    for line in drawn:
        for x, y in points_of(line):
            assert 0 <= x <= 600 and 0 <= y <= 200
    first = points_of(drawn[0])
    assert first[1][1] < first[0][1] and first[1][1] < first[2][1]  # the peak (20) is the highest point: smallest y
    assert drawn[0].attrib["stroke"] == "var(--series-1)" and drawn[1].attrib["stroke"] == "var(--series-2)"


def test_the_y_axis_starts_at_zero_and_reaches_the_maximum() -> None:
    svg = line_chart({"a": [(0, 40), (1, 90)]}, 400, 200, "t")
    labels = re.findall(r'class="svg-tick">([^<]*)</text>', svg)
    assert labels[0] == "0" and "100" in labels or "90" in labels or "80" in labels


def test_a_missing_value_breaks_the_line_instead_of_bridging_the_gap() -> None:
    svg = line_chart({"a": [(0, 1), (1, 2), (2, float("nan")), (3, 3), (4, 4)]}, 400, 150, "t")
    assert [len(points_of(d)) for d in lines(parse(svg))] == [2, 2]
    single = line_chart({"a": [(0, 1), (1, None), (2, 3), (3, 4)]}, 400, 150, "t")
    assert len(lines(parse(single))) == 1 and "<circle" in single  # the lone point is still drawn


def test_dashed_series_the_band_and_the_reference_are_drawn_and_named_in_the_legend() -> None:
    svg = line_chart(
        {"Producido": [(0, 5), (1, 6)], "P50": [(1, 6), (2, 7)]}, 500, 200, "t",
        dashed=("P50",), band=[(1, 5, 8), (2, 6, 9)], reference=("Objetivo", 6.5),
    )
    root = parse(svg)
    dashed = [d for d in lines(root) if d.attrib.get("stroke-dasharray")]
    assert len(dashed) == 1 and dashed[0].attrib["stroke"] == "var(--series-2)"
    assert len(list(root.iter(f"{SVG}polygon"))) == 1
    text = " ".join(t.text or "" for t in root.iter(f"{SVG}text"))
    for word in ("Producido", "P50", "P10-P90", "Objetivo"):
        assert word in text


def test_one_series_has_no_legend_two_or_more_do() -> None:
    one = parse(line_chart({"a": [(0, 1), (1, 2)]}, 400, 150, "t"))
    two = parse(line_chart({"a": [(0, 1), (1, 2)], "b": [(0, 2), (1, 1)]}, 400, 150, "t"))
    assert not [t for t in one.iter(f"{SVG}text") if t.attrib.get("class") == "svg-legend"]
    assert {t.text for t in two.iter(f"{SVG}text") if t.attrib.get("class") == "svg-legend"} == {"a", "b"}


def test_x_labels_unit_and_hover_values_are_present_and_text_is_escaped() -> None:
    svg = line_chart({"a & <b>": [(0, 1234), (1, 2000)]}, 400, 150, "Gas <x>", x_ticks=[(0, "2024-01"), (1, "2024-02")], unit="m³")
    parse(svg)  # still well-formed
    assert "2024-01" in svg and "m³" in svg and "Gas &lt;x&gt;" in svg and "a &amp; &lt;b&gt;: 1.234" in svg


def test_no_points_gives_a_visible_empty_state() -> None:
    for svg in (line_chart({}, 300, 100, "t"), line_chart({"a": [(0, float("nan"))]}, 300, 100, "t")):
        root = parse(svg)
        assert "Sin datos" in "".join(root.itertext()) and "sin datos" in root.attrib["aria-label"]


# --- bars ---------------------------------------------------------------------------------------------------------


def test_bar_lengths_are_proportional_to_the_values() -> None:
    svg = bar_chart([("YPF", 100.0), ("VISTA", 50.0), ("PAE", 25.0)], 500, 120, "Empresas", unit="m³")
    root = parse(svg)
    paths = list(root.iter(f"{SVG}path"))
    assert len(paths) == 3
    widths = [float(re.search(r"h([\d.]+)", p.attrib["d"]).group(1)) + 4 for p in paths]  # the straight part plus the 4 px round end
    assert widths[0] == pytest.approx(2 * widths[1], abs=0.5) and widths[1] == pytest.approx(2 * widths[2], abs=0.5)  # paths are rounded to 0.1 px
    assert all(p.find(f"{SVG}title") is not None for p in paths)
    assert "YPF: 100 m³" in svg


def test_long_labels_are_cut_and_empty_or_missing_values_are_dropped() -> None:
    svg = bar_chart([("A" * 60, 3.0), ("ok", float("nan"))], 300, 80, "t")
    assert "…" in svg and len(list(parse(svg).iter(f"{SVG}path"))) == 1
    assert "Sin datos" in bar_chart([], 300, 80, "t")


def test_grouped_bars_have_one_bar_per_series_in_each_group_and_a_legend() -> None:
    groups = [("1 mes", {"naive": 0.5, "arps": 0.4}), ("12 meses", {"naive": 0.8, "arps": 0.6, "ml": 0.5})]
    root = parse(grouped_bar_chart(groups, 500, 220, "WAPE", percent=True))
    rects = list(root.iter(f"{SVG}rect"))
    assert len(rects) == 5
    heights = {r.find(f"{SVG}title").text: float(r.attrib["height"]) for r in rects}
    assert heights["naive, 12 meses: 80 %"] > heights["arps, 12 meses: 60 %"] > heights["ml, 12 meses: 50 %"]
    legend = {t.text for t in root.iter(f"{SVG}text") if t.attrib.get("class") == "svg-legend"}
    assert legend == {"naive", "arps", "ml"}
    assert "Sin datos" in grouped_bar_chart([("a", {})], 300, 100, "t")


# --- scatter and treemap ----------------------------------------------------------------------------------------------


def test_scatter_places_points_by_value_and_names_the_groups() -> None:
    svg = scatter_chart([(0, 0, "SHALE"), (10, 5, "TIGHT"), (5, 2.5, "SHALE"), (float("nan"), 1, "SHALE")], 300, 200, "Pozos")
    root = parse(svg)
    circles = [c for c in root.iter(f"{SVG}circle")]
    assert len(circles) == 3
    xs = sorted(float(c.attrib["cx"]) for c in circles)
    assert xs[1] - xs[0] == pytest.approx(xs[2] - xs[1])
    low = next(c for c in circles if float(c.attrib["cx"]) == xs[0])
    assert float(low.attrib["cy"]) > float(next(c for c in circles if float(c.attrib["cx"]) == xs[2]).attrib["cy"])  # north is up
    assert {t.text for t in root.iter(f"{SVG}text")} >= {"SHALE", "TIGHT"}


def test_treemap_areas_are_proportional_and_small_labels_are_left_out() -> None:
    svg = treemap([("Grande", 60.0), ("Medio", 30.0), ("Chico", 10.0), ("Cero", 0.0)], 400, 200, "Yacimientos")
    root = parse(svg)
    rects = list(root.iter(f"{SVG}rect"))
    assert len(rects) == 3  # a zero value has no rectangle
    areas = sorted(((float(r.attrib["width"]) + 2) * (float(r.attrib["height"]) + 2) for r in rects), reverse=True)
    total = sum(areas)
    assert [round(a / total, 2) for a in areas] == [0.6, 0.3, 0.1]
    assert "Sin datos" in treemap([], 100, 100, "t")
    assert "Grande" in svg
