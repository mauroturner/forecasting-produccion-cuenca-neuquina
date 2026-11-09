"""The fracture ablation (RF21, D15): the same evaluation set for both models, a rule fixed in advance and the report."""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oilgas import ablation
from oilgas.backtest import evaluation_pairs, plan_origins, run_ml
from oilgas.cli import EXIT_OK, EXIT_USAGE, main
from oilgas.config import load_config
from oilgas.fracture import attach_fracture, read_fracture_csv
from oilgas.series import build_panel
from oilgas.warehouse import connect
from tests.fixtures.modeling import small_cfg, write_config
from tests.unit.test_fracture import frac, write_csv


@pytest.fixture(scope="module")
def setup(tmp_path_factory, warehouse_path: Path):
    root = tmp_path_factory.mktemp("ablation")
    cfg = small_cfg(warehouse_path, root / "interim", well_sample=24)  # a sample keeps the suite fast; the real run used every well
    conn = connect(warehouse_path)
    try:
        panel = build_panel(conn, 24, cfg.backtest.seed)
    finally:
        conn.close()
    wells = [int(w) for w in panel.well_ids[::2]]
    rows = [frac(w, f"{2019 + n % 4}-0{1 + n % 9}-28", stages=8 + n, lateral=900 + 40 * n, water=1500 + 100 * n) for n, w in enumerate(wells)]
    table = read_fracture_csv(write_csv(root / "fracture.csv", rows))
    plan = plan_origins(int(panel.period_index[-1]), cfg.backtest)
    return cfg, panel, plan, table, root


@pytest.fixture(scope="module")
def pairs(setup):
    cfg, panel, plan, table, _ = setup
    return ablation.run_fracture_ablation(panel, plan, cfg, table)


def keys(frame: pd.DataFrame) -> list[tuple]:
    cols = ["segment", "fluid", "well_id", "origin", "horizon"]
    return sorted(map(tuple, frame[cols].astype(str).to_numpy().tolist()))


def test_both_models_are_scored_on_exactly_the_same_pairs(pairs) -> None:
    assert set(pairs["method"].astype(str)) == {ablation.CONTROL, ablation.TREATMENT}
    control = pairs[pairs["method"].astype(str) == ablation.CONTROL]
    treatment = pairs[pairs["method"].astype(str) == ablation.TREATMENT]
    assert len(control) == len(treatment) > 0
    assert keys(control) == keys(treatment)
    pd.testing.assert_series_equal(control["actual"].reset_index(drop=True), treatment["actual"].reset_index(drop=True), check_names=False)


def test_the_control_is_the_base_model_unchanged(setup, pairs) -> None:
    cfg, panel, plan, _, _ = setup
    base = evaluation_pairs(run_ml(panel, plan, cfg), plan, cfg.backtest)
    control = pairs[pairs["method"].astype(str) == ablation.CONTROL].sort_values(["fluid", "well_id", "origin", "horizon"]).reset_index(drop=True)
    base = base.sort_values(["fluid", "well_id", "origin", "horizon"]).reset_index(drop=True)
    np.testing.assert_array_equal(control["p50"].to_numpy(), base["p50"].to_numpy())  # the same code, the same seed: not a different baseline


def test_the_treatment_really_sees_the_fracture_data(pairs) -> None:
    control = pairs[pairs["method"].astype(str) == ablation.CONTROL].reset_index(drop=True)
    treatment = pairs[pairs["method"].astype(str) == ablation.TREATMENT].reset_index(drop=True)
    assert not np.array_equal(control["p50"].to_numpy(), treatment["p50"].to_numpy())


def test_the_comparison_has_one_row_per_fluid_horizon_and_segment_with_both_sides(setup, pairs) -> None:
    cfg = setup[0]
    table = ablation.compare(pairs, cfg)
    assert {"fluid", "horizon", "segment", "n_pairs", "n_series", "wape_base", "wape_fracture", "scaled_pinball_base",
            "scaled_pinball_fracture", "pinball_change", "coverage_base", "coverage_fracture", "share_fracture_better"} <= set(table.columns)
    assert not table.duplicated(["fluid", "horizon", "segment"]).any()
    row = table.iloc[0]
    assert row.pinball_change == pytest.approx(row.scaled_pinball_fracture / row.scaled_pinball_base - 1)
    assert 0 <= row.share_fracture_better <= 1
    assert (table["n_pairs"] > 0).all()


def cells(changes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"fluid": "oil", "horizon": range(len(changes)), "segment": "eligible", "pinball_change": changes})


def test_the_rule_adds_the_fracture_data_only_with_a_clear_gain_in_most_cells() -> None:
    gain = ablation.decide(cells([-0.05] * 12 + [0.0] * 4))
    assert gain["add_to_base"] is True and gain["cells_improved"] == 12 and gain["cells_worse"] == 0
    # the preregistered threshold is inclusive: exactly 2 % better counts, 1.9 % does not
    assert ablation.decide(cells([-0.02] * 12 + [0.0] * 4))["cells_improved"] == 12
    assert ablation.decide(cells([-0.019] * 16))["add_to_base"] is False


