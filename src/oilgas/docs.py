"""Generated parts of the documentation: the tables of the data dictionary come from the semantic model (D14).

The dictionary lists each column of each exported Parquet file with its type, unit and meaning. Writing
them by hand would let the documentation drift from the files, so ``docs-sync`` copies this text between
two markers of ``docs/data-dictionary.md`` and a test keeps the file and the model equal.
"""

from __future__ import annotations

import pandas as pd

from oilgas.dashboard.semantic_model import SemanticModel
from oilgas.reporting import FLUID_ES, SEGMENT_ES, _decimal, _percent

COLUMNS_START = "<!-- columns:start -->"
COLUMNS_END = "<!-- columns:end -->"
METHODS_START = "<!-- methods:start -->"
METHODS_END = "<!-- methods:end -->"
METHOD_ORDER = ("naive_last", "naive_mean3", "arps_exp", "arps_mh_b1", "arps_mh_b2", "ml_hgb")
KIND_ES = {"dimension": "dimensión", "fact": "hecho"}
DTYPE_ES = {"int32": "entero 32", "int64": "entero 64", "float64": "decimal", "string": "texto", "bool": "verdadero/falso", "date": "fecha"}
NO_UNIT = "—"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_dictionary_tables(model: SemanticModel) -> str:
    """One section per exported table: what it is, its key or grain, and every column with type, unit and meaning."""
    lines: list[str] = []
    for table in model.tables:
        key_label = "Clave" if table.kind == "dimension" else "Grano"
        keys = ", ".join(f"`{k}`" for k in table.key)
        lines += [f"### `{table.name}`", "", f"{KIND_ES[table.kind].capitalize()}. {_cell(table.description_es)} {key_label}: {keys}.".replace("  ", " "), ""]
        lines += ["| Columna | Tipo | Unidad | Significado |", "| --- | --- | --- | --- |"]
        for column in table.columns:
            lines.append(f"| `{column.name}` | {DTYPE_ES[column.dtype]} | {_cell(column.unit or NO_UNIT)} | {_cell(column.description_es)} |")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _share(value) -> str:
    return "—" if pd.isna(value) else f"{_percent(float(value))} %"


def render_method_tables(summary: pd.DataFrame) -> str:
    """The results of every method, fluid, horizon and segment from ``model_summary`` (the rows of ``backtest_summary.json``).

    Columns: WAPE, the share of wells where the method has a lower MAE than repeating the last month, the P10-P90
    coverage and the scaled pinball. Nothing is selected or left out: a cell without a value shows a dash.
    """
    lines: list[str] = []
    for segment in ("eligible", "young"):
        for fluid in ("oil", "gas"):
            rows = summary[(summary["segment"] == segment) & (summary["fluid"] == fluid)]
            if rows.empty:
                continue
            lines += [f"#### {FLUID_ES[fluid].capitalize()}, series {SEGMENT_ES[segment]}", "",
                      "| Método | Horizonte (meses) | Series | WAPE | Pozos donde supera a repetir el último mes | Cobertura P10-P90 | Pinball escalada |",
                      "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
            order = {m: i for i, m in enumerate(METHOD_ORDER)}
            for r in rows.sort_values(by=["method", "horizon"], key=lambda col: col.map(order) if col.name == "method" else col).itertuples(index=False):
                lines.append(
                    f"| `{r.method}` | {int(r.horizon)} | {int(r.n_series)} | {_percent(r.wape)} % | {_share(r.share_beats_naive_last)} | "
                    f"{_decimal(r.coverage)} | {_decimal(r.scaled_pinball, 3)} |"
                )
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
