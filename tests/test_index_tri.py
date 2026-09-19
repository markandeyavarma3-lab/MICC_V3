"""NIFTY 500 total return: the collector's request and the parser's table.

Context: benchmarks.yml has named NIFTY500_TR as the headline market leg since
the project began, and pointed it at a table that did not exist. 32 slices were
probed on 2026-09-15 and then nothing — a probe is not a collector, and the
series stopped the day it was found. These pin the request the host actually
answers, the window arithmetic a backfill depends on, and the rule that decides
which slice's value a date keeps.
"""

from __future__ import annotations

import gzip
import json
from datetime import date, timedelta

import pytest

from src.archive import index_tri as col
from src.ingest import index_tri as ing

pytestmark = pytest.mark.unit


# --- the collector ---------------------------------------------------------------


def test_the_post_body_is_a_string_holding_a_js_literal_not_nested_json():
    """The host answers [] with a 200 to a proper JSON object under `cinfo`.
    What it parses is a STRING of single-quoted JS — found by reading the
    page's own script on 2026-09-15."""
    body = json.loads(col.body_for(date(1995, 1, 1), date(1995, 9, 22)))
    assert set(body) == {"cinfo"}
    assert body["cinfo"] == ("{'name':'NIFTY 500','startDate':'01-Jan-1995',"
                             "'endDate':'22-Sep-1995','indexName':'NIFTY 500'}")


def test_a_backfill_is_cut_into_windows_of_at_most_a_year():
    """The host serves at most one year per request; a longer window is []."""
    w = col.windows(date(2024, 1, 1), date(2026, 9, 19))
    assert w[0] == (date(2024, 1, 1), date(2024, 12, 30))
    assert w[-1][1] == date(2026, 9, 19)
    assert all((hi - lo).days < col.MAX_WINDOW_DAYS for lo, hi in w)
    assert all(w[i + 1][0] == w[i][1] + timedelta(days=1) for i in range(len(w) - 1))  # contiguous
    assert col.windows(date(2026, 9, 19), date(2026, 9, 1)) == []


def test_the_daily_topup_asks_for_a_45_day_window_ending_today(monkeypatch):
    """Six weeks of overlap: a fortnight of missed evenings costs nothing."""
    asked = []
    monkeypatch.setattr(col, "fetch_window", lambda lo, hi, dry_run=False: asked.append((lo, hi)) or {})
    col.collect(today=date(2026, 9, 19))
    assert asked == [(date(2026, 8, 5), date(2026, 9, 19))]


def test_the_topup_never_asks_before_the_hosts_first_session(monkeypatch):
    asked = []
    monkeypatch.setattr(col, "fetch_window", lambda lo, hi, dry_run=False: asked.append((lo, hi)) or {})
    col.collect(start=date(1990, 1, 1), end=date(1995, 3, 1))
    assert asked[0][0] == col.EARLIEST


def test_an_empty_list_is_a_failure_not_an_empty_day(monkeypatch, tmp_path):
    """[] is what the host says for a window it does not serve. On a window
    that should hold 30 sessions it is a change on the host, and a manifest
    that recorded it as a quiet day would hide exactly that."""
    from src.archive import probe
    monkeypatch.setattr(probe, "fetch", lambda url, headers=None, data=None, retries=1: (200, b"[]", ""))
    r = col.fetch_window(date(2026, 8, 5), date(2026, 9, 19), dry_run=True)
    assert r["status"] == "FAILED"
    assert "0 items" in r["error"]
    assert r["request_startDate"] == "05-Aug-2026" and r["session_date"] == "2026-09-19"


# --- the parser --------------------------------------------------------------------


def _slice(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(json.dumps([{"RequestNumber": "TRI1", "Index Name": "Nifty 500", "Date": d,
                              "TotalReturnsIndex": v, "NTR_Value": n} for d, v, n in rows]).encode())


def test_rows_are_parsed_as_the_host_writes_them(tmp_path):
    p = tmp_path / "INDEX_TRI_NSE_19950922_aa.json.gz"
    _slice(p, [("22 Sep 1995", "742.26", "-"), ("01 Jan 1995", "1000.00", "-"), ("bad", "1", "-")])
    rows = ing.parse_file(str(p))
    assert [(r.date, r.tri, r.ntr) for r in rows] == [("1995-09-22", 742.26, None), ("1995-01-01", 1000.0, None)]
    assert rows[0].index_key == "NIFTY500" and rows[0].index_name == "Nifty 500"


def test_a_date_served_by_two_slices_keeps_the_later_slices_value(tmp_path, monkeypatch):
    """A backfill slice and a daily top-up both contain last Tuesday. The
    top-up was archived later and wins; `source_file` says so."""
    duckdb = pytest.importorskip("duckdb")
    monkeypatch.setattr(ing, "GLOB", str(tmp_path / "INDEX_TRI" / "**" / "*.json.gz"))
    monkeypatch.setattr(ing, "OUT", tmp_path / "out" / "index_tri.parquet")
    _slice(tmp_path / "INDEX_TRI" / "NSE" / "INDEX_TRI_NSE_20260910_aa.json.gz",
           [("10 Sep 2026", "36918.52", "30000.1"), ("09 Sep 2026", "36800.00", "29900.0")])
    _slice(tmp_path / "INDEX_TRI" / "NSE" / "INDEX_TRI_NSE_20260919_bb.json.gz",
           [("18 Sep 2026", "37100.00", "30100.0"), ("10 Sep 2026", "36919.00", "30000.2")])
    out = ing.write(ing.parse())
    got = duckdb.sql(f"SELECT date, tri, source_file FROM read_parquet('{out}') ORDER BY date").fetchall()
    assert [(str(d), v) for d, v, _ in got] == [("2026-09-09", 36800.0), ("2026-09-10", 36919.0), ("2026-09-18", 37100.0)]
    assert got[1][2].startswith("INDEX_TRI_NSE_20260919")
