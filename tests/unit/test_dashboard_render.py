"""The HTML design of the report: every page, visual, measure and relationship, nothing external, real numbers (AC18)."""

from __future__ import annotations

import dataclasses
import html as html_lib
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd
import pytest

from oilgas.dashboard.render import render_design
from oilgas.dashboard.semantic_model import MODEL, Measure

ATTRIBUTION = "Fuente: Secretaría de Energía de la Nación (datos.energia.gob.ar), CC BY 4.0."


@pytest.fixture(scope="module")
def design(tmp_path_factory, star_outputs) -> tuple[Path, str]:
    path = render_design(MODEL, star_outputs, tmp_path_factory.mktemp("design") / "dashboard" / "powerbi-design.html", ATTRIBUTION)
    return path, path.read_text(encoding="utf-8")


def text_of(html: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", " ", html))


class Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def parsed(html: str) -> Collector:
    collector = Collector()
    collector.feed(html)
    return collector


# --- the file ----------------------------------------------------------------------------------------------------


def test_the_file_is_one_html_document_in_spanish_under_two_megabytes(design) -> None:
    path, html = design
    assert path.name == "powerbi-design.html" and path.stat().st_size < 2 * 1024 * 1024
    assert html.startswith("<!doctype html>") and '<html lang="es">' in html and "<title>Diseño del tablero de Power BI" in html
    assert 'name="viewport"' in html and html.count("<h1>") == 1
    assert [p.name for p in path.parent.iterdir()] == ["powerbi-design.html"]  # written atomically: no temporary file


def test_nothing_is_loaded_from_outside_and_there_are_no_scripts(design) -> None:
    _, html = design
    tags = parsed(html).tags
    assert not [t for t, _ in tags if t in ("script", "link", "iframe", "img", "object", "embed", "video", "audio", "source")]
    for tag, attrs in tags:
        for name in ("src", "href", "action", "data", "poster", "srcset"):
            value = attrs.get(name)
            assert value is None or value.startswith("#"), (tag, name, value)  # only links inside the page
    assert "@import" not in html and not re.search(r"url\((?!#)", html)  # only references inside the page (the arrow marker)
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in html
    assert not [k for _, a in tags for k in a if k.startswith("on")]  # no inline handlers


def test_the_attribution_the_run_and_the_data_date_are_stated(design, star_outputs) -> None:
    _, html = design
    text = text_of(html)
    assert ATTRIBUTION in text and "CC BY 4.0" in text
    assert "Corrida r1" in re.sub(r"\s+", " ", text) and "ab" * 6 in text  # the run key and the start of the source hash
    assert "Datos hasta 2024-12" in re.sub(r"\s+", " ", text)
    assert re.search(r"Pozos con pronóstico:\s*\d+ de \d+", text)


def test_rendering_twice_gives_the_same_bytes(design, star_outputs, tmp_path) -> None:
    again = render_design(MODEL, star_outputs, tmp_path / "again.html", ATTRIBUTION)
    assert again.read_bytes() == design[0].read_bytes()


# --- the content of the spec -----------------------------------------------------------------------------------------


def test_it_has_the_steps_and_every_section(design) -> None:
    _, html = design
    for key in ("armado", "modelo", "relaciones", "consultas", "medidas", "paginas", "fuente"):
        assert f'id="{key}"' in html and f'href="#{key}"' in html
    text = text_of(html)
    for fragment in ("CarpetaSalidas", "tabla de fechas", "_Medidas", "uno a varios", "1280"):
        assert fragment in text


def test_every_table_has_its_power_query(design) -> None:
    _, html = design
    for table in MODEL.tables:
        assert f"<h3>{table.name}</h3>" in html
        code = html_lib.escape(f'Parquet.Document(File.Contents(CarpetaSalidas & "{chr(92)}{table.name}.parquet"))')
        assert code in html, table.name
    assert 'Table.TransformColumnTypes(Origen, {{"month_start", type date}})' in html.replace("&quot;", '"')


def test_every_relationship_is_listed_with_its_cardinality_and_direction(design) -> None:
    _, html = design
    section = html[html.index('id="relaciones"'):html.index('id="consultas"')]
    for r in MODEL.relationships:
        row = re.search(rf"<tr><td>{r.rel_id}</td>(.*?)</tr>", section)
        assert row, r.rel_id
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1))
        assert cells[0] == f"{r.dim_table}[{r.dim_column}]" and cells[2] == f"{r.fact_table}[{r.fact_column}]"
        assert "Uno a varios (1:*)" in cells and "Única: de la dimensión al hecho" in cells and cells[-1] == "Sí"
    assert section.count("<tr>") == len(MODEL.relationships) + 1  # plus the header


