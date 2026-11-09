"""Summary, preregistered criteria, method selection and the results block (RF13-RF15, AC14-AC16)."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oilgas.config import load_config
from oilgas.reporting import (
    SUMMARY_COLUMNS,
    coverage_verdict,
    evaluate_criteria,
    read_selection,
    read_summary,
    render_results_markdown,
    select_methods,
    store_summary,
    summarize,
    sync_block,
    write_summary,
)
from oilgas.warehouse import apply_schema, connect

CFG = load_config()
CRIT = CFG.criteria


def pair(method: str, well: int, origin: int, actual: float, p50: float, band: tuple[float, float] | None = None,
         *, fluid: str = "oil", horizon: int = 12, segment: str = "eligible", status: str = "ok") -> dict:
    low, high = band if band is not None else (p50 * 0.8, p50 * 1.2)
    return {
        "fluid": fluid, "well_id": well, "origin": origin, "horizon": horizon, "method": method, "segment": segment,
        "age_bucket": "24-59" if segment == "eligible" else "young", "n_post_peak": 30, "target_days": 30,
        "actual": actual, "p10": low, "p50": p50, "p90": high, "fit_status": status,
    }


@pytest.fixture()
def small() -> pd.DataFrame:
    """Two wells, two origins, one fluid and horizon: numbers small enough to check by hand."""
    actual = {(1, 1): 100.0, (1, 2): 100.0, (2, 1): 200.0, (2, 2): 200.0}
    naive = {(1, 1): 90.0, (1, 2): 130.0, (2, 1): 250.0, (2, 2): 150.0}  # abs errors 10, 30, 50, 50
    arps = {(1, 1): 95.0, (1, 2): 105.0, (2, 1): 150.0, (2, 2): 270.0}  # abs errors 5, 5, 50, 70
    rows = []
    for (well, origin), y in actual.items():
        rows.append(pair("naive_last", well, origin, y, naive[well, origin]))
        status = "fallback_exp" if (well, origin) == (2, 1) else "ok"
        rows.append(pair("arps_mh_b2", well, origin, y, arps[well, origin], (arps[well, origin] * 0.9, arps[well, origin] * 1.1), status=status))
    return pd.DataFrame(rows)


def row_of(summary: pd.DataFrame, method: str, fluid: str = "oil", horizon: int = 12, segment: str = "eligible") -> pd.Series:
    hit = summary[(summary["method"] == method) & (summary["fluid"] == fluid) & (summary["horizon"] == horizon) & (summary["segment"] == segment)]
    assert len(hit) == 1, (method, fluid, horizon, segment)
    return hit.iloc[0]


# --- summarize ----------------------------------------------------------------------------------------------


def test_the_summary_has_the_columns_of_the_model_summary_table() -> None:
    assert SUMMARY_COLUMNS == [
        "method", "fluid", "horizon", "segment", "n_series", "n_points", "mae", "rmse", "wape", "bias", "coverage",
        "scaled_pinball", "share_beats_naive_last", "share_beats_naive_mean3", "fallback_rate", "basin_band_coverage",
        "coverage_verdict", "verdict_es",
    ]


def test_summarize_computes_every_metric_of_a_cell_by_hand(small: pd.DataFrame) -> None:
    summary = summarize(small, CFG)
    assert list(summary.columns) == SUMMARY_COLUMNS and len(summary) == 2
    naive = row_of(summary, "naive_last")
    assert (naive["n_series"], naive["n_points"]) == (2, 4)
    assert naive["mae"] == pytest.approx(35.0)
    assert naive["rmse"] == pytest.approx(math.sqrt(1500.0))
    assert naive["wape"] == pytest.approx(140.0 / 600.0)
    assert naive["bias"] == pytest.approx(20.0 / 600.0)
    assert naive["coverage"] == pytest.approx(0.5)  # [72, 108] yes, [104, 156] no, [200, 300] yes (edge), [120, 180] no
    y, q = small[small["method"] == "naive_last"], None
    pinball = sum(
        np.maximum(a * (y["actual"] - y[c]), (a - 1) * (y["actual"] - y[c])).sum() for a, c in ((0.1, "p10"), (0.5, "p50"), (0.9, "p90"))
    )
    assert naive["scaled_pinball"] == pytest.approx(pinball / 600.0)
    arps = row_of(summary, "arps_mh_b2")
    assert arps["mae"] == pytest.approx(32.5) and arps["wape"] == pytest.approx(130.0 / 600.0)
    assert arps["bias"] == pytest.approx((95 + 105 + 150 + 270 - 600) / 600.0)
    assert arps["coverage"] == pytest.approx(0.5)  # [85.5, 104.5] and [94.5, 115.5] hold their 100; [135, 165] and [243, 297] miss 200


def test_share_of_series_that_beat_a_baseline_is_by_series_and_never_against_itself(small: pd.DataFrame) -> None:
    summary = summarize(small, CFG)
    arps = row_of(summary, "arps_mh_b2")
    # well 1: arps MAE 5 < naive 20; well 2: arps MAE 60 > naive 50
    assert arps["share_beats_naive_last"] == pytest.approx(0.5)
    assert math.isnan(arps["share_beats_naive_mean3"])  # that baseline is not in the frame
    naive = row_of(summary, "naive_last")
    assert math.isnan(naive["share_beats_naive_last"])


def test_the_fallback_rate_counts_fits_not_horizons_and_only_for_arps(small: pd.DataFrame) -> None:
    doubled = pd.concat([small, small.assign(horizon=6)], ignore_index=True)  # same fits, a second horizon
    summary = summarize(doubled, CFG)
    for horizon in (6, 12):
        assert row_of(summary, "arps_mh_b2", horizon=horizon)["fallback_rate"] == pytest.approx(0.25)  # 1 of 4 fits
        assert math.isnan(row_of(summary, "naive_last", horizon=horizon)["fallback_rate"])


def test_basin_band_coverage_is_the_share_of_origins_whose_total_falls_inside_the_summed_bands(small: pd.DataFrame) -> None:
    summary = summarize(small, CFG)
    # naive: origin 1 total 300 in [272, 408]; origin 2 total 300 in [224, 336]
    assert row_of(summary, "naive_last")["basin_band_coverage"] == pytest.approx(1.0)
    # arps bands are +-10 %: origin 1 sums p50 = 245 -> [220.5, 269.5], origin 2 sums p50 = 375 -> [337.5, 412.5]; 300 is outside both
    assert row_of(summary, "arps_mh_b2")["basin_band_coverage"] == pytest.approx(0.0)


def test_cells_are_split_by_fluid_horizon_and_segment(small: pd.DataFrame) -> None:
    young = pd.DataFrame([pair("naive_last", 9, 1, 10.0, 12.0, segment="young", fluid="gas", horizon=1)])
    summary = summarize(pd.concat([small, young], ignore_index=True), CFG)
    assert len(summary) == 3
    only = row_of(summary, "naive_last", fluid="gas", horizon=1, segment="young")
    assert (only["n_series"], only["n_points"]) == (1, 1)


def test_summarize_accepts_the_categorical_frame_the_backtest_produces(small: pd.DataFrame) -> None:
    frame = small.copy()
    for column in ("fluid", "method", "segment", "age_bucket", "fit_status"):
        frame[column] = frame[column].astype("category")
    pd.testing.assert_frame_equal(summarize(frame, CFG), summarize(small, CFG))


def test_summarize_of_nothing_is_an_empty_summary() -> None:
    summary = summarize(pd.DataFrame(columns=list(pair("naive_last", 1, 1, 1.0, 1.0))), CFG)
    assert summary.empty and list(summary.columns) == SUMMARY_COLUMNS


# --- coverage verdict (AC15) --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "verdict"),
    [(0.80, "calibrado"), (0.75, "calibrado"), (0.85, "calibrado"), (0.7499, "aceptable"), (0.85001, "aceptable"),
     (0.70, "aceptable"), (0.90, "aceptable"), (0.6999, "descalibrado"), (0.9001, "descalibrado"), (0.0, "descalibrado")],
)
def test_coverage_is_classified_with_the_preregistered_ranges(value: float, verdict: str) -> None:
    assert coverage_verdict(value, CRIT) == verdict


def test_a_coverage_that_does_not_exist_has_no_verdict() -> None:
    assert coverage_verdict(float("nan"), CRIT) is None


def test_every_row_carries_the_verdict_that_matches_its_number(small: pd.DataFrame) -> None:
    summary = summarize(small, CFG)
    for _, row in summary.iterrows():
        assert row["coverage_verdict"] == coverage_verdict(row["coverage"], CRIT)
        assert row["coverage_verdict"] in row["verdict_es"] and f"{row['coverage']:.2f}".replace(".", ",") in row["verdict_es"]


# --- criteria (AC14, AC15, AC16) -----------------------------------------------------------------------------


def make_summary(cells: dict) -> pd.DataFrame:
    """A summary with one row per (method, fluid, horizon, segment) given; unset metrics are NaN."""
    rows = []
    for (method, fluid, horizon, segment), values in cells.items():
        base = dict.fromkeys(SUMMARY_COLUMNS, float("nan"))
        base.update(method=method, fluid=fluid, horizon=horizon, segment=segment, n_series=100, n_points=1000)
        base.update(values)
        base["coverage_verdict"] = coverage_verdict(base["coverage"], CRIT)
        base["verdict_es"] = ""
        rows.append(base)
    return pd.DataFrame(rows)[SUMMARY_COLUMNS]


def favorable(share: float = 0.64, wape6: float = 0.30, wape12: float = 0.40) -> dict:
    """Oil cells that pass AC14: Arps beats repeating the last month on share and WAPE."""
    return {
        ("arps_mh_b2", "oil", 12, "eligible"): dict(share_beats_naive_last=share, wape=wape12, coverage=0.72, scaled_pinball=0.5, fallback_rate=0.004),
        ("naive_last", "oil", 12, "eligible"): dict(wape=0.50, coverage=0.60, scaled_pinball=0.7),
        ("arps_mh_b2", "oil", 6, "eligible"): dict(share_beats_naive_last=0.7, wape=wape6, coverage=0.83, scaled_pinball=0.4, fallback_rate=0.004),
        ("naive_last", "oil", 6, "eligible"): dict(wape=0.35, coverage=0.60, scaled_pinball=0.6),
    }


def test_a_favorable_summary_passes_ac14_with_the_preregistered_wording() -> None:
    criteria = evaluate_criteria(make_summary(favorable()), CRIT)
    oil = criteria["AC14"]["oil"]
    assert oil["passed"] is True and oil["share_passed"] is True and oil["wape_passed"] is True
    assert oil["share_beats_naive_last"] == pytest.approx(0.64)
    assert "A 12 meses, la curva de Arps supera a repetir el último mes en el 64 % de los pozos (umbral: 60 %)." in oil["verdict_es"]
    assert [w["horizon"] for w in oil["wape"]] == [6, 12] and all(w["passed"] for w in oil["wape"])
    assert criteria["thresholds"]["share_beats_naive_min"] == 0.60


def test_an_unfavorable_share_says_it_does_not_beat_the_baseline() -> None:
    criteria = evaluate_criteria(make_summary(favorable(share=0.48)), CRIT)
    oil = criteria["AC14"]["oil"]
    assert oil["passed"] is False and oil["share_passed"] is False and oil["wape_passed"] is True
    assert "A 12 meses, la curva de Arps no supera a repetir el último mes: lo hace en el 48 % de los pozos (umbral: 60 %)." in oil["verdict_es"]


def test_the_share_threshold_is_inclusive() -> None:
    assert evaluate_criteria(make_summary(favorable(share=0.60)), CRIT)["AC14"]["oil"]["share_passed"] is True
    assert evaluate_criteria(make_summary(favorable(share=0.5999)), CRIT)["AC14"]["oil"]["share_passed"] is False


def test_a_wape_that_is_not_lower_fails_ac14_even_when_the_share_passes() -> None:
    criteria = evaluate_criteria(make_summary(favorable(wape6=0.35)), CRIT)  # equal to the baseline at 6 months: not lower
    oil = criteria["AC14"]["oil"]
    assert oil["share_passed"] is True and oil["wape_passed"] is False and oil["passed"] is False
    assert [w["passed"] for w in oil["wape"]] == [False, True]
    assert any("no supera" in sentence and "6 meses" in sentence and "WAPE" in sentence for sentence in oil["verdict_es"])


def test_a_fluid_without_data_fails_instead_of_passing_silently() -> None:
    criteria = evaluate_criteria(make_summary(favorable()), CRIT)
    gas = criteria["AC14"]["gas"]
    assert gas["passed"] is False and gas["share_beats_naive_last"] is None
    assert any("sin datos" in sentence.lower() for sentence in gas["verdict_es"])


def test_ac15_labels_each_method_and_horizon_with_the_word_that_matches_its_coverage() -> None:
    cells = favorable()
    cells[("ml_hgb", "oil", 12, "eligible")] = dict(coverage=0.62, scaled_pinball=0.45)
    criteria = evaluate_criteria(make_summary(cells), CRIT)
    by_key = {(c["fluid"], c["horizon"], c["method"]): c for c in criteria["AC15"]}
    assert by_key["oil", 12, "arps_mh_b2"]["verdict"] == "aceptable" and by_key["oil", 12, "arps_mh_b2"]["coverage"] == pytest.approx(0.72)
    assert by_key["oil", 6, "arps_mh_b2"]["verdict"] == "calibrado"
    assert by_key["oil", 12, "ml_hgb"]["verdict"] == "descalibrado"
    for c in by_key.values():
        assert c["verdict"] in c["verdict_es"] and f"{c['coverage']:.2f}".replace(".", ",") in c["verdict_es"]
    assert ("oil", 12, "naive_last") not in by_key  # only the two methods of AC15


def test_ac16_reports_whether_machine_learning_adds_something_on_each_segment() -> None:
    cells = favorable()
    cells[("ml_hgb", "oil", 12, "eligible")] = dict(coverage=0.8, scaled_pinball=0.45)  # arps has 0.5: ml better
    cells[("ml_hgb", "oil", 6, "eligible")] = dict(coverage=0.8, scaled_pinball=0.55)  # arps has 0.4: ml worse
    cells[("ml_hgb", "oil", 12, "young")] = dict(coverage=0.8, scaled_pinball=0.9)
    cells[("naive_mean3", "oil", 12, "young")] = dict(coverage=0.7, scaled_pinball=0.8)
    criteria = evaluate_criteria(make_summary(cells), CRIT)
    by_key = {(c["fluid"], c["horizon"], c["segment"]): c for c in criteria["AC16"]}
    better = by_key["oil", 12, "eligible"]
    assert better["ml_better"] is True and (better["baseline"], better["ml_pinball"], better["baseline_pinball"]) == ("arps_mh_b2", 0.45, 0.5)
    assert "supera" in better["verdict_es"] and "no supera" not in better["verdict_es"]
    worse = by_key["oil", 6, "eligible"]
    assert worse["ml_better"] is False and "no supera" in worse["verdict_es"]
    young = by_key["oil", 12, "young"]
    assert young["baseline"] == "naive_mean3" and young["ml_better"] is False and "no supera" in young["verdict_es"]


def test_the_fallback_rate_of_each_arps_method_is_checked_against_the_maximum() -> None:
    cells = favorable()
    cells[("arps_mh_b2", "oil", 12, "eligible")]["fallback_rate"] = 0.03
    criteria = evaluate_criteria(make_summary(cells), CRIT)
    fallback = {(f["fluid"], f["method"]): f for f in criteria["fallback"]}
    entry = fallback["oil", "arps_mh_b2"]
    assert entry["rate"] == pytest.approx(0.03) and entry["passed"] is False and entry["threshold"] == 0.02
    assert "supera el máximo" in entry["verdict_es"]


# --- method selection (RF15, D11) -----------------------------------------------------------------------------


def pinballs(**by_method: list[float]) -> list[tuple]:
    return [(m, "oil", h, "eligible", v) for m, values in by_method.items() for h, v in zip((1, 3, 6, 12), values, strict=True)]


def selection_summary(rows: list[tuple]) -> pd.DataFrame:
    return make_summary({(m, f, h, s): dict(scaled_pinball=v, coverage=0.8) for m, f, h, s, v in rows})


def test_the_method_with_the_lowest_mean_pinball_over_the_horizons_is_selected() -> None:
    rows = pinballs(arps_mh_b2=[0.5, 0.5, 0.5, 0.5], ml_hgb=[0.4, 0.4, 0.6, 0.7], naive_mean3=[0.9, 0.9, 0.9, 0.9])
    chosen = select_methods(selection_summary(rows))
    assert len(chosen) == 1
    row = chosen.iloc[0]
    assert (row["fluid"], row["segment"], row["method"]) == ("oil", "eligible", "arps_mh_b2")  # 0.5 against ml 0.525
    assert row["criterion_value"] == pytest.approx(0.5) and "pinball" in row["rule"]
    assert list(chosen.columns) == ["fluid", "segment", "method", "criterion_value", "rule"]


@pytest.mark.parametrize(
    ("tied", "winner"),
    [(("arps_mh_b2", "ml_hgb", "naive_mean3"), "naive_mean3"), (("arps_mh_b2", "ml_hgb"), "arps_mh_b2")],
)
def test_a_tie_goes_to_the_simplest_method(tied: tuple[str, ...], winner: str) -> None:
    rows = pinballs(**{m: [0.5, 0.5, 0.5, 0.5] for m in tied})
    assert select_methods(selection_summary(rows)).iloc[0]["method"] == winner


def test_young_series_choose_between_machine_learning_and_the_average_only() -> None:
    rows = [(m, "gas", h, "young", v) for m, vals in (("ml_hgb", [0.3] * 4), ("arps_mh_b2", [0.1] * 4), ("naive_mean3", [0.6] * 4))
            for h, v in zip((1, 3, 6, 12), vals, strict=True)]
    chosen = select_methods(selection_summary(rows))
    assert chosen.iloc[0]["method"] == "ml_hgb"  # Arps is not a candidate for a young series even if it appears better


def test_selection_is_per_fluid_and_segment_and_skips_a_cell_without_candidates() -> None:
    rows = pinballs(arps_mh_b2=[0.5] * 4, naive_mean3=[0.6] * 4)
    rows += [("ml_hgb", "gas", h, "eligible", 0.2) for h in (1, 3, 6, 12)]
    rows += [("naive_last", "gas", 1, "young", 0.1)]  # naive_last is never a candidate
    chosen = select_methods(selection_summary(rows)).set_index(["fluid", "segment"])["method"].to_dict()
    assert chosen == {("oil", "eligible"): "arps_mh_b2", ("gas", "eligible"): "ml_hgb"}


def test_a_candidate_missing_a_horizon_is_averaged_over_the_horizons_it_has() -> None:
    rows = pinballs(arps_mh_b2=[0.5, 0.5, 0.5, 0.5], naive_mean3=[0.4, 0.4, 0.4, float("nan")])
    chosen = select_methods(selection_summary(rows)).iloc[0]
    assert chosen["method"] == "naive_mean3" and chosen["criterion_value"] == pytest.approx(0.4)


# --- results block and files ---------------------------------------------------------------------------------


def test_the_markdown_states_every_verdict_including_the_unfavorable_ones() -> None:
    cells = favorable(share=0.48, wape6=0.35)
    summary = make_summary(cells)
    text = render_results_markdown(evaluate_criteria(summary, CRIT), summary)
    assert "no supera a repetir el último mes: lo hace en el 48 % de los pozos (umbral: 60 %)" in text
    assert "no supera" in text and "WAPE" in text
    assert "Petróleo" in text and "Gas" in text
    assert "sin datos" in text.lower()  # gas has no cells
    assert text.endswith("\n") and "arps_mh_b2" in text


def test_the_markdown_is_the_same_every_time(small: pd.DataFrame) -> None:
    summary = summarize(small, CFG)
    criteria = evaluate_criteria(summary, CRIT)
    assert render_results_markdown(criteria, summary) == render_results_markdown(criteria, summary)


def test_write_summary_writes_json_and_markdown_that_agree(small: pd.DataFrame, tmp_path: Path) -> None:
    summary = summarize(small, CFG)
    criteria = evaluate_criteria(summary, CRIT)
    json_path, md_path = write_summary(criteria, summary, tmp_path / "reports")
    assert (json_path.name, md_path.name) == ("backtest_summary.json", "backtest_summary.md")
    document = json.loads(json_path.read_text(encoding="utf-8"))
    assert document["criteria"]["AC14"]["oil"]["passed"] == criteria["AC14"]["oil"]["passed"]
    assert len(document["summary"]) == len(summary) and "NaN" not in json_path.read_text(encoding="utf-8")
    arps = next(r for r in document["summary"] if r["method"] == "arps_mh_b2")
    assert arps["wape"] == pytest.approx(130.0 / 600.0) and arps["share_beats_naive_mean3"] is None
    assert md_path.read_text(encoding="utf-8") == render_results_markdown(criteria, summary)
    assert sorted(p.name for p in json_path.parent.iterdir()) == ["backtest_summary.json", "backtest_summary.md"]
    again = write_summary(criteria, summary, tmp_path / "other")
    assert again[0].read_bytes() == json_path.read_bytes() and again[1].read_bytes() == md_path.read_bytes()


# --- sync_block ----------------------------------------------------------------------------------------------


START, END = "<!-- results:start -->", "<!-- results:end -->"


def readme(body: str = "old") -> str:
    return f"# Title\n\nbefore\n\n{START}\n{body}\n{END}\n\nafter\n"


def test_sync_block_replaces_only_what_is_between_the_markers(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_bytes(readme().encode())
    assert sync_block(path, START, END, "### New\n\ntext\n") is True
    assert path.read_text(encoding="utf-8") == readme("### New\n\ntext")


def test_sync_block_is_idempotent_and_says_whether_it_changed_the_file(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_bytes(readme().encode())
    assert sync_block(path, START, END, "new") is True
    before = path.read_bytes()
    assert sync_block(path, START, END, "new\n") is False  # trailing newlines do not count
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "text",
    ["no markers at all\n", f"{START}\nonly the start\n", f"{END}\nbefore the start\n{START}\n", readme() + readme()],
    ids=["none", "no_end", "reversed", "twice"],
)
def test_sync_block_refuses_a_file_without_exactly_one_ordered_pair_of_markers(tmp_path: Path, text: str) -> None:
    path = tmp_path / "README.md"
    path.write_bytes(text.encode())
    with pytest.raises(ValueError, match="marker"):
        sync_block(path, START, END, "x")
    assert path.read_bytes() == text.encode()


def test_sync_block_keeps_utf8_and_does_not_leave_temporary_files(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_bytes(readme("viejo ñ").encode())
    sync_block(path, START, END, "Petróleo: 64 %")
    assert "Petróleo: 64 %" in path.read_text(encoding="utf-8") and [p.name for p in tmp_path.iterdir()] == ["README.md"]


# --- storage in SQLite -----------------------------------------------------------------------------------------


def test_the_summary_and_the_selection_are_stored_replacing_the_previous_run(small: pd.DataFrame, tmp_path: Path) -> None:
    conn = connect(tmp_path / "w.sqlite")
    apply_schema(conn)
    summary = summarize(small, CFG)
    selection = pd.DataFrame([{"fluid": "oil", "segment": "eligible", "method": "arps_mh_b2", "criterion_value": 0.5, "rule": "r"}])
    store_summary(conn, summary, selection, "r1")
    store_summary(conn, summary.iloc[:1], selection, "r2")  # replaces everything
    stored = read_summary(conn)
    assert len(stored) == 1 and set(pd.read_sql_query("SELECT run_key FROM model_summary", conn)["run_key"]) == {"r2"}
    assert list(stored.columns) == SUMMARY_COLUMNS
    assert stored.iloc[0]["wape"] == pytest.approx(summary.iloc[0]["wape"])
    chosen = read_selection(conn)
    assert chosen.to_dict("records") == [{"fluid": "oil", "segment": "eligible", "method": "arps_mh_b2", "criterion_value": 0.5, "rule": "r"}]
    conn.close()


def test_a_failed_store_keeps_the_previous_summary(small: pd.DataFrame, tmp_path: Path) -> None:
    conn = connect(tmp_path / "w.sqlite")
    apply_schema(conn)
    summary = summarize(small, CFG)
    selection = pd.DataFrame([{"fluid": "oil", "segment": "eligible", "method": "arps_mh_b2", "criterion_value": 0.5, "rule": "r"}])
    store_summary(conn, summary, selection, "r1")
    broken = pd.concat([summary, summary.iloc[:1]], ignore_index=True)  # a duplicated key
    with pytest.raises(sqlite3.IntegrityError):
        store_summary(conn, broken, selection, "r2")
    assert not conn.in_transaction
    assert set(pd.read_sql_query("SELECT run_key FROM model_summary", conn)["run_key"]) == {"r1"} and len(read_summary(conn)) == 2
    conn.close()


# --- wording --------------------------------------------------------------------------------------------------


def test_the_sentences_use_the_singular_for_one_month_and_the_spanish_contractions() -> None:
    cells = {
        ("ml_hgb", "oil", 1, "eligible"): dict(coverage=0.79, scaled_pinball=0.3),
        ("arps_mh_b2", "oil", 1, "eligible"): dict(coverage=0.81, scaled_pinball=0.4, wape=0.3, share_beats_naive_last=0.7),
        ("ml_hgb", "oil", 1, "young"): dict(coverage=0.7, scaled_pinball=0.5),
        ("naive_mean3", "oil", 1, "young"): dict(coverage=0.7, scaled_pinball=0.6),
    }
    criteria = evaluate_criteria(make_summary(cells), CRIT)
    sentences = [e["verdict_es"] for e in criteria["AC15"]] + [e["verdict_es"] for e in criteria["AC16"]]
    assert all(sentence.startswith("A 1 mes,") for sentence in sentences) and len(sentences) == 4
    assert any("cobertura P10-P90 del modelo de machine learning" in sentence for sentence in sentences)
    assert any("supera al promedio de los últimos 3 meses" in sentence for sentence in sentences)
    assert not any(" de el " in sentence or " a el " in sentence or "1 meses" in sentence for sentence in sentences)


def test_a_cell_verdict_says_one_month_in_the_singular(small: pd.DataFrame) -> None:
    summary = summarize(small.assign(horizon=1), CFG)
    assert "1 mes," in row_of(summary, "arps_mh_b2", horizon=1)["verdict_es"] and "1 meses" not in summary["verdict_es"].str.cat()
