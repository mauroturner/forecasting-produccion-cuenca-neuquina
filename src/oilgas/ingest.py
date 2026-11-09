"""Detection and download of the monthly publication (RF01, RF02, D13).

The server answers ``HEAD`` with ``ETag``, ``Last-Modified`` and ``Content-Range``, but ignores
``Range``, ``If-None-Match`` and ``If-Modified-Since``. So a change is detected by comparing the
``HEAD`` metadata with the last successful load in the manifest, and the download is always whole,
written to ``<name>.part`` and renamed only when the size is the announced one.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime
from email.utils import formatdate
from pathlib import Path
from typing import Literal

from oilgas.files import write_atomic

logger = logging.getLogger(__name__)

USER_AGENT = "oilgas-pipeline/0.1"
MANIFEST_VERSION = 1
STATUSES = ("downloaded", "loaded", "rejected")
SETTLED = ("loaded", "rejected")  # a run in one of these states is past its download
_CONTENT_RANGE = re.compile(r"bytes\s+\d+-\d+/(\d+)")


class IngestError(RuntimeError):
    """Base class of the errors of this module."""


class SourceNotFoundError(IngestError):
    """The publication URL answered 404 (runbook R11)."""


class DownloadError(IngestError):
    """The download or the adoption of a file did not end with the announced size."""


@dataclass(frozen=True)
class RemoteMeta:
    url: str
    etag: str | None
    last_modified: str | None
    size: int | None


@dataclass(frozen=True)
class ManifestEntry:
    url: str
    etag: str | None
    last_modified: str | None
    size: int
    sha256: str
    local_path: str
    downloaded_at: str
    status: Literal["downloaded", "loaded", "rejected"]
    run_key: str


def _not_found(url: str) -> SourceNotFoundError:
    return SourceNotFoundError(
        f"The publication was not found at {url} (HTTP 404). The resource may have moved or been "
        "renamed: follow docs/runbook.md, R11."
    )


def _open(url: str, method: str, timeout_s: int):
    request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    try:
        return urllib.request.urlopen(request, timeout=timeout_s)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise _not_found(url) from error
        raise


def head_remote(url: str, timeout_s: int) -> RemoteMeta:
    """Read the publication metadata with ``HEAD``; nothing is downloaded."""
    with _open(url, "HEAD", timeout_s) as response:
        headers = response.headers
        size: int | None = None
        match = _CONTENT_RANGE.match(headers.get("Content-Range", ""))
        if match:
            size = int(match.group(1))
        elif headers.get("Content-Length", "").isdigit():
            size = int(headers["Content-Length"])
        meta = RemoteMeta(url, headers.get("ETag"), headers.get("Last-Modified"), size)
    logger.info("HEAD %s -> etag=%s last_modified=%s size=%s", url, meta.etag, meta.last_modified, meta.size)
    return meta


def local_meta(path: Path) -> RemoteMeta:
    """The same metadata for a local file (``source.mode = "local"``): size and modification time."""
    path = Path(path)
    stat = path.stat()
    return RemoteMeta(
        url=path.resolve().as_uri(),
        etag=None,
        last_modified=formatdate(stat.st_mtime, usegmt=True),
        size=stat.st_size,
    )


def is_changed(remote: RemoteMeta, last: ManifestEntry | None) -> bool:
    """True when there is no previous load or `ETag`, `Last-Modified` or size differ from it."""
    if last is None:
        return True
    return (remote.etag, remote.last_modified, remote.size) != (last.etag, last.last_modified, last.size)


# --- manifest ---------------------------------------------------------------------------------------


def read_manifest(path: Path) -> list[ManifestEntry]:
    """Entries in the order they were appended; a missing manifest is an empty list."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        names = {f.name for f in fields(ManifestEntry)}
        entries = []
        for raw in document["entries"]:
            if set(raw) != names:
                raise KeyError(sorted(set(raw) ^ names))
            entries.append(ManifestEntry(**raw))
        return entries
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{path} is not a valid manifest: {error}") from error


def _write_manifest(path: Path, entries: list[ManifestEntry]) -> None:
    """Write the manifest through a unique temporary file in its folder and rename it (RNF05)."""
    document = {"version": MANIFEST_VERSION, "entries": [asdict(e) for e in entries]}
    write_atomic(path, json.dumps(document, indent=2, ensure_ascii=False) + "\n")


def _check_status(status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"status {status!r} is not one of {', '.join(STATUSES)}")


