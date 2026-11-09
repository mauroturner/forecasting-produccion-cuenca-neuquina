"""Atomic file writes (RNF05): write to a temporary file of its own, then rename.

The temporary file is unique and lives in the folder of the target, so two overlapping writers never
share it and the rename stays on one filesystem. A failure removes the temporary file and leaves the
target as it was.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_path(path: Path) -> Iterator[Path]:
    """Yield a temporary path next to `path`; on a clean exit it replaces `path` (``os.replace``)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    os.close(handle)
    temporary = Path(name)
    try:
        yield temporary
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_atomic(path: Path, data: str | bytes) -> Path:
    """Write `data` (text as UTF-8, newlines untouched) to `path` atomically; returns `path`."""
    payload = data.encode("utf-8") if isinstance(data, str) else data
    with atomic_path(path) as temporary:
        temporary.write_bytes(payload)
    return Path(path)
