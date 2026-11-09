"""The semantic model of the report: tables, relationships 1:* with a single filter, DAX references, pages (AC17)."""

from __future__ import annotations

import dataclasses

import pyarrow as pa
import pytest

from oilgas.dashboard.semantic_model import (
    ARROW_TYPES,
    MODEL,
    PAGE_COLUMNS,
    PAGE_ROWS,
    Measure,
    Page,
    Visual,
    arrow_schema,
    dax_column_refs,
    dax_measure_refs,
    validate_model,
)

DIMENSIONS = {
    "dim_calendar", "dim_well", "dim_company", "dim_fluid", "dim_method", "dim_horizon", "dim_origin", "dim_pipeline_run",
}
FACTS = {
    "fact_production_monthly", "fact_forecast", "fact_well_fit", "fact_fitted_curve", "fact_backtest_metrics",
    "fact_model_summary", "fact_validation",
}
# The relationships of the plan (section 13): dimension column -> fact column.
PLANNED = {
    ("dim_calendar[period_key]", "fact_production_monthly[period_key]"),
    ("dim_calendar[period_key]", "fact_forecast[target_period_key]"),
    ("dim_calendar[period_key]", "fact_fitted_curve[period_key]"),
    ("dim_calendar[period_key]", "fact_backtest_metrics[origin_period_key]"),
    *((f"dim_well[well_key]", f"{f}[well_key]") for f in ("fact_production_monthly", "fact_forecast", "fact_well_fit", "fact_fitted_curve")),
    *((f"dim_company[company_key]", f"{f}[company_key]") for f in ("fact_production_monthly", "fact_forecast")),
    *((f"dim_fluid[fluid_key]", f"{f}[fluid_key]") for f in ("fact_forecast", "fact_well_fit", "fact_fitted_curve", "fact_backtest_metrics", "fact_model_summary")),
    *((f"dim_method[method_key]", f"{f}[method_key]") for f in ("fact_forecast", "fact_well_fit", "fact_backtest_metrics", "fact_model_summary")),
    *((f"dim_origin[origin_period_key]", f"{f}[origin_period_key]") for f in ("fact_forecast", "fact_well_fit")),
    *((f"dim_horizon[horizon]", f"{f}[horizon]") for f in ("fact_forecast", "fact_backtest_metrics", "fact_model_summary")),
    ("dim_pipeline_run[run_key]", "fact_validation[run_key]"),
}


def test_the_model_is_consistent() -> None:
    assert validate_model(MODEL) == []


def test_the_tables_are_the_eight_dimensions_and_the_seven_facts_of_the_plan() -> None:
    assert {t.name for t in MODEL.tables if t.kind == "dimension"} == DIMENSIONS
    assert {t.name for t in MODEL.tables if t.kind == "fact"} == FACTS
    assert len(MODEL.tables) == 15


def test_there_are_25_relationships_r01_to_r25_and_they_are_the_planned_ones() -> None:
    assert [r.rel_id for r in MODEL.relationships] == [f"R{i:02d}" for i in range(1, 26)]
    assert {(f"{r.dim_table}[{r.dim_column}]", f"{r.fact_table}[{r.fact_column}]") for r in MODEL.relationships} == PLANNED


def test_every_relationship_is_one_to_many_with_a_single_filter_from_the_dimension_and_active() -> None:
    for r in MODEL.relationships:
        assert (r.cardinality, r.cross_filter, r.active) == ("one_to_many", "single", True), r.rel_id
        assert r.dim_table in DIMENSIONS and r.fact_table in FACTS
        assert MODEL.table(r.dim_table).key == (r.dim_column,)  # the "one" side is the key of the dimension
        assert MODEL.table(r.dim_table).column(r.dim_column).dtype == MODEL.table(r.fact_table).column(r.fact_column).dtype


