"""The modules that run unattended report through ``logging`` and never print (H1, RNF12)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "oilgas"
UNATTENDED = ("ingest", "validate", "warehouse")


@pytest.mark.parametrize("module", UNATTENDED)
def test_the_module_logs_with_the_standard_library_and_does_not_print(module: str) -> None:
    tree = ast.parse((SRC / f"{module}.py").read_text(encoding="utf-8"))
    prints = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "print"]
    assert prints == []
    loggers = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "getLogger"
        and any(isinstance(a, ast.Name) and a.id == "__name__" for a in n.args)
    ]
    assert len(loggers) == 1  # one module logger, named after the module
