"""The shareholding-pattern parser: two schemas, one scale, one join key.

Three things went wrong on the first real run and each is pinned here: the
header context is `OneD` in old files and `MainD` in new ones (147,518 rows
with an empty symbol); the holding is a percent in old files and a fraction in
new ones (a factor of 100 across the schema change); and the XBRL's symbol is
the symbol AT FILING TIME, so a rename breaks a symbol join (0069, again).
"""

from __future__ import annotations

import gzip
import json

import pytest

from src.ingest import shp

pytestmark = pytest.mark.unit


def _xbrl(header_ctx: str, isin: str, symbol: str, promoter: str, public: str,
          fpi: str, holders: str = "127") -> bytes:
    """A minimal filing in the real structure: contexts with a category axis,
    facts referencing them, one header context with the ISIN."""
    def ctx(cid, member=None):
        scen = (f'<xbrli:scenario><xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">'
                f'in-bse-shp:{member}</xbrldi:explicitMember></xbrli:scenario>' if member else "")
        return (f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
                f'</xbrli:entity><xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period>{scen}</xbrli:context>')
    def fact(name, cid, val):
        return f'<in-bse-shp:{name} contextRef="{cid}" unitRef="pure">{val}</in-bse-shp:{name}>'
    body = (ctx(header_ctx) + ctx("Prom_I", "ShareholdingOfPromoterAndPromoterGroupMember")
            + ctx("Pub_I", "PublicShareholdingMember") + ctx("FPI_I", "InstitutionsForeignMember")
            + ctx("Detail001I")  # a category-less detail block, NOT the header
            + fact("NameOfTheShareholder", "Detail001I", "SOME HOLDER")
            + fact("ISIN", header_ctx, isin) + fact("Symbol", header_ctx, symbol)
            + fact("NameOfTheCompany", header_ctx, "ACME LTD")
            + fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "Prom_I", promoter)
            + fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "Pub_I", public)
            + fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "FPI_I", fpi)
            + fact("NumberOfShareholders", "FPI_I", holders))
    return gzip.compress(f'<?xml version="1.0"?><xbrli:xbrl>{body}</xbrli:xbrl>'.encode())


def test_the_header_is_found_by_its_isin_whichever_context_holds_it(tmp_path):
    """OneD in 2018-2024, MainD from V1.1. The first context without a category
    is a named-holder detail block in both — guessing it left the symbol empty."""
    for header in ("OneD", "MainD"):
        f = tmp_path / f"{header}.xml.gz"; f.write_bytes(_xbrl(header, "INE000A01010", "ACME", "41.37", "58.63", "6.37"))
        rows = shp.parse_xbrl_file(str(f))
        assert rows and all(r.isin == "INE000A01010" and r.symbol == "ACME" for r in rows), header


def test_a_fraction_scale_filing_is_normalised_to_percent_and_says_so(tmp_path):
    f = tmp_path / "new.xml.gz"; f.write_bytes(_xbrl("MainD", "INE000A01010", "ACME", "0.4137", "0.5863", "0.0637"))
    rows = {r.category: r for r in shp.parse_xbrl_file(str(f))}
    assert rows["ForeignInst_Total"].pct_shares == pytest.approx(6.37)
    assert rows["ForeignInst_Total"].pct_scale_raw == "fraction"


def test_a_percent_scale_filing_is_left_alone_and_says_so(tmp_path):
    f = tmp_path / "old.xml.gz"; f.write_bytes(_xbrl("OneD", "INE000A01010", "ACME", "41.37", "58.63", "6.37"))
    rows = {r.category: r for r in shp.parse_xbrl_file(str(f))}
    assert rows["ForeignInst_Total"].pct_shares == pytest.approx(6.37)
    assert rows["ForeignInst_Total"].pct_scale_raw == "percent"


def test_an_unrecognisable_scale_is_not_guessed(tmp_path):
    """A filing whose promoter+public total is neither ~1 nor ~100 is left on
    its own scale and labelled unknown — a wrong factor of 100 is worse than
    a flagged row."""
    f = tmp_path / "odd.xml.gz"; f.write_bytes(_xbrl("MainD", "INE000A01010", "ACME", "4.1", "5.8", "0.6"))
    rows = {r.category: r for r in shp.parse_xbrl_file(str(f))}
    assert rows["ForeignInst_Total"].pct_scale_raw == "unknown" and rows["ForeignInst_Total"].pct_shares == pytest.approx(0.6)


def test_the_category_less_detail_block_is_not_a_holdings_row(tmp_path):
    f = tmp_path / "x.xml.gz"; f.write_bytes(_xbrl("MainD", "INE000A01010", "ACME", "0.4", "0.6", "0.06"))
    rows = shp.parse_xbrl_file(str(f))
    assert {r.category for r in rows} == {"Promoter", "PublicTotal", "ForeignInst_Total"}
    assert all(r.num_shareholders == 127 for r in rows if r.category == "ForeignInst_Total")


def _master(tmp_path, symbol, isin, quarter="30-Jun-2026", broadcast="15-Jul-2026 19:32:59"):
    d = tmp_path / "SHP" / "NSE" / "year=2026" / "month=09"; d.mkdir(parents=True, exist_ok=True)
    (d / f"SHP_NSE_{symbol}_20260918_abcd1234.json.gz").write_bytes(gzip.compress(json.dumps(
        {"data": [{"symbol": symbol, "isin": isin, "recordId": 1, "date": quarter, "broadcastDate": broadcast,
                   "revisedStatus": "-"}]}).encode()))