def test_the_diagram_draws_every_table_and_every_relationship_with_its_ends(design) -> None:
    _, html = design
    diagram = html[html.index('class="model-svg"'):html.index("</svg>", html.index('class="model-svg"'))]
    for table in MODEL.tables:
        assert f">{table.name}</text>" in diagram
    assert diagram.count('class="rel"') == len(MODEL.relationships) == 25
    assert diagram.count('marker-end="url(#arrow)"') == 25  # the filter arrow, dimension to fact
    assert len(re.findall(r'class="card"[^>]*>1<', diagram)) == 25 and len(re.findall(r'class="card"[^>]*>\*<', diagram)) == 25
    for r in MODEL.relationships:
        assert f"{r.rel_id}: {r.dim_table}[{r.dim_column}] 1 → * {r.fact_table}[{r.fact_column}]" in diagram


def test_every_measure_appears_with_its_dax_format_and_description(design) -> None:
    _, html = design
    section = html[html.index('id="medidas"'):html.index('id="paginas"')]
    plain = html_lib.unescape(section)
    for m in MODEL.measures:
        assert f"<h3>{html_lib.escape(m.name_es)}</h3>" in section, m.name_es
        assert f"{m.name_es} =\n{m.dax}" in plain
        assert m.description_es in plain and f"<code>{html_lib.escape(m.format_string)}</code>" in section
    assert len(re.findall(r"<h3>", section)) == len(MODEL.measures)


def test_the_five_pages_have_their_visuals_placed_on_the_grid(design) -> None:
    _, html = design
    assert len(re.findall(r'<div class="canvas"', html)) == 5
    for i, page in enumerate(MODEL.pages, start=1):
        start = html.index(f'id="pagina-{i}"')
        end = html.index(f'id="pagina-{i + 1}"') if i < 5 else html.index('id="fuente"')
        block = html[start:end]
        assert f"Página {i}: {page.name_es}" in block
        assert block.count('<section class="visual"') == len(page.visuals)
        for v in page.visuals:
            assert f'style="grid-column:{v.x + 1} / span {v.w};grid-row:{v.y + 1} / span {v.h}"' in block, v.title_es
            assert f'aria-label="{html_lib.escape(v.title_es)}"' in block
            assert f"<b>{html_lib.escape(v.title_es)}</b>" in block
            fields = ", ".join(v.fields) or "—"
            assert html_lib.escape(fields) in block  # the placement table names the fields
            assert f"x {v.x}, y {v.y}, ancho {v.w}, alto {v.h}" in block
    css = html[:html.index("</style>")]
    assert "repeat(12,1fr)" in css and "repeat(9,1fr)" in css and "aspect-ratio:16/9" in css


# --- real numbers in the previews -------------------------------------------------------------------------------------


def test_the_cards_show_the_figures_of_the_last_published_month(design, star_outputs) -> None:
    _, html = design
    prod = pd.read_parquet(star_outputs / "fact_production_monthly.parquet")
    last = prod[prod["period_key"] == 202412]
    page = html[html.index('id="pagina-1"'):html.index('id="pagina-2"')]
    cards = dict(re.findall(r'<b>([^<]+)</b><span>Tarjeta</span></header><div class="body"><div class="big">([^<]*)</div>', page))
    from oilgas.dashboard.svg import format_number

    assert cards["Petróleo del último mes (m³)"] == format_number(float(last["oil_m3"].sum()), 2)
    assert cards["Gas del último mes (miles de m³)"] == format_number(float(last["gas_thousand_m3"].sum()), 2)
    assert cards["Pozos en producción"] == format_number(float(last[last["is_producing"]]["well_key"].nunique()), 1)
    assert cards["Último mes publicado"] == "2024-12"
    before = prod[prod["period_key"] == 202312]["oil_m3"].sum()
    expected = f"{(last['oil_m3'].sum() - before) / before * 100:+.1f} %".replace(".", ",")
    assert cards["Variación interanual del petróleo"] == expected


