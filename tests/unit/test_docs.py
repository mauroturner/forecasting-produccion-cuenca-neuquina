"""The documentation is checked like code (AC23, AC14-AC16 consistency): headings, dictionary, decisions, runbook, results."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest

from oilgas.dashboard.semantic_model import MODEL
from oilgas.docs import COLUMNS_END, COLUMNS_START, render_dictionary_tables
from oilgas.reporting import FLUID_ES, render_results_markdown
from oilgas.schema import SOURCE_COLUMNS

README_HEADINGS = [
    "1. Resumen ejecutivo", "2. Datasets y preparación", "3. Arquitectura y metodología", "4. Producto final", "5. Conclusión",
    "Resultados completos de la corrida", "Cómo correrlo de punta a punta", "Paso a paso", "Fuente y licencia",
]
README_SUBSECTIONS = [
    "1.1 Problema de negocio y solución", "1.2 Criterios de éxito e impacto",
    "2.1 Fuentes, alcance y granularidad", "2.2 Saneamiento y reglas de calidad",
    "3.1 Fuente e ingesta", "3.2 Orquestación y transformación", "3.3 Almacenamiento y modelado de datos",
    "3.4 Experimentación y Machine Learning", "3.5 Consumo y gobernanza",
    "4.1 Entregables operativos", "4.2 Lectura de resultados actuales",
    "5.1 Evaluación frente a criterios de éxito", "5.2 Limitaciones metodológicas", "5.3 Trabajo futuro",
]
README_ML_SUBSECTIONS = [
    "3.4.1 Ingeniería de características y línea base (baseline)", "3.4.2 Decisiones de modelado y ablación (ADR)",
    "3.4.3 Protocolo de validación (backtesting / cross-validation)",
]
DECISION_FIELDS = ("Contexto", "Opciones", "Decisión", "Motivo", "Afecta", "Quién")
START, END = "<!-- results:start -->", "<!-- results:end -->"
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")


@pytest.fixture(scope="module")
def readme(project_root: Path) -> str:
    return (project_root / "README.es.md").read_text(encoding="utf-8")


def read(project_root: Path, name: str) -> str:
    return (project_root / "docs" / name).read_text(encoding="utf-8")


def test_the_readme_follows_the_numbered_outline_of_the_portfolio_in_that_order(readme: str) -> None:
    """The structure of ESTRUCTURA-PROYECTOS.md: five numbered sections with their sub-sections, then the appendices."""
    assert readme.startswith("# Producción de petróleo y gas, pozo por pozo\n")
    assert re.findall(r"^## (.+)$", readme, flags=re.MULTILINE) == README_HEADINGS
    assert re.findall(r"^### (\d.+)$", readme, flags=re.MULTILINE) == README_SUBSECTIONS
    assert re.findall(r"^#### (\d.+)$", readme, flags=re.MULTILINE) == README_ML_SUBSECTIONS


def test_the_readme_has_no_section_about_how_ai_built_the_project(readme: str) -> None:
    assert "Con IA, de punta a punta" not in readme


def test_the_readme_gives_the_attribution_of_the_licence(readme: str) -> None:
    tail = readme.split("## Fuente y licencia")[1]
    assert "CC BY 4.0" in tail and "Secretaría de Energía" in tail and "https://creativecommons.org/licenses/by/4.0/" in tail


def test_the_results_block_of_the_readme_is_the_summary_of_the_run(project_root: Path, readme: str) -> None:
    check_the_english_readme(project_root, readme)
    assert readme.count(START) == 1 and readme.count(END) == 1
    block = readme.split(START)[1].split(END)[0]
    assert block.strip() == (project_root / "reports" / "backtest_summary.md").read_text(encoding="utf-8").strip()


def test_the_markdown_summary_says_what_the_json_summary_computes(project_root: Path) -> None:
    document = json.loads((project_root / "reports" / "backtest_summary.json").read_text(encoding="utf-8"))
    summary = pd.DataFrame(document["summary"])
    expected = render_results_markdown(document["criteria"], summary)
    assert (project_root / "reports" / "backtest_summary.md").read_text(encoding="utf-8") == expected


def test_an_unfavorable_verdict_is_never_left_out_of_the_readme(project_root: Path, readme: str) -> None:
    document = json.loads((project_root / "reports" / "backtest_summary.json").read_text(encoding="utf-8"))
    for fluid, result in document["criteria"]["AC14"].items():
        assert all(sentence in readme for sentence in result["verdict_es"]), fluid
        verdict = "Cumple" if result["passed"] else "No cumple"
        assert f"**{FLUID_ES[fluid].capitalize()}.** {verdict} el criterio fijado de antemano." in readme


def test_the_dictionary_documents_every_column_of_the_source_file(project_root: Path) -> None:
    text = read(project_root, "data-dictionary.md")
    missing = [c for c in SOURCE_COLUMNS if not re.search(rf"^\| `{c}` \|", text, flags=re.MULTILINE)]
    assert missing == []


def test_the_dictionary_tables_are_the_ones_generated_from_the_semantic_model(project_root: Path) -> None:
    text = read(project_root, "data-dictionary.md")
    assert text.count(COLUMNS_START) == 1 and text.count(COLUMNS_END) == 1
    block = text.split(COLUMNS_START)[1].split(COLUMNS_END)[0]
    assert block.strip() == render_dictionary_tables(MODEL).strip()


def test_every_column_of_every_exported_table_has_a_unit_or_a_dash(project_root: Path) -> None:
    text = read(project_root, "data-dictionary.md")
    for table in MODEL.tables:
        section = text.split(f"### `{table.name}`")[1].split("###")[0]
        rows = {m.group(1): m.group(2) for m in re.finditer(r"^\| `([a-z_0-9]+)` \| [^|]+ \| ([^|]+) \|", section, flags=re.MULTILINE)}
        assert set(rows) == set(table.column_names), table.name
        assert all(unit.strip() for unit in rows.values()), table.name


def test_every_decision_has_all_its_fields(project_root: Path) -> None:
    text = read(project_root, "decisions.md")
    entries = re.split(r"^## (?=D\d+ )", text, flags=re.MULTILINE)[1:]
    assert len(entries) >= 35
    for entry in entries:
        title = entry.splitlines()[0]
        for field in DECISION_FIELDS:
            assert f"- **{field}**" in entry, f"{title}: missing {field}"
        assert "**Estado**" in entry, f"{title}: missing Estado"
    numbers = [int(re.match(r"D(\d+)", e).group(1)) for e in entries]
    assert numbers == list(range(1, len(numbers) + 1))  # no gaps and no repeats


def test_the_runbook_covers_r1_to_r11(project_root: Path) -> None:
    headings = re.findall(r"^## (R\d+) ", read(project_root, "runbook.md"), flags=re.MULTILINE)
    assert headings == [f"R{n}" for n in range(1, 12)]


def test_every_document_the_readme_lists_exists(project_root: Path, readme: str) -> None:
    for name in ("data-dictionary.md", "model-card.md", "decisions.md", "runbook.md", "paso-a-paso.md", "requirements.md", "plan.md", "research.md"):
        assert (project_root / "docs" / name).is_file(), name
        assert f"docs/{name}" in readme, name


def test_relative_links_and_images_point_to_files_that_exist(project_root: Path) -> None:
    documents = [project_root / "README.md", project_root / "README.es.md", *sorted((project_root / "docs").glob("*.md"))]
    broken = []
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for target in [*LINK.findall(text), *IMAGE.findall(text)]:
            if re.match(r"^(https?:|mailto:)", target):
                continue
            if not (document.parent / target).resolve().exists():
                broken.append(f"{document.name}: {target}")
    assert broken == []


def test_the_documentation_figures_are_versioned_and_used(project_root: Path, readme: str) -> None:
    figures = sorted(p.name for p in (project_root / "docs" / "figures").glob("*.png"))
    assert figures == ["basin_forecast.png", "coverage.png", "example_well_fit.png", "method_comparison.png"]
    used = readme + read(project_root, "model-card.md")
    assert all(f"figures/{name}" in used for name in figures)


def test_the_method_tables_show_every_cell_with_a_dash_where_there_is_no_value() -> None:
    from oilgas.docs import render_method_tables

    summary = pd.DataFrame([
        {"method": "ml_hgb", "fluid": "oil", "horizon": 12, "segment": "eligible", "n_series": 5, "wape": 0.4218, "coverage": 0.78,
         "scaled_pinball": 0.4171, "share_beats_naive_last": 0.7188},
        {"method": "naive_last", "fluid": "oil", "horizon": 12, "segment": "eligible", "n_series": 5, "wape": 0.7177, "coverage": 0.79,
         "scaled_pinball": 0.679, "share_beats_naive_last": float("nan")},
    ])
    text = render_method_tables(summary)
    lines = [line for line in text.splitlines() if line.startswith("| `")]
    assert lines[0].startswith("| `naive_last` | 12 | 5 | 71,77 % | — | 0,79 | 0,679 |")  # the baseline first; no share against itself
    assert lines[1] == "| `ml_hgb` | 12 | 5 | 42,18 % | 71,88 % | 0,78 | 0,417 |"
    assert "#### Petróleo, series elegibles" in text and "Gas" not in text and "jóvenes" not in text  # only the cells that exist


def test_the_model_card_tables_are_the_ones_generated_from_the_summary(project_root: Path) -> None:
    from oilgas.docs import METHODS_END, METHODS_START, render_method_tables

    text = read(project_root, "model-card.md")
    assert text.count(METHODS_START) == 1 and text.count(METHODS_END) == 1
    document = json.loads((project_root / "reports" / "backtest_summary.json").read_text(encoding="utf-8"))
    block = text.split(METHODS_START)[1].split(METHODS_END)[0]
    assert block.strip() == render_method_tables(pd.DataFrame(document["summary"])).strip()


def check_the_english_readme(project_root: Path, readme: str) -> None:
    """README.md is the page of the project in English; README.es.md is the full one, which ``docs-sync`` and the other tests check."""
    english = (project_root / "README.md").read_text(encoding="utf-8")
    assert "**English** · [Español](README.es.md)" in english and "[English](README.md) · **Español**" in readme
    assert english.count("2 of 2 success criteria met") == 2 and "undefined" not in english and "@gmail" not in english
    for target in ("docs/screenshots/dashboard.png", "docs/screenshots/demo.png", "docs/model-card.md", "docs/evaluation.md"):
        assert f"]({target})" in english and (project_root / target).is_file(), target
