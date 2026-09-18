"""The all-index close table: long, dated twice, seed-identical where they overlap."""

from __future__ import annotations

import gzip

import pytest

from src.ingest import index_close as ic

pytestmark = pytest.mark.unit

HDR = "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"


def _file(tmp_path, session_ymd, body):
    d = tmp_path / "INDEX_CLOSE" / "NSE" / "year=2026" / "month=09"; d.mkdir(parents=True, exist_ok=True)
    f = d / f"INDEX_CLOSE_NSE_{session_ymd}_abcd1234.csv.gz"
    f.write_bytes(gzip.compress((HDR + body).encode()))
    return f


def test_rows_are_long_keyed_and_numbers_parsed_as_nse_writes_them(tmp_path):
    f = _file(tmp_path, "20260917", "Nifty 50,17-09-2026,23195.25,23363.55,23193.65,23270.6,53.0,.23,259700999,18775.3,19.67,2.81,1.22\n"
                                     "Nifty 500,17-09-2026,1,2,3,4,-,-,-,-,-,-,-\n")
    rows = ic.parse_file(str(f))
    assert [(r.index_key, r.date) for r in rows] == [("NIFTY50", "2026-09-17"), ("NIFTY500", "2026-09-17")]
    assert rows[0].change_pct == pytest.approx(0.23) and rows[0].close == pytest.approx(23270.6)
    assert rows[1].pe is None and rows[1].close == 4.0


def test_a_row_whose_date_disagrees_with_the_files_session_is_refused():
    """Three April-2023 files carry the date MM-DD. The archive checked the
    first row; a file that lies internally must not land under the wrong day."""
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp())
    f = _file(tmp, "20230406", "Nifty 50,04-06-2023,1,1,1,1,0,0,0,0,0,0,0\nNifty 500,06-04-2023,1,1,1,2,0,0,0,0,0,0,0\n")
    rows = ic.parse_file(str(f))
    assert [r.index_key for r in rows] == ["NIFTY500"]  # the DD-MM row that matches the session


def test_index_key_matches_the_seeds_symbol_convention():
    assert ic.index_key("Nifty 50") == "NIFTY50"
    assert ic.index_key("Nifty Smallcap 250") == "NIFTYSMALLCAP250"
    assert ic.index_key("NIFTY IT") == "NIFTYIT"


def test_a_session_archived_twice_keeps_one_row_per_index(tmp_path, monkeypatch):
    monkeypatch.setattr(ic, "GLOB", str(tmp_path / "INDEX_CLOSE" / "**" / "*.csv.gz"))
    monkeypatch.setattr(ic, "OUT", tmp_path / "out" / "index_close.parquet")
    _file(tmp_path, "20260917", "Nifty 50,17-09-2026,1,1,1,100,0,0,0,0,0,0,0\n")
    d = tmp_path / "INDEX_CLOSE" / "NSE" / "year=2026" / "month=09"
    (d / "INDEX_CLOSE_NSE_20260917_ffff0000.csv.gz").write_bytes(gzip.compress((HDR + "Nifty 50,17-09-2026,1,1,1,101,0,0,0,0,0,0,0\n").encode()))
    ic.write(ic.parse())
    import duckdb
    got = duckdb.connect().sql(f"select close from read_parquet('{ic.OUT}')").fetchall()
    assert len(got) == 1 and got[0][0] == 101.0  # the later archive (name sorts last) wins