def test_the_measures_of_the_plan_exist_and_the_forecast_ones_are_generated_per_fluid_and_quantile() -> None:
    names = {m.name_es for m in MODEL.measures}
    assert {
        "Petróleo producido (m³)", "Gas producido (miles de m³)", "Agua producida (m³)", "Pozos en producción", "Filas por mes",
        "Petróleo año anterior (m³)", "Variación interanual petróleo (%)", "Curva ajustada petróleo (m³)",
        "Curva ajustada gas (miles de m³)", "WAPE (%)", "MAE", "RMSE", "Sesgo (%)", "Cobertura P10-P90 (%)", "Objetivo de cobertura",
        "Pinball escalada", "WAPE línea base (%)", "Mejora frente a la línea base (%)", "Error del total de la cuenca (%)",
        "Series que superan a la línea base (%)", "Veredicto", "Último mes publicado", "Reglas bloqueantes fallidas",
    } <= names
    for fluid, unit in (("Petróleo", "m³"), ("Gas", "miles de m³")):
        for q in (10, 50, 90):
            assert f"{fluid} P{q} ({unit})" in names and f"{fluid} P{q} por método ({unit})" in names
    assert len(names) == len(MODEL.measures)


def test_the_selected_forecast_measure_filters_the_method_in_use_and_the_origin() -> None:
    selected = MODEL.measure("Petróleo P50 (m³)").dax
    assert 'fact_forecast[is_selected] = TRUE ()' in selected and 'dim_fluid[fluid_key] = "oil"' in selected
    assert "SUM ( fact_forecast[p50] )" in selected and "dim_origin[origin_period_key] = origen" in selected
    by_method = MODEL.measure("Petróleo P50 por método (m³)").dax
    assert "is_selected" not in by_method  # every method, to compare them on the Pozo page
    assert 'dim_fluid[fluid_key] = "gas"' in MODEL.measure("Gas P90 (miles de m³)").dax


def test_every_dax_column_reference_names_a_column_of_the_model() -> None:
    columns = {(t.name, c) for t in MODEL.tables for c in t.column_names}
    for m in MODEL.measures:
        refs = dax_column_refs(m.dax)
        assert refs <= columns, (m.name_es, refs - columns)


def test_dax_references_are_read_without_mistaking_measures_for_columns() -> None:
    dax = 'DIVIDE ( [WAPE (%)], SUM ( fact_forecast[p50] ) ) + CALCULATE ( [Otra], dim_fluid[fluid_key] = "oil" )'
    assert dax_column_refs(dax) == {("fact_forecast", "p50"), ("dim_fluid", "fluid_key")}
    assert dax_measure_refs(dax) == {"WAPE (%)", "Otra"}
    assert dax_column_refs("1 + 2") == set() and dax_measure_refs("1 + 2") == set()


def test_there_are_five_pages_with_their_visuals_inside_a_12_column_grid_without_overlaps() -> None:
    assert [p.name_es for p in MODEL.pages] == ["Cuenca", "Empresas y yacimientos", "Pozo", "Validación del modelo", "Calidad y frescura"]
    for page in MODEL.pages:
        cells = set()
        for v in page.visuals:
            assert 0 <= v.x and v.x + v.w <= PAGE_COLUMNS and 0 <= v.y and v.y + v.h <= PAGE_ROWS, (page.name_es, v.title_es)
            block = {(x, y) for x in range(v.x, v.x + v.w) for y in range(v.y, v.y + v.h)}
            assert not cells & block, (page.name_es, v.title_es)
            cells |= block
    assert (PAGE_COLUMNS, PAGE_ROWS) == (12, 9)  # 12 x 9 equal cells fill a 16:9 canvas


def test_the_basin_page_has_the_slicers_cards_and_charts_of_the_plan() -> None:
    page = MODEL.pages[0]
    kinds = [v.kind for v in page.visuals]
    assert kinds.count("slicer") == 6 and kinds.count("card") == 5 and kinds.count("lineChart") == 2
    assert {"barChart", "scatterChart", "text"} <= set(kinds)
    titles = {v.title_es for v in page.visuals}
    assert "Petróleo: producido y proyectado (m³)" in titles and "10 empresas con más petróleo, últimos 12 meses" in titles
    line = next(v for v in page.visuals if v.title_es.startswith("Petróleo: producido"))
    assert {"[Petróleo producido (m³)]", "[Petróleo P50 (m³)]", "[Petróleo P10 (m³)]", "[Petróleo P90 (m³)]", "dim_calendar[month_start]"} <= set(line.fields)
    scatter = next(v for v in page.visuals if v.kind == "scatterChart")
    assert {"dim_well[lon]", "dim_well[lat]"} <= set(scatter.fields)  # no map service needed


