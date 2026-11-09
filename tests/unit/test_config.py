"""Configuration: values, overrides, environment variables, path resolution."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from oilgas.config import PipelineConfig, load_config

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
FULL = CONFIG_DIR / "pipeline.toml"


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def extending_full(tmp_path: Path, body: str) -> Path:
    """A config file that starts from the full configuration and changes `body`."""
    return write(tmp_path / "other.toml", f'extends = "{FULL.as_posix()}"\n{body}')


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OILGAS_CONFIG", raising=False)
    monkeypatch.delenv("OILGAS_N_WORKERS", raising=False)


def test_default_values_come_from_pipeline_toml() -> None:
    cfg = load_config()
    assert isinstance(cfg, PipelineConfig)
    assert cfg.source.mode == "http"
    assert cfg.source.url.endswith("produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv")
    assert cfg.source.resource_id == "b5b58cdc-9e07-41f9-b392-fb9ec68b0725"
    assert cfg.source.chunk_bytes == 1_048_576
    assert (cfg.scope.basin, cfg.scope.resource_type, cfg.scope.first_year) == (
        "NEUQUINA",
        "NO CONVENCIONAL",
        2006,
    )
    assert cfg.validation.min_rows_ratio == 0.99
    assert cfg.validation.basin_lon == (-71.5, -66.0)
    assert cfg.validation.depth_valid_m == (1.0, 8000.0)
    assert cfg.validation.freshness_max_days == 55
    assert cfg.arps.min_post_peak_points == 6
    assert cfg.arps.b_bounds_base == (0.001, 2.0)
    assert cfg.arps.b_bounds_sensitivity == (0.001, 1.0)
    assert cfg.arps.b_starts_base == (0.3, 1.0, 1.7)
    assert cfg.arps.loss == "soft_l1"
    assert cfg.backtest.n_eval_origins == 24
    assert cfg.backtest.n_warmup_origins == 12
    assert cfg.backtest.eval_horizons == (1, 3, 6, 12)
    assert cfg.backtest.all_horizon_methods == ("arps_mh_b2", "naive_mean3")
    assert cfg.backtest.n_workers == 4
    assert cfg.ml.quantiles == (0.1, 0.5, 0.9)
    assert cfg.ml.max_iter == 250
    assert cfg.criteria.share_beats_naive_min == 0.60
    assert cfg.criteria.coverage_acceptable == (0.70, 0.90)
    assert cfg.criteria.wape_horizons == (6, 12)


def test_relative_paths_resolve_against_the_project_folder(project_root: Path) -> None:
    cfg = load_config()
    assert cfg.paths.raw_dir == project_root / "data" / "raw"
    assert cfg.paths.interim_dir == project_root / "data" / "interim"
    assert cfg.paths.warehouse == project_root / "data" / "warehouse" / "production.sqlite"
    assert cfg.paths.outputs_dir == project_root / "outputs" / "powerbi"
    assert cfg.paths.dashboard_html == project_root / "dashboard" / "powerbi-design.html"
    assert all(p.is_absolute() for p in dataclasses.astuple(cfg.paths))


def test_absolute_paths_are_kept(tmp_path: Path) -> None:
    override = write(tmp_path / "o.toml", f'[paths]\nraw_dir = "{(tmp_path / "raw").as_posix()}"\n')
    cfg = load_config(overrides=override)
    assert cfg.paths.raw_dir == tmp_path / "raw"
    assert cfg.paths.interim_dir.name == "interim"  # the siblings keep their default


def test_overrides_merge_key_by_key_and_keep_the_rest(tmp_path: Path) -> None:
    override = write(tmp_path / "o.toml", "[backtest]\nn_workers = 2\neval_horizons = [1, 2]\n")
    cfg = load_config(overrides=override)
    assert cfg.backtest.n_workers == 2
    assert cfg.backtest.eval_horizons == (1, 2)
    assert cfg.backtest.n_eval_origins == 24
    assert cfg.arps == load_config().arps


def test_a_config_path_replaces_the_default_file(tmp_path: Path) -> None:
    custom = write(
        tmp_path / "custom.toml", FULL.read_text(encoding="utf-8").replace("n_workers = 4", "n_workers = 3")
    )
    assert load_config(custom).backtest.n_workers == 3
    assert load_config().backtest.n_workers == 4


def test_quick_mode_extends_the_full_configuration() -> None:
    quick = load_config(CONFIG_DIR / "pipeline.quick.toml")
    full = load_config()
    assert quick.source.mode == "local"
    assert quick.backtest.n_eval_origins == 6
    assert quick.backtest.n_warmup_origins == 6
    assert quick.backtest.n_workers == 1
    assert (quick.ml.max_iter, quick.ml.max_train_rows, quick.ml.retrain_every) == (40, 20000, 6)
    # everything the quick file does not mention is inherited
    assert quick.arps == full.arps
    assert quick.criteria == full.criteria
    assert quick.scope == full.scope
    assert quick.backtest.eval_horizons == full.backtest.eval_horizons
    assert quick.ml.learning_rate == full.ml.learning_rate


def test_oilgas_config_selects_another_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    other = extending_full(tmp_path, "[scope]\nfirst_year = 2015\n")
    monkeypatch.setenv("OILGAS_CONFIG", str(other))
    assert load_config().scope.first_year == 2015


def test_an_explicit_path_wins_over_oilgas_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    other = extending_full(tmp_path, "[scope]\nfirst_year = 2015\n")
    monkeypatch.setenv("OILGAS_CONFIG", str(other))
    assert load_config(FULL).scope.first_year == 2006


def test_oilgas_n_workers_overrides_the_file_and_the_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = write(tmp_path / "o.toml", "[backtest]\nn_workers = 2\n")
    monkeypatch.setenv("OILGAS_N_WORKERS", "7")
    assert load_config().backtest.n_workers == 7
    assert load_config(overrides=override).backtest.n_workers == 7


@pytest.mark.parametrize("value", ["0", "-2", "many", "1.5", ""])
def test_oilgas_n_workers_must_be_a_positive_integer(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OILGAS_N_WORKERS", value)
    with pytest.raises(ValueError, match="OILGAS_N_WORKERS"):
        load_config()


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    override = write(tmp_path / "o.toml", "[arps]\nmin_post_peak_pointz = 6\n")
    with pytest.raises(ValueError, match="min_post_peak_pointz"):
        load_config(overrides=override)


def test_unknown_section_is_rejected(tmp_path: Path) -> None:
    override = write(tmp_path / "o.toml", "[bakctest]\nn_workers = 2\n")
    with pytest.raises(ValueError, match="bakctest"):
        load_config(overrides=override)


def test_missing_key_is_rejected(tmp_path: Path) -> None:
    text = FULL.read_text(encoding="utf-8").replace("seed = 42\n\n[ml]", "\n[ml]")
    broken = write(tmp_path / "broken.toml", text)
    with pytest.raises(ValueError, match="seed"):
        load_config(broken)


def test_wrong_type_is_rejected(tmp_path: Path) -> None:
    override = write(tmp_path / "o.toml", '[backtest]\nn_workers = "four"\n')
    with pytest.raises(ValueError, match="n_workers"):
        load_config(overrides=override)


def test_source_mode_must_be_http_or_local(tmp_path: Path) -> None:
    override = write(tmp_path / "o.toml", '[source]\nmode = "ftp"\n')
    with pytest.raises(ValueError, match="mode"):
        load_config(overrides=override)


def test_bounds_must_be_ordered_pairs(tmp_path: Path) -> None:
    override = write(tmp_path / "o.toml", "[arps]\nb_bounds_base = [2.0, 0.001]\n")
    with pytest.raises(ValueError, match="b_bounds_base"):
        load_config(overrides=override)


def test_missing_file_names_the_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="nope.toml"):
        load_config(tmp_path / "nope.toml")


def test_configuration_is_immutable() -> None:
    cfg = load_config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.backtest.n_workers = 9  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.scope = None  # type: ignore[misc]
