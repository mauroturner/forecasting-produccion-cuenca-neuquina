"""The outputs of the real run that are versioned in the repository keep their contracts (AC13, AC17, AC21, RNF09).

They are plain files, so these tests run by default: they read what the run of 2026-11-09 left in ``outputs/``,
``reports/`` and ``dashboard/`` and fail if someone commits a file that breaks a contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from oilgas.config import load_config
from oilgas.dashboard.semantic_model import MODEL
from oilgas.export import MAX_PARQUET_BYTES, verify_star_schema

METHODS = {"naive_last", "naive_mean3", "arps_exp", "arps_mh_b1", "arps_mh_b2", "ml_hgb"}
HORIZONS = {1, 3, 6, 12}


@pytest.fixture(scope="module")
def summary(project_root: Path) -> pd.DataFrame:
    document = json.loads((project_root / "reports" / "backtest_summary.json").read_text(encoding="utf-8"))
    return pd.DataFrame(document["summary"])


def test_the_star_schema_files_keep_the_contract_and_the_size_limit(project_root: Path) -> None:
    out = project_root / "outputs" / "powerbi"
    assert verify_star_schema(out, MODEL) == []
    files = sorted(out.glob("*.parquet"))
    assert {f.stem for f in files} == {t.name for t in MODEL.tables}
    assert all(f.stat().st_size <= MAX_PARQUET_BYTES for f in files)  # AC21, RNF09


def test_the_dashboard_design_is_one_small_file_made_from_the_full_run(project_root: Path) -> None:
    html = (project_root / "dashboard" / "powerbi-design.html").read_text(encoding="utf-8")
    assert len(html.encode("utf-8")) < 2 * 1024 * 1024
    assert "de 4937" in html and "Datos hasta <b>2026-09</b>" in html  # the 4,937 wells of the real publication, not a sample


def test_every_method_fluid_and_horizon_is_in_the_summary_over_the_same_pairs(summary: pd.DataFrame) -> None:
    eligible = summary[summary["segment"] == "eligible"]
    assert set(eligible["method"]) == METHODS and set(eligible["fluid"]) == {"oil", "gas"} and set(eligible["horizon"]) == HORIZONS
    assert len(eligible) == len(METHODS) * 2 * len(HORIZONS)
    young = summary[summary["segment"] == "young"]
    assert set(young["method"]) == {"naive_last", "naive_mean3", "ml_hgb"}
    assert (summary.groupby(["segment", "fluid", "horizon"])["n_points"].nunique() == 1).all()  # AC13: the same pairs for every method


def test_the_arps_fallback_rate_is_under_the_limit(summary: pd.DataFrame, project_root: Path) -> None:
    limit = load_config().criteria.max_fallback_rate
    arps = summary[summary["method"].str.startswith("arps")]
    assert arps["fallback_rate"].max() < limit


def test_the_thresholds_of_the_summary_are_the_preregistered_ones(project_root: Path) -> None:
    document = json.loads((project_root / "reports" / "backtest_summary.json").read_text(encoding="utf-8"))
    thresholds = document["criteria"]["thresholds"]
    criteria = load_config().criteria
    assert thresholds["share_beats_naive_min"] == criteria.share_beats_naive_min == 0.60
    assert thresholds["coverage_target"] == criteria.coverage_target == 0.80
    assert thresholds["coverage_acceptable"] == list(criteria.coverage_acceptable) == [0.70, 0.90]
    assert thresholds["share_beats_horizon"] == criteria.share_beats_horizon == 12


def test_the_versioned_ablation_report_follows_its_own_rule(project_root: Path) -> None:
    """The decision about the fracture data is the preregistered rule applied to the cells of the report, and the Markdown is that report."""
    from oilgas import ablation

    document = json.loads((project_root / "reports" / "fracture_ablation.json").read_text(encoding="utf-8"))
    comparison = pd.DataFrame(document["comparison"])
    assert len(comparison) == 16 and document["scope"]["wells"] == 4937
    assert document["decision"] == ablation.decide(comparison)  # nobody edited the verdict by hand
    assert document["decision"]["rule"] == ablation.DECISION_RULE
    expected = ablation.render_markdown(comparison, document["decision"], document["scope"])
    assert (project_root / "reports" / "fracture_ablation.md").read_text(encoding="utf-8") == expected
