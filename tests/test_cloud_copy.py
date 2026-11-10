"""The cloud copy check: a copy that differs in any file must be reported."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_copy", ROOT / "cloud" / "verify_copy.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)


def _tree(base: Path, files: dict[str, bytes]) -> None:
    for rel, body in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)


@pytest.mark.unit
def test_identical_copies_match_and_skips_scratch_files(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _tree(a, {"data/x.parquet": b"one", "data/sub/y.csv": b"two", "data/.DS_Store": b"z", "data/q.partial": b"p"})
    _tree(b, {"data/x.parquet": b"one", "data/sub/y.csv": b"two"})
    ma, mb = V.manifest([a / "data"], a), V.manifest([b / "data"], b)
    assert set(ma["files"]) == {"data/x.parquet", "data/sub/y.csv"}
    assert not any(V.compare(ma, mb).values())


@pytest.mark.unit
def test_a_missing_extra_or_changed_file_is_reported(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _tree(a, {"data/x": b"one", "data/y": b"two", "data/z": b"three"})
    _tree(b, {"data/x": b"one", "data/y": b"TWO", "data/w": b"new"})
    d = V.compare(V.manifest([a / "data"], a), V.manifest([b / "data"], b))
    assert d["missing"] == ["data/z"]
    assert d["extra"] == ["data/w"]
    # Same size, different content: only the hash catches it.
    assert d["different"] == ["data/y"]


@pytest.mark.unit
def test_duckdb_row_counts_are_compared(tmp_path):
    import duckdb
    for side, n in (("a", 3), ("b", 2)):
        (tmp_path / side / "db").mkdir(parents=True)
        con = duckdb.connect(str(tmp_path / side / "db" / "r.duckdb"))
        con.execute(f"CREATE TABLE t AS SELECT * FROM range({n})")
        con.close()
    ma = V.manifest([tmp_path / "a" / "db"], tmp_path / "a")
    mb = V.manifest([tmp_path / "b" / "db"], tmp_path / "b")
    assert ma["tables"]["db/r.duckdb"] == {"main.t": 3}
    assert V.compare(ma, mb)["table_rows"] == ["db/r.duckdb main.t: 3 vs 2"]


@pytest.mark.unit
def test_sync_copies_into_a_folder_with_spaces_and_refuses_an_unsaved_database(tmp_path):
    repo = tmp_path / "institutional research"
    _tree(repo, {"data/raw/a.csv": b"1", "data/raw/b.partial": b"x", "db/r.duckdb": b"db"})
    _tree(tmp_path / "research website", {"src/index.astro": b"<p/>", "node_modules/m.js": b"m"})
    dest = tmp_path / "server copy"
    env = {**os.environ, "MICC_REPO": str(repo), "MICC_DEST": str(dest)}
    r = subprocess.run(["zsh", str(ROOT / "cloud" / "sync_up.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (dest / "research" / "data" / "raw" / "a.csv").read_bytes() == b"1"
    assert not (dest / "research" / "data" / "raw" / "b.partial").exists()
    assert (dest / "website" / "src" / "index.astro").exists()
    assert not (dest / "website" / "node_modules").exists()
    (repo / "db" / "r.duckdb.wal").write_bytes(b"w")
    r = subprocess.run(["zsh", str(ROOT / "cloud" / "sync_up.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "unsaved changes" in r.stdout
