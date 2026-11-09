"""The semantic model of the Power BI report: the single source of truth (D14).

Tables with their columns, the relationships (all one-to-many, single direction, active), the DAX
measures and the five pages with their visuals placed on a 12-column grid. The Arrow schema of every
Parquet file, the data dictionary and the HTML design all come from here, so a change of a column is
made once and the tests that read this module (keys, foreign keys, DAX references) keep them honest.
Names of tables, columns and files are in English; measures and visual titles are in Spanish (D16).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import pyarrow as pa

PAGE_COLUMNS = 12
PAGE_ROWS = 9  # 12 columns x 9 rows of equal cells fill a 16:9 canvas of 1280 x 720 px (106.7 x 80 px)
PAGE_WIDTH_PX, PAGE_HEIGHT_PX = 1280, 720
ARROW_TYPES = {
    "int32": pa.int32(), "int64": pa.int64(), "float64": pa.float64(), "string": pa.string(), "bool": pa.bool_(),
    "date": pa.date32(),
}


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str  # a key of ARROW_TYPES
    description_es: str
    unit: str | None = None


@dataclass(frozen=True)
class Table:
    name: str
    kind: Literal["dimension", "fact"]
    key: tuple[str, ...]  # a dimension's unique key or a fact's grain
    columns: tuple[Column, ...]
    description_es: str = ""

    def column(self, name: str) -> Column:
        return next(c for c in self.columns if c.name == name)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


@dataclass(frozen=True)
class Relationship:
    rel_id: str
    dim_table: str
    dim_column: str
    fact_table: str
    fact_column: str
    cardinality: str = "one_to_many"
    cross_filter: str = "single"
    active: bool = True


@dataclass(frozen=True)
class Measure:
    name_es: str
    dax: str
    format_string: str
    description_es: str


@dataclass(frozen=True)
class Visual:
    kind: str
    title_es: str
    fields: tuple[str, ...]  # "table[column]" or "[Measure]"
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Page:
    name_es: str
    visuals: tuple[Visual, ...]


@dataclass(frozen=True)
class SemanticModel:
    tables: tuple[Table, ...]
    relationships: tuple[Relationship, ...]
    measures: tuple[Measure, ...]
    pages: tuple[Page, ...]

    def table(self, name: str) -> Table:
        return next(t for t in self.tables if t.name == name)

    def measure(self, name: str) -> Measure:
        return next(m for m in self.measures if m.name_es == name)


def _c(name: str, dtype: str, description_es: str, unit: str | None = None) -> Column:
    return Column(name, dtype, description_es, unit)


# --- tables ---------------------------------------------------------------------------------------------------

M3, KM3 = "m³", "miles de m³"

DIM_CALENDAR = Table("dim_calendar", "dimension", ("period_key",), (
    _c("period_key", "int32", "Mes como AAAAMM (clave).", "AAAAMM"),
    _c("period_index", "int32", "Número de mes (año × 12 + mes − 1), para sumar y restar meses.", "meses"),
    _c("month_start", "date", "Primer día del mes; la tabla de fechas se marca con esta columna."),
    _c("year", "int32", "Año."),
    _c("month", "int32", "Mes (1 a 12)."),
    _c("month_name_es", "string", "Nombre del mes en español."),
    _c("quarter", "int32", "Trimestre (1 a 4)."),
    _c("year_month_label", "string", "Mes como AAAA-MM, para ejes y segmentadores."),
    _c("days_in_month", "int32", "Días del mes.", "días"),
    _c("is_published", "bool", "Verdadero si el mes está en la publicación; falso para los 12 meses proyectados."),
    _c("is_last_published", "bool", "Verdadero solo para el último mes publicado."),
), "Un mes por fila, desde el primero publicado hasta 12 meses después del último, sin huecos.")

DIM_WELL = Table("dim_well", "dimension", ("well_key",), (
    _c("well_key", "int64", "Identificador del pozo en la fuente (idpozo; clave)."),
    _c("well_code", "string", "Sigla del pozo (una etiqueta: no es única)."),
    _c("province", "string", "Provincia."),
    _c("concession_code", "string", "Código de la concesión o permiso."),
    _c("concession_name", "string", "Nombre de la concesión o permiso."),
    _c("field_code", "string", "Código del yacimiento."),
    _c("field_name", "string", "Nombre del yacimiento."),
    _c("formation_code", "string", "Código de la formación productiva."),
    _c("formation_name", "string", "Formación productiva."),
    _c("sub_resource_type", "string", "Subtipo de recurso: SHALE o TIGHT."),
    _c("basin", "string", "Cuenca."),
    _c("lon", "float64", "Longitud (coordenadax de la fuente), corregida si estaba intercambiada.", "grados"),
    _c("lat", "float64", "Latitud (coordenaday de la fuente), corregida si estaba intercambiada.", "grados"),
    _c("depth_m", "float64", "Profundidad; vacía si estaba fuera de rango.", "m"),
    _c("operator_current_key", "string", "Código de la operadora en el último mes informado."),
    _c("operator_current_name", "string", "Nombre de la operadora en el último mes informado."),
    _c("well_type_latest", "string", "Tipo de pozo en el último mes informado."),
    _c("well_status_latest", "string", "Estado del pozo en el último mes informado."),
    _c("extraction_method_latest", "string", "Método de extracción en el último mes informado."),
    _c("first_production_period_key", "int32", "Primer mes con producción.", "AAAAMM"),
    _c("last_report_period_key", "int32", "Último mes informado.", "AAAAMM"),
    _c("months_with_production", "int32", "Meses con petróleo o gas mayores que cero.", "meses"),
    _c("cum_oil_m3", "float64", "Petróleo acumulado.", M3),
    _c("cum_gas_thousand_m3", "float64", "Gas acumulado.", KM3),
    _c("cum_water_m3", "float64", "Agua acumulada.", M3),
    _c("quality_flags", "string", "Correcciones de calidad hechas al pozo, separadas por punto y coma (COORDS_SWAPPED, COORDS_OUTSIDE, DEPTH_INVALID, FIXED_ATTR_CHANGED)."),
), "Un pozo por fila con sus atributos fijos. La jerarquía Provincia, Concesión, Yacimiento, Pozo vive aquí (estrella).")

DIM_COMPANY = Table("dim_company", "dimension", ("company_key",), (
    _c("company_key", "string", "Código de la operadora (clave)."),
    _c("company_name", "string", "Nombre de la operadora en su último mes informado."),
), "Una operadora por fila.")

DIM_FLUID = Table("dim_fluid", "dimension", ("fluid_key",), (
    _c("fluid_key", "string", "oil o gas (clave)."),
    _c("fluid_name_es", "string", "Petróleo o Gas."),
    _c("unit", "string", "Unidad del volumen de ese fluido."),
), "Los dos fluidos que se proyectan. Nunca se suman entre sí.")

DIM_METHOD = Table("dim_method", "dimension", ("method_key",), (
    _c("method_key", "string", "Identificador del método (clave)."),
    _c("method_name_es", "string", "Nombre del método."),
    _c("family", "string", "Línea base, Arps o machine learning."),
    _c("description_es", "string", "Qué hace el método."),
    _c("is_base", "bool", "Verdadero para las líneas base ingenuas."),
    _c("sort_order", "int32", "Orden de aparición."),
), "Los seis métodos comparados.")

DIM_HORIZON = Table("dim_horizon", "dimension", ("horizon",), (
    _c("horizon", "int32", "Meses hacia adelante (1 a 12; clave).", "meses"),
    _c("horizon_label", "string", "Texto del horizonte (1 mes, 3 meses…)."),
    _c("is_headline", "bool", "Verdadero para los horizontes validados (1, 3, 6 y 12)."),
), "Horizontes del pronóstico.")

DIM_ORIGIN = Table("dim_origin", "dimension", ("origin_period_key",), (
    _c("origin_period_key", "int32", "Mes desde el que se proyectó (clave).", "AAAAMM"),
    _c("origin_label", "string", "Origen como AAAA-MM."),
    _c("is_latest", "bool", "Verdadero para el origen más reciente."),
    _c("run_key", "string", "Corrida que generó ese origen."),
), "Los últimos 12 orígenes del pronóstico en uso.")

DIM_PIPELINE_RUN = Table("dim_pipeline_run", "dimension", ("run_key",), (
    _c("run_key", "string", "Identificador de la corrida (clave)."),
    _c("started_at", "string", "Inicio (ISO 8601, UTC)."),
    _c("finished_at", "string", "Fin (ISO 8601, UTC)."),
    _c("status", "string", "unchanged, late, rejected, failed u ok."),
    _c("source_url", "string", "URL de la publicación."),
    _c("source_etag", "string", "ETag de la publicación."),
    _c("source_last_modified", "string", "Last-Modified de la publicación."),
    _c("source_size", "int64", "Tamaño de la publicación.", "bytes"),
    _c("source_sha256", "string", "SHA-256 de la publicación."),
    _c("last_period_key", "int32", "Último mes de la publicación.", "AAAAMM"),
    _c("rows_subset", "int64", "Filas del subconjunto cargado.", "filas"),
    _c("wells_subset", "int64", "Pozos del subconjunto cargado.", "pozos"),
    _c("revised_rows", "int64", "Filas de meses anteriores que cambiaron respecto de la carga previa.", "filas"),
    _c("message", "string", "Mensaje de la corrida."),
), "Una corrida del flujo por fila.")

FACT_PRODUCTION = Table("fact_production_monthly", "fact", ("well_key", "period_key"), (
    _c("well_key", "int64", "Pozo."),
    _c("period_key", "int32", "Mes.", "AAAAMM"),
    _c("company_key", "string", "Operadora del pozo en ese mes."),
    _c("oil_m3", "float64", "Petróleo producido (corregido).", M3),
    _c("gas_thousand_m3", "float64", "Gas producido (corregido).", KM3),
    _c("water_m3", "float64", "Agua producida (corregida).", M3),
    _c("effective_days", "float64", "Días de extracción efectiva; vacío si era imposible.", "días"),
    _c("is_producing", "bool", "Verdadero si el pozo produjo petróleo o gas en el mes."),
    _c("well_type", "string", "Tipo de pozo en ese mes."),
    _c("well_status", "string", "Estado del pozo en ese mes."),
    _c("extraction_method", "string", "Método de extracción en ese mes."),
    _c("quality_flags", "string", "Correcciones hechas a la fila (NEG_VOLUME, TEF_GT_DAYS, TEF_ZERO_WITH_PROD, VOLUME_CEILING)."),
    _c("run_key", "string", "Corrida que cargó la fila."),
), "Producción mensual de cada pozo.")

FACT_FORECAST = Table("fact_forecast", "fact", ("well_key", "fluid_key", "method_key", "origin_period_key", "horizon"), (
    _c("well_key", "int64", "Pozo."),
    _c("fluid_key", "string", "Fluido."),
    _c("method_key", "string", "Método."),
    _c("origin_period_key", "int32", "Mes desde el que se proyectó.", "AAAAMM"),
    _c("target_period_key", "int32", "Mes proyectado.", "AAAAMM"),
    _c("horizon", "int32", "Meses entre el origen y el mes proyectado.", "meses"),
    _c("company_key", "string", "Operadora del pozo en el origen."),
    _c("p10", "float64", "Volumen P10 del mes proyectado (en la unidad del fluido).", "m³ o miles de m³"),
    _c("p50", "float64", "Volumen P50 (la curva o la mediana).", "m³ o miles de m³"),
    _c("p90", "float64", "Volumen P90.", "m³ o miles de m³"),
    _c("segment", "string", "eligible (≥ 6 meses desde el pico) o young."),
    _c("is_selected", "bool", "Verdadero para el método elegido por el backtest para ese fluido y segmento."),
    _c("fit_status", "string", "ok, fallback_exp o fallback_naive."),
    _c("run_key", "string", "Corrida que generó la fila."),
), "Pronóstico de 12 meses por pozo, fluido, método y origen.")

FACT_WELL_FIT = Table("fact_well_fit", "fact", ("well_key", "fluid_key", "method_key", "origin_period_key"), (
    _c("well_key", "int64", "Pozo."),
    _c("fluid_key", "string", "Fluido."),
    _c("method_key", "string", "Variante de Arps."),
    _c("origin_period_key", "int32", "Mes del ajuste.", "AAAAMM"),
    _c("run_key", "string", "Corrida que generó el ajuste."),
    _c("peak_period_key", "int32", "Mes del pico usado.", "AAAAMM"),
    _c("log_qi", "float64", "Logaritmo natural de la tasa inicial (qi)."),
    _c("qi_rate_per_day", "float64", "Tasa inicial qi.", "m³/día o miles de m³/día"),
    _c("di_nominal_per_month", "float64", "Declinación inicial nominal (Di).", "1/mes"),
    _c("b", "float64", "Exponente de la hiperbólica (0 en la exponencial)."),
    _c("d_lim_nominal_per_month", "float64", "Declinación terminal nominal.", "1/mes"),
    _c("t_switch_months", "float64", "Meses desde el pico hasta el cambio a la declinación terminal.", "meses"),
    _c("d_effective_annual_initial", "float64", "Declinación efectiva anual inicial.", "fracción"),
    _c("n_points", "int32", "Puntos usados en el ajuste.", "meses"),
    _c("rmse_log", "float64", "Raíz del error cuadrático medio en escala logarítmica."),
    _c("status", "string", "ok, fallback_exp o fallback_naive."),
    _c("needs_review", "bool", "Verdadero si rmse_log supera 1,0: se conserva pero se marca para revisión."),
), "Parámetros de las curvas de Arps ajustadas en cada origen.")

FACT_FITTED_CURVE = Table("fact_fitted_curve", "fact", ("well_key", "fluid_key", "period_key"), (
    _c("well_key", "int64", "Pozo."),
    _c("fluid_key", "string", "Fluido."),
    _c("period_key", "int32", "Mes entre el pico y el origen.", "AAAAMM"),
    _c("origin_period_key", "int32", "Origen del ajuste.", "AAAAMM"),
    _c("fitted_volume", "float64", "Volumen de la curva base (arps_mh_b2) en el mes.", "m³ o miles de m³"),
), "La curva base sobre los meses ajustados, solo del último origen.")

FACT_BACKTEST = Table("fact_backtest_metrics", "fact", ("method_key", "fluid_key", "horizon", "origin_period_key", "age_bucket", "sub_resource_type"), (
    _c("method_key", "string", "Método."),
    _c("fluid_key", "string", "Fluido."),
    _c("horizon", "int32", "Horizonte evaluado.", "meses"),
    _c("origin_period_key", "int32", "Origen evaluado.", "AAAAMM"),
    _c("age_bucket", "string", "Tramo de edad de la serie: young, 06-11, 12-23, 24-59 o 60+."),
    _c("sub_resource_type", "string", "Subtipo del pozo."),
    _c("run_key", "string", "Corrida del backtest."),
    _c("n", "int64", "Pares evaluados.", "pares"),
    _c("sum_actual", "float64", "Suma de lo real.", "m³ o miles de m³"),
    _c("sum_p10", "float64", "Suma de los P10.", "m³ o miles de m³"),
    _c("sum_p50", "float64", "Suma de los P50.", "m³ o miles de m³"),
    _c("sum_p90", "float64", "Suma de los P90.", "m³ o miles de m³"),
    _c("sum_abs_error", "float64", "Suma del error absoluto del P50.", "m³ o miles de m³"),
    _c("sum_sq_error", "float64", "Suma del error cuadrático del P50.", "(m³ o miles de m³)²"),
    _c("sum_error", "float64", "Suma del error con signo del P50 (pronóstico − real).", "m³ o miles de m³"),
    _c("n_covered", "int64", "Pares con lo real entre P10 y P90.", "pares"),
    _c("sum_pinball", "float64", "Suma de la pérdida pinball de los tres cuantiles.", "m³ o miles de m³"),
), "Componentes sumables del backtest: cualquier métrica es un cociente de sumas bajo cualquier filtro.")

FACT_MODEL_SUMMARY = Table("fact_model_summary", "fact", ("method_key", "fluid_key", "horizon", "segment"), (
    _c("method_key", "string", "Método."),
    _c("fluid_key", "string", "Fluido."),
    _c("horizon", "int32", "Horizonte.", "meses"),
    _c("segment", "string", "eligible o young."),
    _c("run_key", "string", "Corrida del backtest."),
    _c("n_series", "int64", "Series evaluadas.", "series"),
    _c("n_points", "int64", "Pares evaluados.", "pares"),
    _c("mae", "float64", "Error absoluto medio.", "m³ o miles de m³"),
    _c("rmse", "float64", "Raíz del error cuadrático medio.", "m³ o miles de m³"),
    _c("wape", "float64", "Suma del error absoluto sobre la suma de lo real.", "fracción"),
    _c("bias", "float64", "Suma de (pronóstico − real) sobre la suma de lo real.", "fracción"),
    _c("coverage", "float64", "Proporción de pares con lo real entre P10 y P90.", "fracción"),
    _c("scaled_pinball", "float64", "Pinball de los tres cuantiles sobre la suma de lo real.", "fracción"),
    _c("share_beats_naive_last", "float64", "Proporción de series cuyo MAE es menor que el de repetir el último mes.", "fracción"),
    _c("share_beats_naive_mean3", "float64", "Proporción de series cuyo MAE es menor que el del promedio de 3 meses.", "fracción"),
    _c("fallback_rate", "float64", "Proporción de ajustes de Arps que cayeron a la cadena de respaldo.", "fracción"),
    _c("basin_band_coverage", "float64", "Proporción de orígenes en que el total real cae entre la suma de P10 y la de P90.", "fracción"),
    _c("coverage_verdict", "string", "calibrado, aceptable o descalibrado."),
    _c("verdict_es", "string", "Veredicto en palabras."),
), "Métricas del backtest por método, fluido, horizonte y segmento, con su veredicto.")

FACT_VALIDATION = Table("fact_validation", "fact", ("run_key", "rule_id"), (
    _c("run_key", "string", "Corrida."),
    _c("rule_id", "string", "Regla de validación (V01 a V20, I01 a I03)."),
    _c("name_es", "string", "Qué comprueba la regla."),
    _c("severity", "string", "bloqueante, advertencia o informativa."),
    _c("status", "string", "pasa, falla (bloqueante) o advierte."),
    _c("rows_affected", "int64", "Filas afectadas.", "filas"),
    _c("wells_affected", "int64", "Pozos afectados.", "pozos"),
), "Resultado de cada regla de validación en cada corrida.")

TABLES = (
    DIM_CALENDAR, DIM_WELL, DIM_COMPANY, DIM_FLUID, DIM_METHOD, DIM_HORIZON, DIM_ORIGIN, DIM_PIPELINE_RUN,
    FACT_PRODUCTION, FACT_FORECAST, FACT_WELL_FIT, FACT_FITTED_CURVE, FACT_BACKTEST, FACT_MODEL_SUMMARY, FACT_VALIDATION,
)

# --- relationships (plan section 13): every one is one-to-many, single direction, active ----------------------------

_PAIRS = (
    ("dim_calendar", "period_key", "fact_production_monthly", "period_key"),
    ("dim_calendar", "period_key", "fact_forecast", "target_period_key"),
    ("dim_calendar", "period_key", "fact_fitted_curve", "period_key"),
    ("dim_calendar", "period_key", "fact_backtest_metrics", "origin_period_key"),
    ("dim_well", "well_key", "fact_production_monthly", "well_key"),
    ("dim_well", "well_key", "fact_forecast", "well_key"),
    ("dim_well", "well_key", "fact_well_fit", "well_key"),
    ("dim_well", "well_key", "fact_fitted_curve", "well_key"),
    ("dim_company", "company_key", "fact_production_monthly", "company_key"),
    ("dim_company", "company_key", "fact_forecast", "company_key"),
    ("dim_fluid", "fluid_key", "fact_forecast", "fluid_key"),
    ("dim_fluid", "fluid_key", "fact_well_fit", "fluid_key"),
    ("dim_fluid", "fluid_key", "fact_fitted_curve", "fluid_key"),
    ("dim_fluid", "fluid_key", "fact_backtest_metrics", "fluid_key"),
    ("dim_fluid", "fluid_key", "fact_model_summary", "fluid_key"),
    ("dim_method", "method_key", "fact_forecast", "method_key"),
    ("dim_method", "method_key", "fact_well_fit", "method_key"),
    ("dim_method", "method_key", "fact_backtest_metrics", "method_key"),
    ("dim_method", "method_key", "fact_model_summary", "method_key"),
    ("dim_origin", "origin_period_key", "fact_forecast", "origin_period_key"),
    ("dim_origin", "origin_period_key", "fact_well_fit", "origin_period_key"),
    ("dim_horizon", "horizon", "fact_forecast", "horizon"),
    ("dim_horizon", "horizon", "fact_backtest_metrics", "horizon"),
    ("dim_horizon", "horizon", "fact_model_summary", "horizon"),
    ("dim_pipeline_run", "run_key", "fact_validation", "run_key"),
)
RELATIONSHIPS = tuple(Relationship(f"R{i:02d}", *pair) for i, pair in enumerate(_PAIRS, start=1))

# --- measures ---------------------------------------------------------------------------------------------------

FLUID_MEASURES = (("Petróleo", "oil", "m³", "petróleo"), ("Gas", "gas", "miles de m³", "gas"))
QUANTILES = (10, 50, 90)
LATEST_ORIGIN = (
    "VAR origen = IF ( ISFILTERED ( dim_origin[origin_period_key] ),\n"
    "        SELECTEDVALUE ( dim_origin[origin_period_key] ),\n"
    "        CALCULATE ( MAX ( dim_origin[origin_period_key] ), REMOVEFILTERS ( dim_origin ) ) )\n"
)


def _forecast_measure(label: str, fluid: str, unit: str, noun: str, quantile: int, selected: bool) -> Measure:
    """P10, P50 or P90 of a fluid at the chosen origin: the method in use, or every method to compare them."""
    by_method = "" if selected else " por método"
    chosen = "fact_forecast[is_selected] = TRUE (),\n        " if selected else ""
    dax = (
        LATEST_ORIGIN
        + f"RETURN CALCULATE ( SUM ( fact_forecast[p{quantile}] ), dim_fluid[fluid_key] = \"{fluid}\",\n"
        + f"        {chosen}dim_origin[origin_period_key] = origen )"
    )
    which = "del método en uso" if selected else "de cada método"
    suffix = (
        " Sumar el P10 o el P90 de varios pozos no da el del total: es el de pozos que se mueven juntos y es más ancho que el verdadero."
        if quantile != 50 else ""
    )
    return Measure(
        f"{label} P{quantile}{by_method} ({unit})", dax, "#,0",
        f"Volumen P{quantile} proyectado de {noun} {which}, para el origen elegido (el más reciente si no se elige).{suffix}",
    )


def _build_measures() -> tuple[Measure, ...]:
    ms: list[Measure] = [
        Measure("Petróleo producido (m³)", "SUM ( fact_production_monthly[oil_m3] )", "#,0", "Petróleo producido en el período filtrado."),
        Measure("Gas producido (miles de m³)", "SUM ( fact_production_monthly[gas_thousand_m3] )", "#,0", "Gas producido en el período filtrado."),
        Measure("Agua producida (m³)", "SUM ( fact_production_monthly[water_m3] )", "#,0", "Agua producida en el período filtrado."),
        Measure("Pozos en producción", "CALCULATE ( DISTINCTCOUNT ( fact_production_monthly[well_key] ), fact_production_monthly[is_producing] = TRUE () )", "#,0", "Pozos con petróleo o gas mayores que cero."),
        Measure("Filas por mes", "COUNTROWS ( fact_production_monthly )", "#,0", "Filas de producción por mes: sirve para ver un mes incompleto."),
        Measure(
            "Petróleo año anterior (m³)",
            "VAR periodos = VALUES ( dim_calendar[period_index] )\n"
            "RETURN CALCULATE ( [Petróleo producido (m³)], REMOVEFILTERS ( dim_calendar ),\n"
            "        TREATAS ( SELECTCOLUMNS ( periodos, \"p\", dim_calendar[period_index] - 12 ), dim_calendar[period_index] ) )",
            "#,0", "Petróleo producido 12 meses antes de cada mes filtrado.",
        ),
        Measure(
            "Variación interanual petróleo (%)",
            "DIVIDE ( [Petróleo producido (m³)] - [Petróleo año anterior (m³)], [Petróleo año anterior (m³)] )",
            "0.0%", "Variación del petróleo producido frente al mismo mes del año anterior.",
        ),
    ]
    for selected in (True, False):
        for label, fluid, unit, noun in FLUID_MEASURES:
            for q in QUANTILES:
                ms.append(_forecast_measure(label, fluid, unit, noun, q, selected))
    ms += [
        Measure("Curva ajustada petróleo (m³)", "CALCULATE ( SUM ( fact_fitted_curve[fitted_volume] ), dim_fluid[fluid_key] = \"oil\" )", "#,0", "Volumen de la curva de Arps base sobre los meses ajustados."),
        Measure("Curva ajustada gas (miles de m³)", "CALCULATE ( SUM ( fact_fitted_curve[fitted_volume] ), dim_fluid[fluid_key] = \"gas\" )", "#,0", "Volumen de la curva de Arps base sobre los meses ajustados."),
        Measure("WAPE (%)", "DIVIDE ( SUM ( fact_backtest_metrics[sum_abs_error] ), SUM ( fact_backtest_metrics[sum_actual] ) )", "0.0%", "Error absoluto ponderado: suma del error absoluto sobre la suma de lo real."),
        Measure("MAE", "DIVIDE ( SUM ( fact_backtest_metrics[sum_abs_error] ), SUM ( fact_backtest_metrics[n] ) )", "#,0.0", "Error absoluto medio, en la unidad del fluido."),
        Measure("RMSE", "SQRT ( DIVIDE ( SUM ( fact_backtest_metrics[sum_sq_error] ), SUM ( fact_backtest_metrics[n] ) ) )", "#,0.0", "Raíz del error cuadrático medio, en la unidad del fluido."),
        Measure("Sesgo (%)", "DIVIDE ( SUM ( fact_backtest_metrics[sum_error] ), SUM ( fact_backtest_metrics[sum_actual] ) )", "0.0%", "Positivo: el método proyecta de más."),
        Measure("Cobertura P10-P90 (%)", "DIVIDE ( SUM ( fact_backtest_metrics[n_covered] ), SUM ( fact_backtest_metrics[n] ) )", "0.0%", "Proporción de pares con lo real entre P10 y P90; el objetivo es 80 %."),
        Measure("Objetivo de cobertura", "0.8", "0.0%", "Cobertura que debería tener una banda P10-P90."),
        Measure("Pinball escalada", "DIVIDE ( SUM ( fact_backtest_metrics[sum_pinball] ), SUM ( fact_backtest_metrics[sum_actual] ) )", "0.000", "Pérdida pinball de los tres cuantiles sobre la suma de lo real; mide a la vez la mediana y las bandas."),
        Measure("WAPE línea base (%)", "CALCULATE ( [WAPE (%)], REMOVEFILTERS ( dim_method ), dim_method[method_key] = \"naive_last\" )", "0.0%", "WAPE de repetir el último mes, con los demás filtros iguales."),
        Measure("Mejora frente a la línea base (%)", "1 - DIVIDE ( [WAPE (%)], [WAPE línea base (%)] )", "0.0%", "Cuánto baja el WAPE frente a repetir el último mes; negativa si lo empeora."),
        Measure(
            "Error del total de la cuenca (%)",
            "DIVIDE ( ABS ( SUM ( fact_backtest_metrics[sum_p50] ) - SUM ( fact_backtest_metrics[sum_actual] ) ), SUM ( fact_backtest_metrics[sum_actual] ) )",
            "0.0%", "Diferencia relativa entre el total proyectado y el real de las series evaluadas.",
        ),
        Measure("Series que superan a la línea base (%)", "AVERAGE ( fact_model_summary[share_beats_naive_last] )", "0.0%", "Proporción de series en que el método tiene un MAE menor que repetir el último mes."),
        Measure("Veredicto", "SELECTEDVALUE ( fact_model_summary[verdict_es] )", "@", "Veredicto en palabras del método, fluido, horizonte y segmento elegidos."),
        Measure("Último origen", "CALCULATE ( MAX ( dim_origin[origin_period_key] ), REMOVEFILTERS ( dim_origin ) )", "0", "Origen más reciente del pronóstico."),
        Measure(
            "qi del pozo",
            "CALCULATE ( MAX ( fact_well_fit[qi_rate_per_day] ), dim_method[method_key] = \"arps_mh_b2\", fact_well_fit[origin_period_key] = [Último origen] )",
            "#,0.0", "Tasa inicial de la curva base, por día.",
        ),
        Measure(
            "Di del pozo (por mes)",
            "CALCULATE ( MAX ( fact_well_fit[di_nominal_per_month] ), dim_method[method_key] = \"arps_mh_b2\", fact_well_fit[origin_period_key] = [Último origen] )",
            "0.000", "Declinación inicial nominal de la curva base.",
        ),
        Measure(
            "b del pozo",
            "CALCULATE ( MAX ( fact_well_fit[b] ), dim_method[method_key] = \"arps_mh_b2\", fact_well_fit[origin_period_key] = [Último origen] )",
            "0.00", "Exponente de la curva base.",
        ),
        Measure(
            "Declinación efectiva anual inicial (%)",
            "CALCULATE ( MAX ( fact_well_fit[d_effective_annual_initial] ), dim_method[method_key] = \"arps_mh_b2\", fact_well_fit[origin_period_key] = [Último origen] )",
            "0.0%", "Declinación del primer año de la curva base.",
        ),
        Measure(
            "Estado del ajuste",
            "CALCULATE ( SELECTEDVALUE ( fact_well_fit[status] ), dim_method[method_key] = \"arps_mh_b2\", fact_well_fit[origin_period_key] = [Último origen] )",
            "@", "ok, fallback_exp o fallback_naive.",
        ),
        Measure(
            "Último mes publicado",
            "CALCULATE ( MAX ( dim_pipeline_run[last_period_key] ), dim_pipeline_run[status] = \"ok\" )",
            "0",
            "Último mes de una corrida terminada (AAAAMM); una corrida que cargó un mes y falló después no cuenta.",
        ),
        Measure(
            "Días desde el fin del último mes",
            "VAR k = [Último mes publicado]\n"
            "RETURN DATEDIFF ( EOMONTH ( DATE ( INT ( k / 100 ), MOD ( k, 100 ), 1 ), 0 ), TODAY (), DAY )",
            "#,0", "Antigüedad de los datos; más de 55 días es una publicación tardía.",
        ),
        Measure(
            "Estado de la última corrida",
            "CALCULATE ( MAX ( dim_pipeline_run[status] ), TOPN ( 1, ALL ( dim_pipeline_run ), dim_pipeline_run[started_at], DESC ) )",
            "@", "Estado de la corrida más reciente.",
        ),
        Measure("Reglas bloqueantes fallidas", "CALCULATE ( COUNTROWS ( fact_validation ), fact_validation[severity] = \"bloqueante\", fact_validation[status] = \"falla\" )", "#,0", "Reglas bloqueantes que fallaron en las corridas filtradas."),
    ]
    return tuple(ms)


MEASURES = _build_measures()

# --- pages: x, y, w, h in cells of the 12 x 9 grid ----------------------------------------------------------------

ATTRIBUTION = "Fuente: Secretaría de Energía de la Nación (datos.energia.gob.ar), CC BY 4.0."
PAGES = (
    Page("Cuenca", (
        Visual("slicer", "Provincia", ("dim_well[province]",), 0, 0, 2, 1),
        Visual("slicer", "Empresa", ("dim_company[company_name]",), 2, 0, 2, 1),
        Visual("slicer", "Yacimiento", ("dim_well[field_name]",), 4, 0, 2, 1),
        Visual("slicer", "Subtipo", ("dim_well[sub_resource_type]",), 6, 0, 2, 1),
        Visual("slicer", "Formación", ("dim_well[formation_name]",), 8, 0, 2, 1),
        Visual("slicer", "Período", ("dim_calendar[year_month_label]",), 10, 0, 2, 1),
        Visual("card", "Petróleo del último mes (m³)", ("[Petróleo producido (m³)]",), 0, 1, 3, 1),
        Visual("card", "Gas del último mes (miles de m³)", ("[Gas producido (miles de m³)]",), 3, 1, 3, 1),
        Visual("card", "Variación interanual del petróleo", ("[Variación interanual petróleo (%)]",), 6, 1, 2, 1),
        Visual("card", "Pozos en producción", ("[Pozos en producción]",), 8, 1, 2, 1),
        Visual("card", "Último mes publicado", ("[Último mes publicado]",), 10, 1, 2, 1),
        Visual("lineChart", "Petróleo: producido y proyectado (m³)", (
            "dim_calendar[month_start]", "[Petróleo producido (m³)]", "[Petróleo P50 (m³)]", "[Petróleo P10 (m³)]", "[Petróleo P90 (m³)]",
        ), 0, 2, 6, 3),
        Visual("lineChart", "Gas: producido y proyectado (miles de m³)", (
            "dim_calendar[month_start]", "[Gas producido (miles de m³)]", "[Gas P50 (miles de m³)]", "[Gas P10 (miles de m³)]", "[Gas P90 (miles de m³)]",
        ), 6, 2, 6, 3),
        Visual("barChart", "10 empresas con más petróleo, últimos 12 meses", ("dim_company[company_name]", "[Petróleo producido (m³)]"), 0, 5, 4, 3),
        Visual("scatterChart", "Pozos: ubicación, tamaño por petróleo de 12 meses y color por subtipo", (
            "dim_well[lon]", "dim_well[lat]", "[Petróleo producido (m³)]", "dim_well[sub_resource_type]",
        ), 4, 5, 5, 3),
        Visual("table", "Suma de P10 por pozo y de P90 por pozo (no son las del total)", ("[Petróleo P10 (m³)]", "[Petróleo P90 (m³)]"), 9, 5, 3, 3),
        Visual("text", "Atribución de los datos", (), 0, 8, 12, 1),
    )),
    Page("Empresas y yacimientos", (
        Visual("matrix", "Producción por empresa y año", ("dim_company[company_name]", "dim_calendar[year]", "[Petróleo producido (m³)]", "[Gas producido (miles de m³)]"), 0, 0, 7, 4),
        Visual("treemap", "Petróleo por yacimiento", ("dim_well[field_name]", "[Petróleo producido (m³)]"), 7, 0, 5, 4),
        Visual("table", "Yacimientos: pozos, petróleo de 12 meses, P50 de los próximos 12 meses y variación", (
            "dim_well[field_name]", "[Pozos en producción]", "[Petróleo producido (m³)]", "[Petróleo P50 (m³)]", "[Variación interanual petróleo (%)]",
        ), 0, 4, 12, 5),
    )),
    Page("Pozo", (
        Visual("slicer", "Pozo (con búsqueda)", ("dim_well[well_code]",), 0, 0, 3, 1),
        Visual("card", "Provincia", ("dim_well[province]",), 3, 0, 2, 1),
        Visual("card", "Formación", ("dim_well[formation_name]",), 5, 0, 3, 1),
        Visual("card", "Subtipo", ("dim_well[sub_resource_type]",), 8, 0, 2, 1),
        Visual("card", "Operadora", ("dim_well[operator_current_name]",), 10, 0, 2, 1),
        Visual("lineChart", "Petróleo: producido, curva ajustada y P10/P50/P90 por método (m³)", (
            "dim_calendar[month_start]", "dim_method[method_name_es]", "[Petróleo producido (m³)]", "[Curva ajustada petróleo (m³)]",
            "[Petróleo P10 por método (m³)]", "[Petróleo P50 por método (m³)]", "[Petróleo P90 por método (m³)]",
        ), 0, 1, 8, 4),
        Visual("multiRowCard", "Ajuste de la curva base", (
            "[qi del pozo]", "[Di del pozo (por mes)]", "[b del pozo]", "[Declinación efectiva anual inicial (%)]", "[Estado del ajuste]",
        ), 8, 1, 4, 4),
        Visual("table", "Últimos 24 meses y 12 proyectados", ("dim_calendar[year_month_label]", "[Petróleo producido (m³)]", "[Petróleo P50 (m³)]", "[Gas producido (miles de m³)]", "[Gas P50 (miles de m³)]"), 0, 5, 12, 4),
    )),
    Page("Validación del modelo", (
        Visual("slicer", "Fluido", ("dim_fluid[fluid_name_es]",), 0, 0, 3, 1),
        Visual("slicer", "Horizonte", ("dim_horizon[horizon_label]",), 3, 0, 3, 1),
        Visual("slicer", "Segmento", ("fact_model_summary[segment]",), 6, 0, 3, 1),
        Visual("slicer", "Origen", ("dim_origin[origin_label]",), 9, 0, 3, 1),
        Visual("clusteredColumnChart", "WAPE por método y horizonte", ("dim_horizon[horizon_label]", "dim_method[method_name_es]", "[WAPE (%)]"), 0, 1, 6, 3),
        Visual("lineChart", "Cobertura P10-P90 por horizonte y método, con el objetivo de 0,8", ("dim_horizon[horizon_label]", "dim_method[method_name_es]", "[Cobertura P10-P90 (%)]", "[Objetivo de cobertura]"), 6, 1, 6, 3),
        Visual("barChart", "Series que superan a la línea base", ("dim_method[method_name_es]", "[Series que superan a la línea base (%)]"), 0, 4, 4, 3),
        Visual("matrix", "WAPE por método y tramo de edad", ("dim_method[method_name_es]", "fact_backtest_metrics[age_bucket]", "[WAPE (%)]"), 4, 4, 5, 3),
        Visual("card", "Veredicto", ("[Veredicto]",), 9, 4, 3, 3),
        Visual("lineChart", "WAPE por origen", ("dim_calendar[month_start]", "dim_method[method_name_es]", "[WAPE (%)]"), 0, 7, 12, 2),
    )),
    Page("Calidad y frescura", (
        Visual("card", "Último mes publicado", ("[Último mes publicado]",), 0, 0, 3, 1),
        Visual("card", "Días desde el fin de ese mes", ("[Días desde el fin del último mes]",), 3, 0, 3, 1),
        Visual("card", "Estado de la última corrida", ("[Estado de la última corrida]",), 6, 0, 3, 1),
        Visual("card", "Reglas bloqueantes fallidas", ("[Reglas bloqueantes fallidas]",), 9, 0, 3, 1),
        Visual("table", "Reglas de validación", ("fact_validation[rule_id]", "fact_validation[name_es]", "fact_validation[severity]", "fact_validation[rows_affected]", "fact_validation[status]"), 0, 1, 8, 5),
        Visual("lineChart", "Filas por mes", ("dim_calendar[month_start]", "[Filas por mes]"), 8, 1, 4, 5),
        Visual("table", "Corridas", ("dim_pipeline_run[run_key]", "dim_pipeline_run[started_at]", "dim_pipeline_run[status]", "dim_pipeline_run[last_period_key]", "dim_pipeline_run[revised_rows]"), 0, 6, 12, 3),
    )),
)

MODEL = SemanticModel(TABLES, RELATIONSHIPS, MEASURES, PAGES)

# --- helpers ------------------------------------------------------------------------------------------------------

_COLUMN_REF = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\[([A-Za-z_][A-Za-z0-9_]*)\]")
_MEASURE_REF = re.compile(r"(?<![A-Za-z0-9_\]])\[([^\[\]]+)\]")


def dax_column_refs(dax: str) -> set[tuple[str, str]]:
    """The ``(table, column)`` pairs a DAX expression names as ``table[column]``."""
    return {(t, c) for t, c in _COLUMN_REF.findall(dax)}


def dax_measure_refs(dax: str) -> set[str]:
    """The names of the measures a DAX expression names as ``[Measure]`` (a bracket not attached to a table)."""
    return set(_MEASURE_REF.findall(dax))


def arrow_schema(table: Table) -> pa.Schema:
    """The Arrow schema of a table's Parquet file, every field nullable except the key columns."""
    return pa.schema([pa.field(c.name, ARROW_TYPES[c.dtype], nullable=c.name not in table.key) for c in table.columns])


