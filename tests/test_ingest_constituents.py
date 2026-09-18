"""Index constituents as snapshots: membership by ASOF, nothing asserted before the first list."""

from __future__ import annotations

import gzip
import json

import duckdb
import pytest

from src.ingest import constituents as cs

pytestmark = pytest.mark.unit

CSV = "Company Name,Industry,Symbol,Series,ISIN Code\nReliance,Oil,RELIANCE,EQ,INE002A01018\nTCS,IT,TCS,EQ,INE467B01029\n"


def _archive(tmp_path, monkeypatch, entries):
    """entries: (source_id, session_date, csv_text, status)."""
    monkeypatch.setattr(cs, "ARCHIVE", tmp_path)
    monkeypatch.setattr(cs, "MANIFEST", tmp_path / "manifest.jsonl")
    monkeypatch.setattr(cs, "OUT", tmp_path / "out" / "constituents.parquet")
    lines = []
    for i, (sid, d, text, status) in enumerate(entries):
        p = tmp_path / f"f{i}.csv.gz"; p.write_bytes(gzip.compress(text.encode()))
        lines.append(json.dumps({"source_id": sid, "session_date": d, "path": str(p), "status": status}))
    (tmp_path / "manifest.jsonl").write_text("\n".join(lines) + "\n")


def test_the_index_comes_from_the_manifest_not_the_filename(tmp_path, monkeypatch):
    """The 2026-09-15 proof file has no index in its name; reading names would misfile it."""
    _archive(tmp_path, monkeypatch, [("nifty500_constituents", "2026-09-15", CSV, "STORED")])
    rows = cs.parse()
    assert {r.index_key for r in rows} == {"NIFTY500"} and len(rows) == 2
    assert rows[0].industry == "Oil" and rows[0].isin == "INE002A01018"


def test_duplicates_and_failed_rows_are_not_snapshots(tmp_path, monkeypatch):
    _archive(tmp_path, monkeypatch, [
        ("nifty50_constituents", "2026-09-17", CSV, "STORED"),
        ("nifty50_constituents", "2026-09-18", CSV, "DUPLICATE"),   # unchanged list: no new snapshot
        ("nifty50_constituents", "2026-09-19", "<html>", "FAILED"),
    ])
    assert {r.snapshot_date for r in cs.parse()} == {"2026-09-17"}


def test_membership_is_asof_and_asserts_nothing_before_the_first_snapshot(tmp_path, monkeypatch):
    """A rebalance on 09-20 drops TCS. Membership on 09-18 is the 09-17 list;
    on 09-21 it is the 09-20 list; on 09-10 there is NO list."""
    later = "Company Name,Industry,Symbol,Series,ISIN Code\nReliance,Oil,RELIANCE,EQ,INE002A01018\n"
    _archive(tmp_path, monkeypatch, [
        ("nifty50_constituents", "2026-09-17", CSV, "STORED"),
        ("nifty50_constituents", "2026-09-20", later, "STORED"),
    ])
    cs.write(cs.parse())
    con = duckdb.connect()
    con.execute("CREATE TABLE dates AS SELECT * FROM (VALUES (DATE '2026-09-10'), (DATE '2026-09-18'), (DATE '2026-09-21')) t(d)")
    got = con.execute(cs.membership_sql("NIFTY50", cs.OUT)).df()
    got["d"] = got["d"].astype(str)
    by = got.groupby("d")["isin"].apply(set).to_dict()
    assert set(by) == {"2026-09-18", "2026-09-21"}   # 09-10: no rows
    assert len(by["2026-09-18"]) == 2 and len(by["2026-09-21"]) == 1
