"""Ablation of the fracture features on the machine-learning model (RF21, decision D15).

The same ``ml_hgb`` runs twice over the same walk-forward origins and series: once as in the base model
(``ml_hgb``) and once with the fracture features of ``fracture.py`` (``ml_hgb_fracture``). Both are scored
on exactly the same (series, origin, horizon) pairs, with the same metrics as the main backtest. The rule
that decides whether the fracture data enters the base model was fixed before the run and lives in
``DECISION_RULE``; nothing here is tuned after seeing the result.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from oilgas.backtest import evaluation_pairs, plan_origins, run_ml
from oilgas.config import PipelineConfig
from oilgas.files import write_atomic
from oilgas.fracture import FractureTable, attach_fracture, read_fracture_csv
from oilgas.metrics import coverage, scaled_pinball, share_beats, wape
from oilgas.series import SeriesPanel, build_panel
from oilgas.warehouse import connect

CONTROL = "ml_hgb"
TREATMENT = "ml_hgb_fracture"
MIN_GAIN = 0.02  # a cell improves if the scaled pinball falls by at least 2 % (relative)
MAX_WORSE = 0.02  # and it worsens if it rises by more than 2 %
MIN_SHARE_IMPROVED = 0.75  # the fracture data enter the base if at least 3 of every 4 cells improve and none worsens
DECISION_RULE = (
    "Los datos de fractura se suman al modelo base solo si la pinball escalada del machine learning con ellos es menor, "
    "por al menos 2 % relativo, en al menos 3 de cada 4 celdas (fluido, horizonte y segmento) y no empeora más de 2 % en ninguna."
)
GROUP = ["fluid", "horizon", "segment"]
COLUMNS = [
    *GROUP, "n_pairs", "n_series", "wape_base", "wape_fracture", "scaled_pinball_base", "scaled_pinball_fracture",
    "pinball_change", "coverage_base", "coverage_fracture", "share_fracture_better",
]
FLUID_ES = {"oil": "Petróleo", "gas": "Gas"}
SEGMENT_ES = {"eligible": "elegibles", "young": "jóvenes"}


def run_fracture_ablation(panel: SeriesPanel, plan, cfg: PipelineConfig, table: FractureTable) -> pd.DataFrame:
    """Evaluation pairs of the base model and of the model with fracture features, long format, two methods."""
    runs = []
    for method, source in ((CONTROL, panel), (TREATMENT, attach_fracture(panel, table))):
        forecasts = run_ml(source, plan, cfg)
        forecasts["method"] = method
        runs.append(forecasts)
    return evaluation_pairs(pd.concat(runs, ignore_index=True), plan, cfg.backtest)


def _metrics(group: pd.DataFrame) -> dict:
    y, p10, p50, p90 = (group[c].to_numpy(dtype=np.float64) for c in ("actual", "p10", "p50", "p90"))
    return {"wape": wape(y, p50), "pinball": scaled_pinball(y, p10, p50, p90), "coverage": coverage(y, p10, p90)}


def compare(pairs: pd.DataFrame, cfg: PipelineConfig) -> pd.DataFrame:
    """One row per fluid, horizon and segment with both models' metrics and the share of series where the fracture one is better."""
    frame = pairs.copy()
    for column in ("fluid", "method", "segment"):
        frame[column] = frame[column].astype(str)
    for column in ("horizon", "well_id", "origin"):
        frame[column] = frame[column].astype(np.int64)
    shares = share_beats(frame, TREATMENT, CONTROL, by=GROUP).set_index(GROUP)["share"]
    rows = []
    for key, group in frame.groupby(GROUP, sort=True):
        base = group[group["method"] == CONTROL]
        treated = group[group["method"] == TREATMENT]
        b, t = _metrics(base), _metrics(treated)
        rows.append({
            "fluid": key[0], "horizon": int(key[1]), "segment": key[2], "n_pairs": int(len(base)), "n_series": int(base["well_id"].nunique()),
            "wape_base": b["wape"], "wape_fracture": t["wape"], "scaled_pinball_base": b["pinball"], "scaled_pinball_fracture": t["pinball"],
            "pinball_change": t["pinball"] / b["pinball"] - 1, "coverage_base": b["coverage"], "coverage_fracture": t["coverage"],
            "share_fracture_better": float(shares.get(key, np.nan)),
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def decide(comparison: pd.DataFrame) -> dict:
    """Apply the preregistered rule to the cells of the comparison."""
    changes = comparison["pinball_change"].dropna().to_numpy(dtype=np.float64)
    cells = int(len(changes))
    improved = int((changes <= -MIN_GAIN).sum())
    worse = int((changes > MAX_WORSE).sum())
    needed = math.ceil(MIN_SHARE_IMPROVED * cells)
    return {
        "add_to_base": bool(cells > 0 and improved >= needed and worse == 0),
        "cells": cells, "cells_improved": improved, "cells_worse": worse, "cells_needed": needed,
        "mean_pinball_change": float(changes.mean()) if cells else None, "rule": DECISION_RULE,
    }


def _pct(value: float) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value * 100:.1f}".replace(".", ",") + " %"


def _n(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _d(value: float) -> str:
    return f"{value:.4f}".replace(".", ",")


def render_markdown(comparison: pd.DataFrame, decision: dict, scope: dict) -> str:
    worse = "ninguna empeora más de 2 %" if decision["cells_worse"] == 0 else f"{decision['cells_worse']} empeoran más de 2 %"
    verdict = "se suman al modelo base" if decision["add_to_base"] else "no se suman al modelo base"
    lines = [
        "# Ablación con datos de fractura", "",
        f"Se corrió el machine learning sin y con variables de fractura sobre los mismos pares: {_n(scope['wells'])} pozos, "
        f"{scope['eval_origins']} orígenes de evaluación, {_n(scope['pairs'])} pares evaluados por modelo.", "",
        f"**Regla fijada de antemano.** {decision['rule']}", "",
        f"**Resultado.** Mejoran {decision['cells_improved']} de {decision['cells']} celdas (hacían falta {decision['cells_needed']}) y "
        f"{worse}; el cambio medio de la pinball escalada es {_pct(decision['mean_pinball_change'])}. "
        f"Los datos de fractura {verdict}.", "",
        "| Fluido | Horizonte | Series | Pares | WAPE sin | WAPE con | Pinball sin | Pinball con | Cambio | Cobertura sin | Cobertura con | Pozos donde mejora |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in comparison.itertuples(index=False):
        lines.append(
            f"| {FLUID_ES[r.fluid]} | {r.horizon} | {SEGMENT_ES.get(r.segment, r.segment)} | {_n(r.n_pairs)} | {_pct(r.wape_base)} | {_pct(r.wape_fracture)} | "
            f"{_d(r.scaled_pinball_base)} | {_d(r.scaled_pinball_fracture)} | {_pct(r.pinball_change)} | {_pct(r.coverage_base)} | {_pct(r.coverage_fracture)} | {_pct(r.share_fracture_better)} |"
        )
    return "\n".join(lines) + "\n"


def write_ablation(comparison: pd.DataFrame, decision: dict, scope: dict, reports_dir: Path) -> tuple[Path, Path]:
    """Write ``fracture_ablation.json`` and ``.md`` atomically."""
    reports_dir = Path(reports_dir)
    records = [{k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in row.items()} for row in comparison.to_dict("records")]
    document = {"scope": scope, "decision": decision, "comparison": records}
    json_path = write_atomic(reports_dir / "fracture_ablation.json", json.dumps(document, indent=2, ensure_ascii=False, default=float) + "\n")
    md_path = write_atomic(reports_dir / "fracture_ablation.md", render_markdown(comparison, decision, scope))
    return json_path, md_path


def run_ablation(cfg: PipelineConfig, wells: int | None = None) -> dict:
    """The ablation on the warehouse of the last run: `wells` > 0 draws a fixed sample of wells (seed of the backtest)."""
    fracture_csv, warehouse = Path(cfg.paths.fracture_csv), Path(cfg.paths.warehouse)
    for path in (fracture_csv, warehouse):
        if not path.exists():
            raise FileNotFoundError(f"{path} does not exist" + (": run the pipeline first (python -m oilgas run)" if path == warehouse else ""))
    started = time.perf_counter()
    conn = connect(warehouse)
    try:
        panel = build_panel(conn, cfg.backtest.well_sample if wells is None else wells, cfg.backtest.seed)
    finally:
        conn.close()
    plan = plan_origins(int(panel.period_index[-1]), cfg.backtest)
    table = read_fracture_csv(fracture_csv)
    pairs = run_fracture_ablation(panel, plan, cfg, table)
    comparison = compare(pairs, cfg)
    decision = decide(comparison)
    covered = int(np.isin(panel.well_ids, table.well_id).sum())
    scope = {
        "wells": int(len(panel.well_ids)), "wells_with_fracture_rows": covered, "fracture_rows": int(len(table.well_id)),
        "fracture_rows_dropped_without_end_date": table.rows_dropped, "eval_origins": len(plan.eval_origins),
        "pairs": int(len(pairs) // 2), "seconds": round(time.perf_counter() - started, 1),
    }
    json_path, md_path = write_ablation(comparison, decision, scope, cfg.paths.reports_dir)
    return {**scope, "add_to_base": decision["add_to_base"], "cells_improved": decision["cells_improved"], "cells": decision["cells"],
            "json": str(json_path), "markdown": str(md_path)}