def test_the_basin_charts_draw_the_history_and_the_projection(design) -> None:
    _, html = design
    page = html[html.index('id="pagina-1"'):html.index('id="pagina-2"')]
    chart = page[page.index("Petróleo: producido y proyectado"):]
    chart = chart[:chart.index("</svg>")]
    assert chart.count("<polyline") == 2 and "<polygon" in chart  # history, P50 and the P10-P90 band
    assert "Suma de P10-P90 por pozo" in chart and 'stroke-dasharray="5 4"' in chart
    assert page.count("<svg") >= 4  # two lines, the bars and the scatter plot
    assert re.search(r"Σ P10", page)


def test_the_validation_page_shows_each_method_and_the_coverage_target(design) -> None:
    _, html = design
    page = html[html.index('id="pagina-4"'):html.index('id="pagina-5"')]
    for method in ("naive_last", "naive_mean3", "arps_exp", "arps_mh_b2", "arps_mh_b1", "ml_hgb"):
        assert method in page
    assert "Objetivo 0,8" in page and "WAPE (petróleo)" in page
    assert re.search(r"cobertura P10-P90 \d,\d\d \((calibrado|aceptable|descalibrado)\)", html_lib.unescape(page))


def test_the_quality_page_lists_the_rules_and_the_run(design) -> None:
    _, html = design
    page = html[html.index('id="pagina-5"'):html.index('id="fuente"')]
    assert "<td>V01</td>" in page and "<td>I03</td>" in page and "<td>advierte</td>" in page
    assert "<td>r1</td>" in page and "2024-12" in page
    assert page.count("<tr><td>V") + page.count("<tr><td>I") == 23


def test_the_well_page_draws_the_fit_of_a_real_well(design, star_outputs) -> None:
    _, html = design
    page = html[html.index('id="pagina-3"'):html.index('id="pagina-4"')]
    fits = pd.read_parquet(star_outputs / "fact_well_fit.parquet")
    assert "<b>qi</b>" in page and "Estado del ajuste" in page and "Curva ajustada" in page
    assert re.search(r"P50 Arps hiperbólica modificada \(b hasta 2\)", page)
    assert len(fits) > 0


# --- failures and edges -------------------------------------------------------------------------------------------------


def test_an_inconsistent_model_is_refused_before_writing(star_outputs, tmp_path) -> None:
    bad = dataclasses.replace(MODEL, measures=(*MODEL.measures, Measure("Rota", "SUM ( fact_forecast[nope] )", "0", "x")))
    with pytest.raises(ValueError, match="inconsistent"):
        render_design(bad, star_outputs, tmp_path / "x.html", ATTRIBUTION)
    assert not (tmp_path / "x.html").exists()


def test_missing_tables_give_empty_previews_not_a_crash(tmp_path, star_outputs) -> None:
    partial = tmp_path / "partial"
    partial.mkdir()
    for name in ("dim_calendar", "dim_well", "dim_company"):
        shutil.copy(star_outputs / f"{name}.parquet", partial / f"{name}.parquet")
    html = render_design(MODEL, partial, tmp_path / "partial.html", ATTRIBUTION).read_text(encoding="utf-8")
    assert html.count('<section class="visual"') == sum(len(p.visuals) for p in MODEL.pages)
    assert "Sin datos" in html and ATTRIBUTION in html


def test_text_from_the_data_is_escaped(tmp_path, star_outputs) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    folder = tmp_path / "hostile"
    shutil.copytree(star_outputs, folder)
    table = pq.read_table(folder / "dim_company.parquet")
    names = ["<script>alert(1)</script>"] + table["company_name"].to_pylist()[1:]
    changed = table.set_column(1, table.schema.field("company_name"), pa.array(names, type=pa.string()))
    pq.write_table(changed, folder / "dim_company.parquet")
    html = render_design(MODEL, folder, tmp_path / "h.html", ATTRIBUTION).read_text(encoding="utf-8")
    assert "<script" not in html


def test_the_versioned_design_file_keeps_the_contract(project_root: Path) -> None:
    path = project_root / "dashboard" / "powerbi-design.html"
    html = path.read_text(encoding="utf-8")
    assert path.stat().st_size < 2 * 1024 * 1024
    for page in MODEL.pages:
        assert f"{page.name_es}" in html and all(html_lib.escape(v.title_es) in html for v in page.visuals)
    assert all(html_lib.escape(m.name_es) in html for m in MODEL.measures)
    assert all(r.rel_id in html for r in MODEL.relationships)
    tags = parsed(html).tags
    assert not [t for t, _ in tags if t in ("script", "link", "iframe", "img")]
    assert all((a.get("href") or "#").startswith("#") and not a.get("src") for _, a in tags)
    assert "CC BY 4.0" in html
