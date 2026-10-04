"""The two sources the exit classifier reads (decision 0082): NSE's delisted
list and the all-series listing history built from the full bhavcopy."""

from __future__ import annotations

import pytest

from src.archive import delisted
from src.ingest import listing_history as lh

pytestmark = pytest.mark.unit


# --- NSE delisted.csv -------------------------------------------------------------

_CSV = ("Symbol,Company,Delisted Date,Type of Delisting,,,,,\n"
        "HEXAWARE,Hexaware Technologies Limited,09-Nov-20,Voluntary Delisting ,,,,,\n"
        "ANIKSHIP,Anik Ship Breaking Industries Ltd.,26-Jul-04,Compulsory Delisting ,,,,,\n"
        "RASOYPR,Rasoya Proteins Limited,10-Jul-20,Delisting - Liquidation,,,,,\n"
        "ODDCO,Soci\xe9t\xe9 Odd Ltd,01-Jan-19,Some New Type,,,,,\n").encode("latin-1")


def test_each_nse_type_maps_to_the_plans_reason():
    got = {r["symbol"]: r for r in delisted.parse(_CSV)}
    assert got["HEXAWARE"]["reason"] == "ACQUISITION"
    assert got["ANIKSHIP"]["reason"] == "SUSPENSION"
    assert got["RASOYPR"]["reason"] == "SUSPENSION"
    assert got["HEXAWARE"]["delisted_on"] == "2020-11-09"


def test_an_unknown_type_is_kept_with_no_reason_not_dropped_or_guessed():
    got = {r["symbol"]: r for r in delisted.parse(_CSV)}
    assert got["ODDCO"]["reason"] is None and got["ODDCO"]["type"] == "Some New Type"


def test_the_windows_1252_file_parses():
    """NSE serves this file in a single-byte encoding; utf-8 fails on it."""
    assert "Soci" in {r["symbol"]: r for r in delisted.parse(_CSV)}["ODDCO"]["company"]


# --- the listing history ------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("cm01AUG2012bhav.csv.zip", ("2012-08-01", "legacy")),
    ("sec_bhavdata_full_14052024.csv", ("2024-05-14", "secfull")),
    ("BhavCopy_NSE_CM_0_0_0_20250102_F_0000.csv.zip", ("2025-01-02", "udiff")),
    ("PRICE_NSE_20261001_ccc5fb27.csv.zip.gz", ("2026-10-01", "archive")),
    ("MTO_01022005.DAT", None),
])
def test_every_bhavcopy_name_dates_its_session(name, expected):
    assert lh.session_of(f"/x/{name}") == expected


def test_one_file_per_session_by_precedence(monkeypatch):
    paths = ["/b/legacy/2024/cm14MAY2024bhav.csv.zip",
             "/b/secfull/2024/sec_bhavdata_full_14052024.csv",
             "/b/udiff/2024/BhavCopy_NSE_CM_0_0_0_20240514_F_0000.csv.zip",
             "/b/secfull/2024/sec_bhavdata_full_15052024.csv"]
    monkeypatch.setattr(lh.glob, "glob", lambda pattern, recursive=False:
                        [p for p in paths if f"/{pattern.split('/')[-3]}/" in p] if "PRICE" not in pattern else [])
    chosen, skipped = lh.files()
    assert chosen["2024-05-14"][1] == "udiff"
    assert chosen["2024-05-15"][1] == "secfull"
    assert skipped == 2


def test_a_corrupt_session_file_is_skipped_when_reading_closes(tmp_path, monkeypatch):
    """sec_bhavdata_full_08082022.csv raises csv.Error mid-iteration; the first
    closes() caught errors only on opening and crashed exp_004's plumbing run."""
    good = tmp_path / "sec_bhavdata_full_02012024.csv"
    good.write_text("SYMBOL, SERIES, DATE1, CLOSE_PRICE\nPPAP, BE, 02-Jan-2024, 290.5\n")
    bad = tmp_path / "sec_bhavdata_full_03012024.csv"
    # An unquoted bare carriage return: the exact csv.Error the real file raises.
    bad.write_bytes(b'SYMBOL, SERIES, DATE1, CLOSE_PRICE\nPPAP, B\rE, 03-Jan-2024, 1\n')
    monkeypatch.setattr(lh, "files", lambda: ({"2024-01-02": (str(good), "secfull"),
                                              "2024-01-03": (str(bad), "secfull")}, 0))
    got = lh.closes({"PPAP"}, "2024-01-01", "2024-01-31")
    assert got == [("PPAP", "BE", "", "2024-01-02", 290.5)]
