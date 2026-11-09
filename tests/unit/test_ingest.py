"""RF01, RF02, AC01, AC02: change detection, whole download, manifest, adoption, quarantine."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
from datetime import datetime
from pathlib import Path

import pytest

from oilgas.ingest import (
    DownloadError,
    ManifestEntry,
    RemoteMeta,
    SourceNotFoundError,
    adopt_local_file,
    append_manifest,
    download_file,
    head_remote,
    is_changed,
    last_loaded,
    local_meta,
    mark_manifest,
    quarantine,
    read_manifest,
)
from tests.fixtures.http_server import PublicationServer

BODY = bytes(range(256)) * 40  # 10 240 bytes


@pytest.fixture()
def server():
    with PublicationServer(body=BODY) as srv:
        yield srv


def entry(run_key: str = "r1", status: str = "loaded", **overrides) -> ManifestEntry:
    values = dict(
        url="http://example.test/resource.csv", etag='"v1"', last_modified="Thu, 22 Oct 2026 21:00:56 GMT",
        size=len(BODY), sha256="ab" * 32, local_path="data/raw/resource.csv",
        downloaded_at="2026-11-09T12:00:00+00:00", status=status, run_key=run_key,
    )
    values.update(overrides)
    return ManifestEntry(**values)


# --- head_remote ----------------------------------------------------------------------------------


def test_head_reads_etag_last_modified_and_size_from_content_range(server) -> None:
    meta = head_remote(server.url, timeout_s=5)
    assert meta == RemoteMeta(
        url=server.url, etag='"v1"', last_modified="Thu, 22 Oct 2026 21:00:56 GMT", size=len(BODY)
    )
    assert server.methods() == ["HEAD"]  # nothing was downloaded


def test_head_falls_back_to_content_length(server) -> None:
    server.mode = "length"
    assert head_remote(server.url, timeout_s=5).size == len(BODY)


def test_head_without_etag_or_last_modified_gives_none(server) -> None:
    server.etag = None
    server.last_modified = None
    meta = head_remote(server.url, timeout_s=5)
    assert (meta.etag, meta.last_modified, meta.size) == (None, None, len(BODY))


def test_head_404_fails_pointing_to_the_runbook(server) -> None:
    with pytest.raises(SourceNotFoundError, match="R11") as info:
        head_remote(server.missing_url, timeout_s=5)
    assert server.missing_url in str(info.value)


def test_head_other_http_errors_propagate(server) -> None:
    server.mode = "error"
    with pytest.raises(urllib.error.HTTPError) as info:
        head_remote(server.url, timeout_s=5)
    assert info.value.code == 500


# --- local_meta -----------------------------------------------------------------------------------


def test_local_meta_uses_size_and_modification_time(tmp_path: Path) -> None:
    path = tmp_path / "file.csv"
    path.write_bytes(BODY)
    os.utime(path, (1_767_225_600, 1_767_225_600))  # 2026-01-01 00:00:00 UTC
    meta = local_meta(path)
    assert meta == RemoteMeta(url=path.resolve().as_uri(), etag=None, last_modified="Thu, 01 Jan 2026 00:00:00 GMT", size=len(BODY))


def test_local_meta_changes_when_the_file_changes(tmp_path: Path) -> None:
    path = tmp_path / "file.csv"
    path.write_bytes(BODY)
    before = local_meta(path)
    path.write_bytes(BODY + b"x")
    os.utime(path, (1_767_225_601, 1_767_225_601))
    last = entry(url=before.url, etag=before.etag, last_modified=before.last_modified, size=before.size)
    assert is_changed(before, last) is False
    assert is_changed(local_meta(path), last) is True


# --- is_changed (AC01) ----------------------------------------------------------------------------


def test_no_previous_load_means_changed() -> None:
    assert is_changed(RemoteMeta("u", '"v1"', "lm", 10), None) is True


def test_identical_metadata_means_unchanged() -> None:
    last = entry(etag='"v1"', last_modified="lm", size=10)
    assert is_changed(RemoteMeta("u", '"v1"', "lm", 10), last) is False


@pytest.mark.parametrize(
    "remote",
    [
        RemoteMeta("u", '"v2"', "lm", 10),
        RemoteMeta("u", '"v1"', "lm2", 10),
        RemoteMeta("u", '"v1"', "lm", 11),
        RemoteMeta("u", None, "lm", 10),
        RemoteMeta("u", '"v1"', "lm", None),
    ],
    ids=["etag", "last_modified", "size", "etag_missing", "size_missing"],
)
def test_any_difference_means_changed(remote: RemoteMeta) -> None:
    assert is_changed(remote, entry(etag='"v1"', last_modified="lm", size=10)) is True


def test_a_publication_is_detected_end_to_end(server, tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    meta = head_remote(server.url, 5)
    assert is_changed(meta, last_loaded(read_manifest(manifest))) is True

    path, sha = download_file(server.url, tmp_path / "resource.csv", meta.size, 4096, 5)
    append_manifest(manifest, entry("r1", "downloaded", etag=meta.etag, last_modified=meta.last_modified, size=meta.size, sha256=sha))
    assert is_changed(head_remote(server.url, 5), last_loaded(read_manifest(manifest))) is True  # not loaded yet
    mark_manifest(manifest, "r1", "loaded")
    assert is_changed(head_remote(server.url, 5), last_loaded(read_manifest(manifest))) is False

    server.etag = '"v2"'
    assert is_changed(head_remote(server.url, 5), last_loaded(read_manifest(manifest))) is True
    server.etag = '"v1"'
    server.last_modified = "Fri, 23 Oct 2026 21:00:56 GMT"
    assert is_changed(head_remote(server.url, 5), last_loaded(read_manifest(manifest))) is True
    server.last_modified = "Thu, 22 Oct 2026 21:00:56 GMT"
    server.body = BODY + b"more"
    assert is_changed(head_remote(server.url, 5), last_loaded(read_manifest(manifest))) is True
    assert server.methods().count("GET") == 1  # only the one download


# --- manifest -------------------------------------------------------------------------------------


def test_missing_manifest_reads_as_empty(tmp_path: Path) -> None:
    assert read_manifest(tmp_path / "manifest.json") == []


def test_manifest_round_trip_keeps_every_field(tmp_path: Path) -> None:
    path = tmp_path / "raw" / "manifest.json"  # the folder is created on demand
    first, second = entry("r1", "downloaded"), entry("r2", "loaded", etag=None, size=5)
    append_manifest(path, first)
    append_manifest(path, second)
    assert read_manifest(path) == [first, second]
    document = json.loads(path.read_text(encoding="utf-8"))
    assert [e["run_key"] for e in document["entries"]] == ["r1", "r2"]
    assert document["entries"][1]["etag"] is None
    assert not list(path.parent.glob("*.tmp"))


def test_appending_the_same_run_key_replaces_the_entry(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    append_manifest(path, entry("r1", "downloaded", sha256="aa" * 32))
    append_manifest(path, entry("r2", "downloaded"))
    append_manifest(path, entry("r1", "downloaded", sha256="bb" * 32))
    entries = read_manifest(path)
    assert [e.run_key for e in entries] == ["r1", "r2"]
    assert entries[0].sha256 == "bb" * 32


def test_mark_manifest_changes_only_that_run(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    append_manifest(path, entry("r1", "downloaded"))
    append_manifest(path, entry("r2", "downloaded"))
    mark_manifest(path, "r2", "rejected")
    assert [(e.run_key, e.status) for e in read_manifest(path)] == [("r1", "downloaded"), ("r2", "rejected")]


def test_mark_manifest_rejects_unknown_run_and_status(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    append_manifest(path, entry("r1", "downloaded"))
    with pytest.raises(ValueError, match="r9"):
        mark_manifest(path, "r9", "loaded")
    with pytest.raises(ValueError, match="done"):
        mark_manifest(path, "r1", "done")
    assert read_manifest(path)[0].status == "downloaded"
    with pytest.raises(ValueError, match="done"):
        append_manifest(path, entry("r2", "done"))


def test_corrupt_manifest_is_reported_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest.json"):
        read_manifest(path)
    with pytest.raises(ValueError, match="manifest.json"):
        append_manifest(path, entry())
    assert path.read_text(encoding="utf-8") == "{not json"


def test_last_loaded_is_the_latest_loaded_entry() -> None:
    entries = [entry("r1", "loaded"), entry("r2", "loaded"), entry("r3", "downloaded"), entry("r4", "rejected")]
    assert last_loaded(entries).run_key == "r2"
    assert last_loaded([entry("r1", "downloaded"), entry("r2", "rejected")]) is None
    assert last_loaded([]) is None


# --- download_file (AC02) -------------------------------------------------------------------------


def test_download_writes_the_whole_file_and_returns_its_sha256(server, tmp_path: Path) -> None:
    dest = tmp_path / "raw" / "resource.csv"
    path, sha = download_file(server.url, dest, len(BODY), 1 << 20, 5)
    assert path == dest
    assert dest.read_bytes() == BODY
    assert sha == hashlib.sha256(BODY).hexdigest()
    assert not Path(str(dest) + ".part").exists()
    assert server.methods() == ["GET"]
    assert "Range" not in server.requests[0][2]


def test_download_in_small_blocks_gives_the_same_result(server, tmp_path: Path) -> None:
    path, sha = download_file(server.url, tmp_path / "resource.csv", len(BODY), 7, 5)
    assert path.read_bytes() == BODY
    assert sha == hashlib.sha256(BODY).hexdigest()


def test_download_replaces_a_previous_file_and_a_stale_part(server, tmp_path: Path) -> None:
    dest = tmp_path / "resource.csv"
    dest.write_bytes(b"old")
    Path(str(dest) + ".part").write_bytes(b"stale partial")
    download_file(server.url, dest, None, 1024, 5)
    assert dest.read_bytes() == BODY
    assert not Path(str(dest) + ".part").exists()


def test_a_size_different_from_the_announced_keeps_the_part_and_raises(server, tmp_path: Path) -> None:
    dest = tmp_path / "resource.csv"
    dest.write_bytes(b"previous good file")
    with pytest.raises(DownloadError, match=str(len(BODY) + 5)):
        download_file(server.url, dest, len(BODY) + 5, 1024, 5)
    assert dest.read_bytes() == b"previous good file"  # never replaced
    assert Path(str(dest) + ".part").read_bytes() == BODY


def test_a_connection_closed_early_raises_and_does_not_rename(server, tmp_path: Path) -> None:
    server.mode = "truncate"
    dest = tmp_path / "resource.csv"
    with pytest.raises(DownloadError):
        download_file(server.url, dest, len(BODY), 1024, 5)
    assert not dest.exists()
    assert Path(str(dest) + ".part").exists()
    assert Path(str(dest) + ".part").stat().st_size < len(BODY)


def test_download_404_fails_pointing_to_the_runbook(server, tmp_path: Path) -> None:
    dest = tmp_path / "resource.csv"
    with pytest.raises(SourceNotFoundError, match="R11"):
        download_file(server.missing_url, dest, None, 1024, 5)
    assert not dest.exists() and not Path(str(dest) + ".part").exists()


# --- adopt_local_file -----------------------------------------------------------------------------


def test_adopting_a_downloaded_file_builds_its_entry(tmp_path: Path) -> None:
    path = tmp_path / "resource.csv"
    path.write_bytes(BODY)
    remote = RemoteMeta("http://example.test/resource.csv", '"v1"', "Thu, 22 Oct 2026 21:00:56 GMT", len(BODY))
    before = datetime.now().astimezone().replace(microsecond=0)
    adopted = adopt_local_file(path, remote, "r7")
    after = datetime.now().astimezone()
    assert (adopted.url, adopted.etag, adopted.last_modified) == (remote.url, remote.etag, remote.last_modified)
    assert adopted.size == len(BODY)
    assert adopted.sha256 == hashlib.sha256(BODY).hexdigest()
    assert Path(adopted.local_path) == path
    assert (adopted.status, adopted.run_key) == ("downloaded", "r7")
    assert before <= datetime.fromisoformat(adopted.downloaded_at) <= after
    assert path.read_bytes() == BODY  # nothing is moved or rewritten


def test_adopting_accepts_an_unknown_remote_size(tmp_path: Path) -> None:
    path = tmp_path / "resource.csv"
    path.write_bytes(BODY)
    adopted = adopt_local_file(path, RemoteMeta("u", None, None, None), "r1")
    assert adopted.size == len(BODY)


def test_adopting_refuses_a_file_of_another_size(tmp_path: Path) -> None:
    path = tmp_path / "resource.csv"
    path.write_bytes(BODY)
    with pytest.raises(DownloadError, match=str(len(BODY) + 1)):
        adopt_local_file(path, RemoteMeta("u", None, None, len(BODY) + 1), "r1")


# --- quarantine -----------------------------------------------------------------------------------


def test_quarantine_moves_the_file_and_tags_it_with_its_hash(tmp_path: Path) -> None:
    path = tmp_path / "raw" / "resource.csv"
    path.parent.mkdir()
    path.write_bytes(BODY)
    sha = hashlib.sha256(BODY).hexdigest()
    target = quarantine(path, tmp_path / "raw" / "quarantine", sha)
    assert not path.exists()
    assert target.parent == tmp_path / "raw" / "quarantine"
    assert target.read_bytes() == BODY
    assert sha[:12] in target.name and target.suffix == ".csv"


def test_quarantining_the_same_content_twice_is_idempotent(tmp_path: Path) -> None:
    sha = hashlib.sha256(BODY).hexdigest()
    qdir = tmp_path / "quarantine"
    targets = []
    for _ in range(2):
        path = tmp_path / "resource.csv"
        path.write_bytes(BODY)
        targets.append(quarantine(path, qdir, sha))
    assert targets[0] == targets[1]
    assert len(list(qdir.iterdir())) == 1
