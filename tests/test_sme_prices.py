"""SME-platform closes from the bhavcopies, for the site only (src/site/sme_prices.py)."""

from __future__ import annotations

import duckdb
import pytest

from src.site import export as X
from src.site import sme_prices as M

pytestmark = pytest.mark.unit

UDIFF = "TradDt,TckrSymb,SctySrs,ClsPric\n2026-11-06,IEML,ST,34.85\n2026-11-06,TCS,EQ,3000\n"
SECFULL = "SYMBOL, SERIES, DATE1, CLOSE_PRICE\nJAYBEE, SM, 02-Jan-2024, 79.9\nGOLD, GB, 02-Jan-2024, 5000\n"
LEGACY = "SYMBOL,SERIES,CLOSE,TIMESTAMP\nOLDSME,SM,12.5,02-NOV-2012\nACC,EQ,1000,02-NOV-2012\n"


def test_all_three_layouts_read_and_only_sme_rows_are_kept():
    assert M.rows_of(UDIFF) == [("IEML", "2026-11-06", 34.85, "ST")]
    assert M.rows_of(SECFULL) == [("JAYBEE", "2024-01-02", 79.9, "SM")]
    assert M.rows_of(LEGACY) == [("OLDSME", "2012-11-02", 12.5, "SM")]


def test_a_row_with_no_usable_close_is_dropped():
    assert M.rows_of("TradDt,TckrSymb,SctySrs,ClsPric\n2026-11-06,IEML,ST,-\n2026-11-06,XYZ,ST,0\n") == []


def test_an_empty_baseline_is_refused_rather_than_kept_for_good(monkeypatch, tmp_path):
    """A wrong path once wrote an empty baseline in 17 seconds, and it would have
    been trusted on every later run."""
    monkeypatch.setattr(M, "BASELINE", tmp_path / "base.parquet")
    monkeypatch.setattr(M, "_salvaged_files", lambda: [])
    with pytest.raises(FileNotFoundError):
        M.build()
    assert not (tmp_path / "base.parquet").exists()


def test_weekly_takes_each_week_s_last_close(tmp_path):
    p = tmp_path / "p.parquet"
    con = duckdb.connect()
    con.execute("""CREATE TABLE t AS SELECT * FROM (VALUES
        ('X', '2026-11-02', 10.0, 'SM'), ('X', '2026-11-06', 11.0, 'SM'), ('X', '2026-11-09', 12.0, 'SM'))
        v(symbol, date, close, series)""")
    con.execute(f"COPY t TO '{p}' (FORMAT PARQUET)")
    assert M.weekly(p) == {"X": [["2026-11-06", 11.0], ["2026-11-09", 12.0]]}
    assert M.weekly(tmp_path / "absent") == {}


def test_nothing_in_research_reads_these_prices():
    """Unadjusted closes must not reach an adjusted-price study."""
    import pathlib
    for f in pathlib.Path("src/research").rglob("*.py"):
        assert "sme_prices" not in f.read_text(), f
    assert X.sme_prices is M