def append_manifest(path: Path, entry: ManifestEntry) -> None:
    """Add an entry; one with the same `run_key` is replaced, so repeating a task changes nothing.

    An entry that is already past ``downloaded`` (``loaded`` or ``rejected``) is never replaced by a
    ``downloaded`` one: running the download task again after the load must not make the run look
    unloaded. The settled entry is kept as it is (``mark_manifest`` is the explicit way to change a status).
    """
    _check_status(entry.status)
    entries = read_manifest(path)
    existing = next((e for e in entries if e.run_key == entry.run_key), None)
    if existing is None:
        entries.append(entry)
    elif existing.status in SETTLED and entry.status not in SETTLED:
        logger.warning(
            "manifest %s: run_key %s is already %s; the %s entry was not applied",
            path, entry.run_key, existing.status, entry.status,
        )
        return
    else:
        logger.info(
            "manifest %s: run_key %s replaced (%s -> %s)", path, entry.run_key, existing.status, entry.status
        )
        entries = [entry if e.run_key == entry.run_key else e for e in entries]
    _write_manifest(Path(path), entries)


def mark_manifest(path: Path, run_key: str, status: str) -> None:
    """Set the status of the entry of `run_key`."""
    _check_status(status)
    entries = read_manifest(path)
    if not any(e.run_key == run_key for e in entries):
        raise ValueError(f"no manifest entry for run_key {run_key!r} in {path}")
    _write_manifest(Path(path), [replace(e, status=status) if e.run_key == run_key else e for e in entries])
    logger.info("manifest %s: run_key %s marked %s", path, run_key, status)


def last_loaded(entries: list[ManifestEntry]) -> ManifestEntry | None:
    """The most recent entry that was loaded into the warehouse."""
    for entry in reversed(entries):
        if entry.status == "loaded":
            return entry
    return None


# --- download ---------------------------------------------------------------------------------------


def download_file(
    url: str, dest: Path, expected_size: int | None, chunk_bytes: int, timeout_s: int
) -> tuple[Path, str]:
    """Download the whole file to ``<dest>.part`` and rename it to `dest` if the size is right.

    Returns ``(dest, sha256)``. The hash is computed while writing. When the size differs from
    `expected_size` (or from the response's ``Content-Length`` if none was given) the ``.part`` is
    kept, `dest` is left as it was and ``DownloadError`` is raised.
    """
    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    received = 0
    started = time.perf_counter()
    with _open(url, "GET", timeout_s) as response:
        announced = expected_size
        if announced is None and response.headers.get("Content-Length", "").isdigit():
            announced = int(response.headers["Content-Length"])
        logger.info("download start: %s (announced size %s) to %s", url, announced, part)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with part.open("wb") as handle:
                while chunk := response.read(chunk_bytes):
                    handle.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
        except (http.client.IncompleteRead, ConnectionError) as error:
            logger.error("download interrupted: %s after %d bytes; kept %s", url, received, part)
            raise DownloadError(
                f"The connection to {url} closed after {received} bytes; kept {part}."
            ) from error
    if announced is not None and received != announced:
        logger.error("download size mismatch: %s gave %d bytes, expected %d; kept %s", url, received, announced, part)
        raise DownloadError(
            f"Downloaded {received} bytes from {url} but expected {announced}; kept {part} and did not "
            f"replace {dest}."
        )
    os.replace(part, dest)
    logger.info(
        "download end: %s, %d bytes, sha256 %s, %.1f s", dest, received, digest.hexdigest(), time.perf_counter() - started
    )
    return dest, digest.hexdigest()


def _sha256_of(path: Path, block: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(block):
            digest.update(chunk)
    return digest.hexdigest()


def adopt_local_file(path: Path, remote: RemoteMeta, run_key: str) -> ManifestEntry:
    """Build the manifest entry of an already downloaded file, without downloading it again.

    The file must have the announced size (when the remote metadata has one). The entry is not
    appended to the manifest: the caller does that.
    """
    path = Path(path)
    size = path.stat().st_size
    if remote.size is not None and size != remote.size:
        raise DownloadError(f"{path} has {size} bytes but the publication announces {remote.size}.")
    return ManifestEntry(
        url=remote.url,
        etag=remote.etag,
        last_modified=remote.last_modified,
        size=size,
        sha256=_sha256_of(path),
        local_path=path.as_posix(),
        downloaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
        status="downloaded",
        run_key=run_key,
    )


def quarantine(path: Path, quarantine_dir: Path, sha256: str) -> Path:
    """Move a rejected file to `quarantine_dir` as ``<stem>.<sha256[:12]><suffix>``."""
    path, quarantine_dir = Path(path), Path(quarantine_dir)
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    target = quarantine_dir / f"{path.stem}.{sha256[:12]}{path.suffix}"
    try:
        os.replace(path, target)
    except OSError:  # another drive: copy, then remove
        if target.exists():
            target.unlink()
        shutil.move(str(path), str(target))
    logger.warning("quarantined %s as %s", path, target)
    return target
