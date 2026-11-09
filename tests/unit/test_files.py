"""Atomic writes: a unique temporary file next to the target, replaced in one step (RNF05)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from oilgas import files
from oilgas.files import atomic_path, write_atomic


def test_write_atomic_creates_the_folder_and_writes_text_and_bytes_untouched(tmp_path: Path) -> None:
    target = write_atomic(tmp_path / "a" / "b" / "out.txt", "línea 1\nlínea 2\n")
    assert target.read_bytes() == "línea 1\nlínea 2\n".encode()  # UTF-8, no newline translation
    write_atomic(target, b"\x00\x01")
    assert target.read_bytes() == b"\x00\x01"
    assert [p.name for p in target.parent.iterdir()] == ["out.txt"]


def test_every_write_uses_its_own_temporary_file_next_to_the_target(tmp_path: Path, monkeypatch) -> None:
    sources: list[Path] = []
    real = os.replace

    def spy(source, target):
        sources.append(Path(source))
        return real(source, target)

    monkeypatch.setattr(files.os, "replace", spy)
    target = tmp_path / "out.json"
    write_atomic(target, "1")
    write_atomic(target, "2")
    assert len(set(sources)) == 2 and all(s.parent == target.parent and s != target for s in sources)


def test_a_failure_inside_the_block_keeps_the_old_file_and_removes_the_temporary_one(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    write_atomic(target, "old")
    with pytest.raises(RuntimeError, match="boom"), atomic_path(target) as temporary:
        temporary.write_text("half written")
        raise RuntimeError("boom")
    assert target.read_text() == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["out.txt"]
