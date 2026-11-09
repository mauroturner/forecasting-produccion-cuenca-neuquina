"""A pipeline context and a small configuration for the tests that run the model tasks on the synthetic warehouse."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

from oilgas.config import PipelineConfig, load_config

BASE = load_config()


@dataclass(frozen=True)
class RunCtx:
    """What the tasks need from a run: the configuration and the run key."""

    cfg: PipelineConfig
    run_key: str


def small_cfg(warehouse: Path, interim: Path, outputs: Path | None = None, well_sample: int = 20) -> PipelineConfig:
    """The quick-mode shape (6 + 6 origins, one process, a small model) on a sample of the synthetic wells."""
    paths = dataclasses.replace(BASE.paths, warehouse=warehouse, interim_dir=interim)
    if outputs is not None:
        paths = dataclasses.replace(paths, outputs_dir=outputs)
    return dataclasses.replace(
        BASE,
        paths=paths,
        backtest=dataclasses.replace(BASE.backtest, n_eval_origins=6, n_warmup_origins=6, n_workers=1, well_sample=well_sample),
        ml=dataclasses.replace(BASE.ml, max_iter=8, min_samples_leaf=10, max_train_rows=2000, train_window_months=18),
    )


def write_config(root: Path, csv: Path, well_sample: int = 20, name: str = "pipeline.test.toml") -> Path:
    """A configuration file for a run under `root` on the local file `csv`: the quick mode with every path inside `root`."""
    quick = (Path(__file__).resolve().parents[2] / "config" / "pipeline.quick.toml").as_posix()
    paths = {
        "raw_dir": "data/raw", "interim_dir": "data/interim", "warehouse": "data/warehouse/production.sqlite",
        "outputs_dir": "outputs/powerbi", "reports_dir": "reports", "dashboard_html": "dashboard/powerbi-design.html", "readme": "README.md",
    }
    lines = [f'extends = "{quick}"', "", "[source]", 'mode = "local"', f'local_path = "{Path(csv).as_posix()}"', "",
             "[backtest]", f"well_sample = {well_sample}", "", "[paths]"]
    lines += [f'{key} = "{(Path(root) / value).as_posix()}"' for key, value in paths.items()]
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path