def test_broadcast_date_joins_on_isin_so_a_renamed_company_still_matches(tmp_path, monkeypatch):
    """The master was fetched as ANGELONE; the 2021 XBRL says ANGELBRKG. Same
    ISIN. 0069 found this exact class of error keying a partition on the symbol."""
    monkeypatch.setattr(shp, "MASTER_GLOB", str(tmp_path / "SHP" / "NSE" / "**" / "*.json.gz"))
    monkeypatch.setattr(shp, "XBRL_GLOB", str(tmp_path / "SHP_XBRL" / "**" / "*.xml.gz"))
    _master(tmp_path, "ANGELONE", "INE732I01013")
    x = tmp_path / "SHP_XBRL" / "y"; x.mkdir(parents=True)
    (x / "a.xml.gz").write_bytes(_xbrl("MainD", "INE732I01013", "ANGELBRKG", "0.4", "0.6", "0.06"))
    rows = shp.parse()
    assert rows and all(r.broadcast_date == "2026-07-15" for r in rows)


def test_a_filing_with_no_master_row_keeps_its_data_with_an_empty_broadcast_date(tmp_path, monkeypatch):
    monkeypatch.setattr(shp, "MASTER_GLOB", str(tmp_path / "SHP" / "NSE" / "**" / "*.json.gz"))
    monkeypatch.setattr(shp, "XBRL_GLOB", str(tmp_path / "SHP_XBRL" / "**" / "*.xml.gz"))
    x = tmp_path / "SHP_XBRL" / "y"; x.mkdir(parents=True)
    (x / "a.xml.gz").write_bytes(_xbrl("MainD", "INE000A01010", "ORPHAN", "0.4", "0.6", "0.06"))
    rows = shp.parse()
    assert len(rows) == 3 and all(r.broadcast_date == "" for r in rows)


def test_master_dates_parse_both_shapes_and_never_guess():
    assert shp._date("30-JUN-2026") == "2026-06-30"
    assert shp._date("15-Jul-2026 19:32:59") == "2026-07-15"
    assert shp._date("garbage") == "" and shp._date("") == ""


def test_revised_is_the_masters_word_revised_and_not_its_placeholder():
    """`revisedStatus` is "Revised" or "-", never empty. Truthiness read
    4,049 of 4,140 filings as revised; an XBRL element guess read 0."""
    import gzip, json, tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    f = d / "m.json.gz"
    f.write_bytes(gzip.compress(json.dumps({"data": [
        {"symbol": "A", "isin": "I1", "recordId": 1, "date": "30-Jun-2026", "broadcastDate": "15-Jul-2026", "revisedStatus": "-"},
        {"symbol": "A", "isin": "I1", "recordId": 2, "date": "31-Mar-2026", "broadcastDate": "15-Apr-2026", "revisedStatus": "Revised"},
    ]}).encode()))
    got = {fl.record_id: fl.revised for fl in shp.parse_master_file(str(f))}
    assert got == {"1": False, "2": True}


def test_a_filing_with_no_master_row_falls_back_to_the_upload_date_in_its_url(tmp_path, monkeypatch):
    """68 companies changed ISIN in a scheme; their old filings have no master
    row. NSE embeds the upload timestamp in the XBRL filename."""
    monkeypatch.setattr(shp, "MASTER_GLOB", str(tmp_path / "SHP" / "NSE" / "**" / "*.json.gz"))
    monkeypatch.setattr(shp, "XBRL_GLOB", str(tmp_path / "SHP_XBRL" / "**" / "*.xml.gz"))
    monkeypatch.setattr(shp, "ARCHIVE", tmp_path)
    x = tmp_path / "SHP_XBRL" / "y"; x.mkdir(parents=True)
    (x / "orphan.xml.gz").write_bytes(_xbrl("MainD", "INE000A01010", "ORPHAN", "0.4", "0.6", "0.06"))
    (tmp_path / "manifest.jsonl").write_text(json.dumps({
        "source_id": "nse_shp_xbrl", "path": str(x / "orphan.xml.gz"),
        "url": "https://nsearchives.nseindia.com/corporate/xbrl/SHP_1693635_15072026073252_WEB.xml"}) + "\n")
    rows = shp.parse()
    assert rows and all(r.broadcast_date == "2026-07-15" and r.broadcast_source == "xbrl_url" for r in rows)


def test_off_cycle_dates_are_flagged_not_dropped(tmp_path):
    f = tmp_path / "x.xml.gz"
    # _xbrl returns GZIPPED bytes; a replace on the compressed stream matches
    # nothing and the test passes for the wrong reason. Decompress first.
    raw = gzip.decompress(_xbrl("MainD", "INE000A01010", "ACME", "0.4", "0.6", "0.06"))
    f.write_bytes(gzip.compress(raw.replace(b"2026-06-30", b"2026-06-04")))
    rows = shp.parse_xbrl_file(str(f))
    assert rows and all(r.quarter_end == "2026-06-04" and r.is_calendar_quarter is False for r in rows)


def test_the_identity_total_is_carried_per_filing(tmp_path):
    f = tmp_path / "x.xml.gz"; f.write_bytes(_xbrl("MainD", "INE000A01010", "ACME", "0.4137", "0.5863", "0.06"))
    rows = shp.parse_xbrl_file(str(f))
    assert all(r.identity_total == pytest.approx(100.0) for r in rows)
