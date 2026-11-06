"""NSE's current company lists (src/archive/listing.py)."""

from __future__ import annotations

import gzip

import pytest

from src.archive import listing

pytestmark = pytest.mark.unit

MAIN = b"SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, ISIN NUMBER\nABC,Abc Ltd,EQ,06-OCT-2008,INE111A01011\nNOISIN,No Isin Ltd,EQ,06-OCT-2008,\n"
SME = b"SYMBOL,NAME_OF_COMPANY,SERIES,DATE_OF_LISTING,ISIN_NUMBER\nABC,Abc Old,ST,01-Jan-20,INE111A01029\nXYZ,Xyz Ltd,ST,06-Nov-26,INE222B01012\n"


def test_both_files_read_though_they_name_their_columns_differently():
    assert listing.parse(MAIN)["ABC"] == {"isin": "INE111A01011", "co": "Abc Ltd", "listed": "06-OCT-2008"}
    assert listing.parse(SME)["XYZ"]["isin"] == "INE222B01012"
    assert "NOISIN" not in listing.parse(MAIN), "a row without an ISIN identifies nothing"


def test_the_newest_file_is_read_and_the_main_board_wins(tmp_path):
    (tmp_path / "main_2026-11-05.csv.gz").write_bytes(gzip.compress(b"SYMBOL,NAME OF COMPANY,ISIN NUMBER\nOLD,Old Ltd,INE000A01011\n"))
    (tmp_path / "main_2026-11-06.csv.gz").write_bytes(gzip.compress(MAIN))
    (tmp_path / "sme_2026-11-06.csv.gz").write_bytes(gzip.compress(SME))
    got = listing.latest(tmp_path)
    assert got["ABC"]["co"] == "Abc Ltd" and got["XYZ"]["co"] == "Xyz Ltd"
    assert "OLD" not in got, "an older list is superseded, not merged"


def test_no_archive_names_nothing(tmp_path):
    assert listing.latest(tmp_path) == {}
