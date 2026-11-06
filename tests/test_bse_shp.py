"""The BSE shareholding backfill: resumable, and a missing file is not retried."""

from __future__ import annotations

import json

import duckdb
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


@pytest.mark.unit
def test_a_quarter_nse_already_covers_is_not_fetched_again_from_bse(monkeypatch, tmp_path):
    """Inside NSE's window only what no filing of the issuer covers; before it, all."""
    (tmp_path / "shp").mkdir()
    con = duckdb.connect()
    con.execute("CREATE TABLE h AS SELECT 'INE111A01011' AS isin, '2023-03-31' AS quarter_end")
    con.execute(f"COPY h TO '{tmp_path}/shp/shp_holdings.parquet' (FORMAT PARQUET)")
    monkeypatch.setattr(B, "COLLECTED", tmp_path)
    con.execute("""CREATE TABLE s AS SELECT * FROM (VALUES
        ('INE111A01011', '2023-03-31'), ('INE111A01029', '2023-03-31'), ('INE111A01011', '2023-06-30'),
        ('INE111A01011', '2019-03-31')) v(isin, quarter_end_date)""")
    got = con.execute(f"SELECT isin, quarter_end_date FROM s WHERE {B._needed_sql()} ORDER BY 2").fetchall()
    assert got == [("INE111A01011", "2019-03-31"), ("INE111A01011", "2023-06-30")]
