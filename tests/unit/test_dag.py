"""The Airflow DAG without Airflow: its text with ``ast`` and its wiring with a stand-in for ``airflow.sdk`` (AC19)."""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from oilgas.pipeline import TASK_IDS, TASKS

DAG_FILE = Path(__file__).resolve().parents[2] / "airflow" / "dags" / "oilgas_monthly.py"


def keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {k.arg: k.value for k in call.keywords if k.arg}


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(DAG_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dag_call(tree: ast.Module) -> ast.Call:
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "DAG"]
    assert len(calls) == 1
    return calls[0]


# --- the text of the file ------------------------------------------------------------------------------------------


def test_the_dag_has_the_id_the_daily_schedule_no_catchup_and_one_active_run_and_task(dag_call: ast.Call) -> None:
    options = keywords(dag_call)
    assert ast.literal_eval(options["dag_id"]) == "oilgas_monthly_production"
    assert ast.literal_eval(options["schedule"]) == "0 9 * * *"
    assert ast.literal_eval(options["catchup"]) is False
    assert ast.literal_eval(options["max_active_runs"]) == 1 and ast.literal_eval(options["max_active_tasks"]) == 1
    assert ast.literal_eval(options["tags"]) == ["oilgas"]
    assert ast.literal_eval(options["default_args"]) == {"retry_exponential_backoff": True}
    start = options["start_date"]
    assert isinstance(start, ast.Call) and [ast.literal_eval(a) for a in start.args] == [2026, 11, 1]


def test_it_uses_the_airflow_3_sdk_and_the_functions_of_the_pipeline(tree: ast.Module) -> None:
    imports = {(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert {("airflow.sdk", "DAG"), ("airflow.sdk", "task"), ("oilgas.pipeline", "TASKS"), ("oilgas.pipeline", "run_task")} <= imports


def test_the_tasks_come_from_the_task_list_and_are_chained_in_its_order_not_typed_in_the_dag(tree: ast.Module) -> None:
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)]
    assert any(isinstance(n.iter, ast.Name) and n.iter.id == "TASKS" for n in loops)
    chained = [n for loop in loops for n in ast.walk(loop) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.RShift)]
    assert chained, "the tasks are chained with >> inside the loop over TASKS"
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not strings & set(TASK_IDS)  # no task id is written in the DAG


def test_the_options_of_each_task_come_from_its_spec_and_the_check_is_a_short_circuit(tree: ast.Module) -> None:
    text = DAG_FILE.read_text(encoding="utf-8")
    for fragment in ("spec.retries", "spec.retry_delay_min", "spec.timeout_min", "spec.short_circuit", "task.short_circuit", "run_task(spec.task_id, run_id)", '["changed"]'):
        assert fragment in text, fragment


# --- the wiring, with a stand-in for airflow.sdk ------------------------------------------------------------------------


class Node:
    def __init__(self, function, options):
        self.function, self.options, self.downstream = function, options, []

    def __rshift__(self, other):
        self.downstream.append(other)
        return other


class FakeDag:
    instances: list[FakeDag] = []

    def __init__(self, **options):
        self.options, self.nodes = options, []
        FakeDag.instances.append(self)

    def __enter__(self):
        FakeDag.current = self
        return self

    def __exit__(self, *exc):
        return False


class FakeTask:
    def _decorator(self, kind, options):
        def wrap(function):
            def build():
                node = Node(function, {"kind": kind, **options})
                FakeDag.current.nodes.append(node)
                return node

            return build

        return wrap

    def __call__(self, **options):
        return self._decorator("task", options)

    def short_circuit(self, **options):
        return self._decorator("short_circuit", options)


@pytest.fixture()
def loaded_dag(monkeypatch):
    sdk = types.ModuleType("airflow.sdk")
    sdk.DAG, sdk.task = FakeDag, FakeTask()
    monkeypatch.setitem(sys.modules, "airflow", types.ModuleType("airflow"))
    monkeypatch.setitem(sys.modules, "airflow.sdk", sdk)
    FakeDag.instances.clear()
    spec = importlib.util.spec_from_file_location("oilgas_monthly_dag", DAG_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, FakeDag.instances[0]


def test_the_dag_builds_one_task_per_spec_in_order_with_its_limits(loaded_dag) -> None:
    _, dag = loaded_dag
    assert [n.options["task_id"] for n in dag.nodes] == list(TASK_IDS)
    for node, spec in zip(dag.nodes, TASKS, strict=True):
        assert node.options["retries"] == spec.retries
        assert node.options["retry_delay"] == timedelta(minutes=spec.retry_delay_min)
        assert node.options["execution_timeout"] == timedelta(minutes=spec.timeout_min)
        assert node.options["kind"] == ("short_circuit" if spec.short_circuit else "task")
    assert dag.options["start_date"] == datetime(2026, 11, 1, tzinfo=UTC)


def test_each_task_depends_on_the_one_before_it(loaded_dag) -> None:
    _, dag = loaded_dag
    for before, after in zip(dag.nodes, dag.nodes[1:], strict=False):
        assert before.downstream == [after]
    assert dag.nodes[-1].downstream == []


def test_each_task_runs_its_own_pipeline_task_with_the_run_id_of_airflow(loaded_dag, monkeypatch) -> None:
    module, dag = loaded_dag
    calls = []

    def fake_run_task(task_id, run_id=None, cfg=None, **kwargs):
        calls.append((task_id, run_id))
        return {"changed": task_id != "check_publication"}

    monkeypatch.setattr(module, "run_task", fake_run_task)
    results = [node.function(run_id="scheduled__x") for node in dag.nodes]
    assert calls == [(task_id, "scheduled__x") for task_id in TASK_IDS]  # not the last loop variable nine times
    assert results[0] is False  # an unchanged publication stops the run: the short circuit gets False
    assert all(r is None for r in results[1:])  # the rest do not put their results in XCom


def test_the_dag_and_the_command_line_list_the_same_tasks() -> None:
    from oilgas.cli import build_parser

    parser = build_parser()
    run = next(a for a in parser._subparsers._group_actions[0].choices.values() if a.prog.endswith(" run"))
    only = next(a for a in run._actions if a.dest == "only")
    assert list(only.choices) == list(TASK_IDS) == [t.task_id for t in TASKS]
