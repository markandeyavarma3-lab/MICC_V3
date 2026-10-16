"""The BSE shareholding backfill: resumable, and a missing file is not retried."""

from __future__ import annotations

import json

import pytest

from src.archive import bse_shp as B


@pytest.mark.unit
def test_stored_and_missing_filings_are_done_and_failures_are_retried(tmp_path):
    m = tmp_path / "manifest.jsonl"
    for fid, st in (("a", "STORED"), ("b", "MISSING"), ("c", "FAILED")):
        B.record({"filing_id": fid, "status": st}, m)
    assert B.done(m) == {"a", "b"}


@pytest.mark.unit
def test_bse_files_are_dated_by_their_broadcast(tmp_path, monkeypatch):
    from src.ingest import shp
    arch = tmp_path / "archive"
    (arch / "SHP_BSE").mkdir(parents=True)
    (arch / "SHP_BSE" / "manifest.jsonl").write_text(json.dumps(
        {"status": "STORED", "path": "/x/y/INE1_2019-06-30_ab.xml.gz", "broadcast": "2019-07-12T10:00:00"}) + "\n")
    monkeypatch.setattr(shp, "ARCHIVE", arch)
    assert shp.bse_broadcasts() == {"INE1_2019-06-30_ab.xml.gz": "2019-07-12"}