def test_the_rule_does_not_add_them_if_one_cell_gets_clearly_worse_or_too_few_improve() -> None:
    assert ablation.decide(cells([-0.05] * 15 + [0.03]))["add_to_base"] is False
    assert ablation.decide(cells([-0.05] * 11 + [0.0] * 5))["add_to_base"] is False
    assert ablation.decide(cells([-0.05] * 12 + [0.021] * 4))["add_to_base"] is False
    assert ablation.decide(cells([-0.05] * 12 + [0.02] * 4))["add_to_base"] is True  # "worse" means more than 2 %: exactly 2 % is tolerated


def with_paths(cfg, root: Path, fracture: Path):
    return dataclasses.replace(cfg, paths=dataclasses.replace(cfg.paths, fracture_csv=fracture, reports_dir=root / "reports"))


def test_the_ablation_task_writes_its_report_and_says_what_was_run(setup) -> None:
    cfg, _, _, _, root = setup
    result = ablation.run_ablation(with_paths(cfg, root, root / "fracture.csv"))
    document = json.loads((root / "reports" / "fracture_ablation.json").read_text(encoding="utf-8"))
    assert document["scope"]["wells"] > 0 and document["scope"]["pairs"] == result["pairs"] > 0
    assert document["decision"]["rule"] == ablation.DECISION_RULE
    assert document["decision"]["add_to_base"] is result["add_to_base"]
    text = (root / "reports" / "fracture_ablation.md").read_text(encoding="utf-8")
    assert "Regla fijada de antemano" in text and ("no se suman" in text) == (not result["add_to_base"])


def test_a_missing_fracture_file_is_reported_before_any_work(setup) -> None:
    cfg, _, _, _, root = setup
    with pytest.raises(FileNotFoundError, match="fracture"):
        ablation.run_ablation(with_paths(cfg, root, root / "fracture-missing.csv"))


def test_the_command_runs_the_ablation_and_a_missing_file_exits_with_two(setup, capsys) -> None:
    cfg, _, _, _, root = setup
    config = write_config(root / "cli", Path(cfg.paths.warehouse), well_sample=0)  # the source file is not read by this command
    text = config.read_text(encoding="utf-8")
    config.write_text(text + f'fracture_csv = "{(root / "fracture.csv").as_posix()}"\n', encoding="utf-8")
    (root / "cli" / "data/warehouse").mkdir(parents=True, exist_ok=True)
    shutil.copy(cfg.paths.warehouse, root / "cli" / "data/warehouse/production.sqlite")
    assert main(["ablation-fracture", "--config", str(config), "--wells", "20"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "fracture_ablation" in out and (root / "cli" / "reports" / "fracture_ablation.json").exists()
    bad = config.read_text(encoding="utf-8").replace("fracture.csv", "nope.csv")
    config.write_text(bad, encoding="utf-8")
    assert main(["ablation-fracture", "--config", str(config)]) == EXIT_USAGE
    assert "does not exist" in capsys.readouterr().err


def test_the_option_puts_the_fracture_arrays_in_the_panel_of_the_model_tasks_and_is_off_by_default(setup) -> None:
    from oilgas.fracture import model_panel

    cfg, _, _, _, root = setup
    conn = connect(cfg.paths.warehouse)
    try:
        assert model_panel(conn, cfg).fracture is None  # the base model never sees fracture data
        on = dataclasses.replace(with_paths(cfg, root, root / "fracture.csv"), ml=dataclasses.replace(cfg.ml, fracture_features=True))
        assert set(model_panel(conn, on).fracture) == {"frac_stages", "frac_lateral_m", "frac_sand_t", "frac_water_m3", "frac_months_since"}
        missing = dataclasses.replace(on, paths=dataclasses.replace(on.paths, fracture_csv=root / "none.csv"))
        with pytest.raises(FileNotFoundError, match="fracture"):
            model_panel(conn, missing)
    finally:
        conn.close()


def test_the_backtest_task_uses_the_fracture_features_only_when_the_option_is_on(setup, tmp_path: Path) -> None:
    from oilgas.backtest import run_backtest
    from tests.fixtures.modeling import RunCtx

    cfg, _, _, _, root = setup
    on = dataclasses.replace(with_paths(cfg, root, root / "fracture.csv"), ml=dataclasses.replace(cfg.ml, fracture_features=True))
    results = {}
    for name, config in (("off", cfg), ("on", on)):
        work = tmp_path / name
        work.mkdir()
        copy = work / "production.sqlite"
        shutil.copy(cfg.paths.warehouse, copy)
        config = dataclasses.replace(config, paths=dataclasses.replace(config.paths, warehouse=copy, interim_dir=work / "interim"),
                                     backtest=dataclasses.replace(config.backtest, well_sample=20))
        run_backtest(RunCtx(config, "k"))
        results[name] = pd.read_parquet(work / "interim" / "backtest" / "ml_forecasts.parquet")
    assert len(results["off"]) == len(results["on"]) > 0
    assert not np.array_equal(results["off"]["p50"].to_numpy(), results["on"]["p50"].to_numpy())
