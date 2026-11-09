"""DAG ``oilgas_monthly_production``: the nine tasks of ``oilgas.pipeline.TASKS``, wired in their order.

The DAG only wires: each task calls ``oilgas.pipeline.run_task(task_id, run_id)``, the same function the
command line runs, so Airflow and ``python -m oilgas run`` do the same work in the same order. The check
of the publication is a short circuit: an unchanged publication skips the rest of the run. It runs every
day (a late publication is taken the day it appears) with one active run and one active task at a time,
because the warehouse is a SQLite file with a single writer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from airflow.sdk import DAG, task

from oilgas.pipeline import TASKS, TaskSpec, run_task


def build_task(spec: TaskSpec):
    """One Airflow task for a ``TaskSpec`` (a function of its own, so the loop variable is never captured)."""
    options = {
        "task_id": spec.task_id,
        "retries": spec.retries,
        "retry_delay": timedelta(minutes=spec.retry_delay_min),
        "execution_timeout": timedelta(minutes=spec.timeout_min),
    }
    if spec.short_circuit:

        @task.short_circuit(**options)
        def step(run_id=None) -> bool:
            return bool(run_task(spec.task_id, run_id)["changed"])

    else:

        @task(**options)
        def step(run_id=None) -> None:
            run_task(spec.task_id, run_id)  # the result stays in the run's state file, not in XCom

    return step()


with DAG(
    dag_id="oilgas_monthly_production",
    schedule="0 9 * * *",  # every day at 09:00 UTC, 06:00 in Argentina
    start_date=datetime(2026, 11, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    default_args={"retry_exponential_backoff": True},
    tags=["oilgas"],
    doc_md=__doc__,
) as dag:
    previous = None
    for spec in TASKS:
        current = build_task(spec)
        if previous is not None:
            previous >> current
        previous = current
