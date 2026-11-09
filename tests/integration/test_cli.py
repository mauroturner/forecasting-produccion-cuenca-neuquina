"""The command line: commands, exit codes and messages (RF19)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from oilgas import cli
from oilgas.cli import EXIT_FAILED, EXIT_OK, EXIT_REJECTED, EXIT_USAGE, build_parser, docs_sync, main
from oilgas.config import load_config
from oilgas.pipeline import TASK_IDS
from tests.fixtures.modeling import write_config

START, END = "<!-- results:start -->", "<!-- results:end -->"


@pytest.fixture()
def copy_of_run(tmp_path: Path, quick_run) -> tuple[Path, Path]:
    root, config, _ = quick_run
    copy = tmp_path / "copy"
    shutil.copytree(root, copy)
    return copy, write_config(copy, Path(load_config(config).source.local_path))


def test_the_parser_offers_the_commands_of_the_plan_and_the_task_names() -> None:
    parser = build_parser()
    parsed = parser.parse_args(["run", "--adopt", "x.csv", "--only", "validate", "load", "--from", "validate", "--run-key", "k"])
    assert (parsed.command, parsed.only, parsed.start, parsed.run_key, str(parsed.adopt)) == ("run", ["validate", "load"], "validate", "k", "x.csv")
    for task in TASK_IDS:
        assert parser.parse_args(["task", task]).task == task
    assert parser.parse_args(["make-fixture", "out.csv", "--wells", "7", "--seed", "3"]).wells == 7
    for bad in (["run", "--only", "nonsense"], ["task", "nonsense"], []):
        with pytest.raises(SystemExit) as info:
            parser.parse_args(bad)
        assert info.value.code == 2


def test_run_prints_the_tasks_and_exits_zero_and_an_unchanged_publication_says_so(copy_of_run, capsys) -> None:
    _, config = copy_of_run
    assert main(["run", "--config", str(config)]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("check_publication") and "changed=False" in out and "unchanged:" in out
    assert "download" not in out  # the run ended after the check


def test_a_rejected_publication_exits_with_three_and_names_the_rule(copy_of_run, malformed, capsys) -> None:
    root, _ = copy_of_run
    config = write_config(root, malformed("month_13"))
    assert main(["run", "--config", str(config)]) == EXIT_REJECTED
    captured = capsys.readouterr()
    assert "rejected" in captured.err and "V04" in captured.err and captured.out.count("check_publication") == 1


def test_a_missing_configuration_or_file_exits_with_two(tmp_path: Path, capsys) -> None:
    assert main(["run", "--config", str(tmp_path / "nope.toml")]) == EXIT_USAGE
    assert "configuration error" in capsys.readouterr().err
    bad = tmp_path / "bad.toml"
    bad.write_text("[nonsense]\nx = 1\n", encoding="utf-8")
    assert main(["run", "--config", str(bad)]) == EXIT_USAGE


def test_a_task_that_fails_exits_with_one_and_says_which_error(copy_of_run, monkeypatch, capsys) -> None:
    _, config = copy_of_run

    def boom(*args, **kwargs):
        raise RuntimeError("no space left")

    monkeypatch.setattr(cli, "run_all", boom)
    assert main(["run", "--config", str(config)]) == EXIT_FAILED
    assert "failed: RuntimeError: no space left" in capsys.readouterr().err


def test_task_runs_one_task_of_a_run(tmp_path: Path, fixture_csv: Path, capsys) -> None:
    config = write_config(tmp_path, fixture_csv)
    assert main(["task", "check_publication", "--config", str(config), "--run-key", "k1"]) == EXIT_OK
    assert capsys.readouterr().out.startswith("check_publication: changed=True")
    assert main(["task", "download", "--config", str(config), "--run-key", "k1"]) == EXIT_OK
    assert "how=local" in capsys.readouterr().out


def test_docs_sync_copies_the_results_block_into_the_readme_and_is_idempotent(copy_of_run, capsys) -> None:
    root, config = copy_of_run
    readme = root / "README.md"
    readme.write_text(f"# Title\n\n{START}\nold\n{END}\n\nafter\n", encoding="utf-8", newline="\n")
    assert main(["docs-sync", "--config", str(config)]) == EXIT_OK and "README updated" in capsys.readouterr().out
    summary = (root / "reports/backtest_summary.md").read_text(encoding="utf-8")
    assert summary.strip() in readme.read_text(encoding="utf-8") and readme.read_text(encoding="utf-8").endswith("\nafter\n")
    assert main(["docs-sync", "--config", str(config)]) == EXIT_OK and "already up to date" in capsys.readouterr().out
    assert docs_sync(load_config(config)) is False


def test_docs_sync_without_a_summary_or_markers_is_a_usage_error(tmp_path: Path, fixture_csv: Path, capsys) -> None:
    config = write_config(tmp_path, fixture_csv)
    assert main(["docs-sync", "--config", str(config)]) == EXIT_USAGE
    assert "run the pipeline first" in capsys.readouterr().err


def test_make_fixture_writes_a_publication_the_pipeline_accepts(tmp_path: Path, capsys) -> None:
    out = tmp_path / "fixture.csv"
    assert main(["make-fixture", str(out), "--wells", "12", "--seed", "1"]) == EXIT_OK
    assert out.exists() and out.read_bytes().startswith(b"\xef\xbb\xbf") and "wrote" in capsys.readouterr().out
    config = write_config(tmp_path / "run", out, well_sample=0)
    assert main(["task", "check_publication", "--config", str(config), "--run-key", "k"]) == EXIT_OK
    assert main(["task", "download", "--config", str(config), "--run-key", "k"]) == EXIT_OK
    assert main(["task", "validate", "--config", str(config), "--run-key", "k"]) == EXIT_OK


def test_figures_draws_the_four_pngs_next_to_the_readme(copy_of_run, capsys) -> None:
    root, config = copy_of_run
    assert main(["figures", "--config", str(config)]) == EXIT_OK
    out = capsys.readouterr().out
    names = ["example_well_fit.png", "method_comparison.png", "coverage.png", "basin_forecast.png"]
    assert all((root / "docs" / "figures" / name).read_bytes()[:4] == b"\x89PNG" for name in names)
    assert all(name in out for name in names)


def test_figures_without_a_run_exits_with_two_and_says_what_to_do(tmp_path: Path, fixture_csv: Path, capsys) -> None:
    assert main(["figures", "--config", str(write_config(tmp_path, fixture_csv))]) == EXIT_USAGE
    assert "run the pipeline" in capsys.readouterr().err
    assert not (tmp_path / "docs").exists()