def test_the_other_pages_show_what_the_plan_asks_for() -> None:
    companies, well, validation, quality = MODEL.pages[1:]
    assert {"matrix", "treemap", "table"} == {v.kind for v in companies.visuals}
    assert any(v.kind == "slicer" and v.fields == ("dim_well[well_code]",) for v in well.visuals)
    assert any(v.kind == "multiRowCard" and "[Estado del ajuste]" in v.fields for v in well.visuals)
    assert any(v.title_es == "Veredicto" and v.fields == ("[Veredicto]",) for v in validation.visuals)
    assert any("[Objetivo de cobertura]" in v.fields for v in validation.visuals)
    assert {"[Último mes publicado]", "[Reglas bloqueantes fallidas]"} <= {f for v in quality.visuals for f in v.fields}


def test_arrow_schemas_follow_the_declared_types_and_keys_are_not_nullable() -> None:
    for table in MODEL.tables:
        schema = arrow_schema(table)
        assert schema.names == list(table.column_names)
        for column, field in zip(table.columns, schema, strict=True):
            assert field.type == ARROW_TYPES[column.dtype]
            assert field.nullable == (column.name not in table.key)
    calendar = arrow_schema(MODEL.table("dim_calendar"))
    assert calendar.field("month_start").type == pa.date32() and calendar.field("period_key").type == pa.int32()
    assert arrow_schema(MODEL.table("fact_forecast")).field("is_selected").type == pa.bool_()


def test_every_column_has_a_description_and_the_measures_a_format() -> None:
    assert all(c.description_es for t in MODEL.tables for c in t.columns)
    assert all(m.format_string and m.description_es for m in MODEL.measures)


# --- the validation catches what breaks the contract -------------------------------------------------------------


def with_relationship(**changes):
    relationships = list(MODEL.relationships)
    relationships[0] = dataclasses.replace(relationships[0], **changes)
    return dataclasses.replace(MODEL, relationships=tuple(relationships))


@pytest.mark.parametrize(
    ("changes", "word"),
    [({"cross_filter": "both"}, "single direction"), ({"cardinality": "many_to_many"}, "one_to_many"),
     ({"active": False}, "active"), ({"fact_column": "nope"}, "unknown column"), ({"dim_column": "year"}, "key of the dimension"),
     ({"fact_table": "dim_well"}, "dimension to a fact")],
)
def test_a_broken_relationship_is_reported(changes: dict, word: str) -> None:
    assert any(word in problem for problem in validate_model(with_relationship(**changes)))


def test_a_dax_reference_to_a_missing_column_or_measure_is_reported() -> None:
    bad = dataclasses.replace(MODEL, measures=(*MODEL.measures, Measure("Rota", "SUM ( fact_forecast[nope] ) + [No existe]", "0", "x")))
    problems = validate_model(bad)
    assert any("fact_forecast[nope]" in p for p in problems) and any("[No existe]" in p for p in problems)
    unbalanced = dataclasses.replace(MODEL, measures=(*MODEL.measures, Measure("Abierta", "SUM ( fact_forecast[p50]", "0", "x")))
    assert any("parentheses" in p for p in validate_model(unbalanced))
    duplicate = dataclasses.replace(MODEL, measures=(*MODEL.measures, MODEL.measures[0]))
    assert any("duplicate measure" in p for p in validate_model(duplicate))


def test_a_visual_outside_the_grid_overlapping_or_with_an_unknown_field_is_reported() -> None:
    page = MODEL.pages[0]
    extra = (
        Visual("card", "Fuera", ("[Pozos en producción]",), 11, 0, 3, 1),
        Visual("card", "Encima", ("[Pozos en producción]",), 0, 0, 2, 1),
        Visual("card", "Sin campo", ("dim_well[nope]", "[No existe]"), 0, 8, 1, 1),
    )
    bad = dataclasses.replace(MODEL, pages=(Page(page.name_es, (*page.visuals, *extra)), *MODEL.pages[1:]))
    problems = validate_model(bad)
    assert any("Fuera" in p and "grid" in p for p in problems)
    assert any("Encima" in p and "overlaps" in p for p in problems)
    assert any("dim_well[nope]" in p for p in problems) and any("[No existe]" in p for p in problems)