def _field_problem(model: SemanticModel, field: str) -> str | None:
    """Why a visual field does not resolve, or None."""
    if field.startswith("["):
        name = field[1:-1] if field.endswith("]") else field
        return None if any(m.name_es == name for m in model.measures) else f"unknown measure {field}"
    match = _COLUMN_REF.fullmatch(field)
    if match is None:
        return f"malformed field {field!r}"
    table, column = match.groups()
    if not any(t.name == table and column in t.column_names for t in model.tables):
        return f"unknown column {field}"
    return None


def validate_model(model: SemanticModel) -> list[str]:
    """Every inconsistency of the model as text (empty when it is sound): keys, relationships, DAX, pages."""
    problems: list[str] = []
    tables = {t.name: t for t in model.tables}
    if len(tables) != len(model.tables):
        problems.append("duplicate table names")
    for t in model.tables:
        names = t.column_names
        if len(set(names)) != len(names):
            problems.append(f"{t.name}: duplicate column names")
        for c in t.columns:
            if c.dtype not in ARROW_TYPES:
                problems.append(f"{t.name}[{c.name}]: unknown type {c.dtype!r}")
            if not c.description_es:
                problems.append(f"{t.name}[{c.name}]: no description")
        missing = [k for k in t.key if k not in names]
        if missing or not t.key:
            problems.append(f"{t.name}: key {list(t.key)} is not made of its columns")
        if t.kind == "dimension" and len(t.key) != 1:
            problems.append(f"{t.name}: a dimension has exactly one key column")
    seen_ids: set[str] = set()
    for r in model.relationships:
        label = f"{r.rel_id} {r.dim_table}[{r.dim_column}] -> {r.fact_table}[{r.fact_column}]"
        if r.rel_id in seen_ids:
            problems.append(f"{label}: duplicate relationship id")
        seen_ids.add(r.rel_id)
        dim, fact = tables.get(r.dim_table), tables.get(r.fact_table)
        if dim is None or fact is None:
            problems.append(f"{label}: unknown table")
            continue
        if dim.kind != "dimension" or fact.kind != "fact":
            problems.append(f"{label}: must go from a dimension to a fact")
        if dim.key != (r.dim_column,):
            problems.append(f"{label}: the one side must be the key of the dimension")
        if r.fact_column not in fact.column_names or r.dim_column not in dim.column_names:
            problems.append(f"{label}: unknown column")
        elif dim.column(r.dim_column).dtype != fact.column(r.fact_column).dtype:
            problems.append(f"{label}: the columns have different types")
        if r.cardinality != "one_to_many":
            problems.append(f"{label}: cardinality must be one_to_many")
        if r.cross_filter != "single":
            problems.append(f"{label}: the filter must be single direction (dimension to fact)")
        if not r.active:
            problems.append(f"{label}: must be active")
    names = [m.name_es for m in model.measures]
    if len(set(names)) != len(names):
        problems.append("duplicate measure names")
    for m in model.measures:
        if m.dax.count("(") != m.dax.count(")"):
            problems.append(f"[{m.name_es}]: unbalanced parentheses in the DAX")
        for table, column in sorted(dax_column_refs(m.dax)):
            if table not in tables or column not in tables[table].column_names:
                problems.append(f"[{m.name_es}]: {table}[{column}] does not exist")
        for ref in sorted(dax_measure_refs(m.dax) - {m.name_es}):
            if ref not in names:
                problems.append(f"[{m.name_es}]: measure [{ref}] does not exist")
        if not m.description_es or not m.format_string:
            problems.append(f"[{m.name_es}]: needs a format and a description")
    for page in model.pages:
        taken: dict[tuple[int, int], str] = {}
        for v in page.visuals:
            label = f"{page.name_es}: {v.title_es}"
            for field in v.fields:
                if (why := _field_problem(model, field)) is not None:
                    problems.append(f"{label}: {why}")
            if v.w < 1 or v.h < 1 or v.x < 0 or v.y < 0 or v.x + v.w > PAGE_COLUMNS or v.y + v.h > PAGE_ROWS:
                problems.append(f"{label}: outside the {PAGE_COLUMNS} x {PAGE_ROWS} grid")
                continue
            for cx in range(v.x, v.x + v.w):
                for cy in range(v.y, v.y + v.h):
                    if (cx, cy) in taken:
                        problems.append(f"{label}: overlaps {taken[cx, cy]}")
                        break
                    taken[cx, cy] = v.title_es
                else:
                    continue
                break
    return problems
