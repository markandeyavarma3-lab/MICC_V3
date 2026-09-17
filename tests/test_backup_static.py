"""The static leg: one verified copy of the 9.1 GB that never changes.

backup.sh excluded data/raw/{salvaged,v1_export,v1_increments} on the grounds
that they were "still in MICCV2". MICCV2 was deleted 2026-09-01. For sixteen
days the only copy was this Mac's disk, and the comment stayed. This leg is
fingerprint-driven and verifies by stat of known paths, because under launchd
the iCloud folder cannot be listed (prune_generations.zsh, 0053).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.common.paths import ROOT

pytestmark = pytest.mark.unit

SYNC = ROOT / "scripts" / "lib" / "static_sync.zsh"


def _tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    (repo / "data/raw/salv").mkdir(parents=True)
    (repo / "data/raw/salv/a.parquet").write_bytes(b"hello\n")
    (repo / "data/raw/salv/b.parquet").write_bytes(b"xx")
    (repo / "data/raw/salv/c d.parquet").write_bytes(b"z\n")  # a space, on purpose
    return repo, tmp_path / "dest", tmp_path / "stamp"


def _run(repo, dest, stamp):
    return subprocess.run([str(SYNC), str(repo), str(dest), str(stamp), "data/raw/salv"],
                          capture_output=True, text=True)


def test_first_run_copies_verifies_and_stamps(tmp_path):
    repo, dest, stamp = _tree(tmp_path)
    r = _run(repo, dest, stamp)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SYNCED" in r.stdout and "3 files" in r.stdout
    assert (dest / "data/raw/salv/c d.parquet").read_bytes() == b"z\n"
    line = stamp.read_text().strip().split("\t")
    assert line[1] == str(dest) and line[3] == "3" and line[4] == "10"


def test_second_run_verifies_by_stat_and_copies_nothing(tmp_path):
    repo, dest, stamp = _tree(tmp_path)
    _run(repo, dest, stamp)
    before = (dest / "data/raw/salv/a.parquet").stat().st_mtime_ns
    r = _run(repo, dest, stamp)
    assert r.returncode == 0 and "in sync" in r.stdout and "SYNCED" not in r.stdout
    assert (dest / "data/raw/salv/a.parquet").stat().st_mtime_ns == before


def test_a_stamp_is_never_trusted_without_re_verifying(tmp_path):
    """A destination can be wiped, unmounted and replaced, or half-restored.
    The stamp says what WAS true; stat says what is."""
    repo, dest, stamp = _tree(tmp_path)
    _run(repo, dest, stamp)
    (dest / "data/raw/salv/b.parquet").write_bytes(b"corrupted")
    r = _run(repo, dest, stamp)
    assert r.returncode == 0
    assert "fail verification" in r.stdout and "re-syncing" in r.stdout
    assert (dest / "data/raw/salv/b.parquet").read_bytes() == b"xx"


def test_a_wiped_destination_is_resynced_not_reported_in_sync(tmp_path):
    repo, dest, stamp = _tree(tmp_path)
    _run(repo, dest, stamp)
    import shutil
    shutil.rmtree(dest)
    r = _run(repo, dest, stamp)
    assert r.returncode == 0 and "SYNCED" in r.stdout
    assert (dest / "data/raw/salv/a.parquet").exists()


def test_an_unwritable_destination_exits_nonzero(tmp_path):
    """Exit 0 here would let backup.sh print GREEN over a copy that does not exist."""
    repo, _, stamp = _tree(tmp_path)
    ro = tmp_path / "ro"; ro.mkdir(); ro.chmod(0o500)
    try:
        r = _run(repo, ro / "x", stamp)
        assert r.returncode == 1 and "cannot create" in r.stdout
        assert not stamp.exists()
    finally:
        ro.chmod(0o700)


def test_a_missing_source_directory_is_a_usage_error_not_a_silent_empty_sync(tmp_path):
    repo, dest, stamp = _tree(tmp_path)
    r = subprocess.run([str(SYNC), str(repo), str(dest), str(stamp), "data/raw/nope"],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "missing" in r.stdout
