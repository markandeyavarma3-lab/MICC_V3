"""The website export (src/site/export.py, docs/plan/WEBSITE_PLAN.md).

What the public site may show is a legal line as much as a design one: no
forward return, no ranking by returns, nothing from Kite (decisions 0086,
0087). These tests hold that line on the files themselves."""

from __future__ import annotations

import gzip
import inspect
import json

import duckdb
import pytest

from src.site import export as X

pytestmark = pytest.mark.unit


@pytest.fixture
def wh(tmp_path, monkeypatch):
    from src.common import migrate
    db = tmp_path / "w.duckdb"
    migrate.migrate_duckdb(db)
    con = duckdb.connect(str(db))
    con.execute("INSERT INTO deal_source_files (source_file_id, exchange, report_type, source_url,"
                " report_date, downloaded_at, file_name, file_hash, file_bytes, parser_version, ingestion_status)"
                " VALUES (1, 'NSE', 'BULK', 'x', DATE '2026-10-09', now(), 'f', 'h', 1, 't', 'OK')")
    con.execute("INSERT INTO security_master (security_id, isin, canonical_symbol, company_name, source, confidence,"
                " status) VALUES (7, 'INE000A01010', 'ACME', 'Acme Ltd', 'test', 'HIGH', 'ACTIVE')")
    for rid, name, side in ((1, "SBI Mutual Fund.", "BUY"), (2, "FAST MAKER", "BUY"), (3, "FAST MAKER", "SELL")):
        con.execute("INSERT INTO institutional_deals_raw (raw_deal_id, source_file_id, exchange, deal_type,"
                    " trade_date, symbol_raw, client_name_raw, side_raw, quantity_raw, deal_price_raw,"
                    " raw_row_json, row_index, ingested_at) VALUES (?,1,'NSE','BULK',DATE '2026-10-09','ACME',?,?,"
                    "'1000','100','{}',?,now())", [rid, name, side, rid])
        con.execute("INSERT INTO institutional_deals_clean (deal_id, raw_deal_id, security_id, trade_date,"
                    " available_from, available_from_confidence, entry_date, exchange, deal_type, side, quantity,"
                    " deal_price, gross_deal_value, same_day_round_trip_flag, five_day_round_trip_flag,"
                    " internal_transfer_flag, promoter_related_flag, suspect_flag, unresolved_symbol_flag,"
                    " uncovered_symbol_flag, eligible_for_research, clean_version, created_at)"
                    " VALUES (?,?,7,DATE '2026-10-09',DATE '2026-10-10','HIGH',DATE '2026-10-10','NSE','BULK',?,"
                    " 1000,100,?,?,false,false,false,false,false,false,?,'t',now())",
                    [rid, rid, side, 1e8 * rid, name == "FAST MAKER", name != "FAST MAKER"])
    con.execute("INSERT INTO participant_master (participant_id, canonical_name, participant_type,"
                " classification_method, confidence_level, review_status) VALUES"
                " (1, 'SBI MUTUAL FUND', 'MUTUAL_FUND', 'NAME_PATTERN', 'HIGH', 'AUTO'),"
                " (2, 'FAST MAKER', 'PROP_HFT', 'BEHAVIOURAL', 'HIGH', 'AUTO')")
    con.execute("INSERT INTO participant_aliases (alias_id, participant_id, raw_name, normalized_name,"
                " mapping_method, mapping_confidence, review_status) VALUES"
                " (1, 1, 'SBI Mutual Fund.', 'SBI MUTUAL FUND', 'EXACT', 'HIGH', 'AUTO'),"
                " (2, 2, 'FAST MAKER', 'FAST MAKER', 'EXACT', 'HIGH', 'AUTO')")
    con.close()
    monkeypatch.setattr(X, "research_db", lambda env=None: db)
    arch = tmp_path / "archive" / "FII_DII"
    arch.mkdir(parents=True)
    (arch / "x.json.gz").write_bytes(gzip.compress(json.dumps([
        {"buyValue": "100", "category": "FII/FPI", "date": "09-Oct-2026", "netValue": "-35.5", "sellValue": "135.5"},
        {"buyValue": "90", "category": "DII", "date": "09-Oct-2026", "netValue": "20", "sellValue": "70"}]).encode()))
    monkeypatch.setattr(X, "ARCHIVE", tmp_path / "archive")
    monkeypatch.setattr(X, "_health", lambda: [])
    monkeypatch.setattr(X, "warehouse_dir", lambda env=None: tmp_path / "warehouse")
    monkeypatch.setattr(X, "COLLECTED", tmp_path / "collected")
    from src.ingest import shp_holders
    monkeypatch.setattr(shp_holders, "OUT", tmp_path / "collected" / "shp" / "none.parquet")
    return tmp_path


def test_a_session_file_carries_labelled_deals_flows_and_counts(wh):
    out = wh / "site"
    meta = X.export(out)
    assert meta["latest_session"] == "2026-10-09" and meta["deals"] == 3
    s = json.loads((out / "sessions" / "2026-10-09.json").read_text())
    rows = [dict(zip(s["cols"], r, strict=True)) for r in s["rows"]]
    by_client = {r["client"]: r for r in rows}
    assert by_client["SBI Mutual Fund."]["who"] == "SBI MUTUAL FUND"
    assert by_client["SBI Mutual Fund."]["label"] == "Mutual fund" and not by_client["SBI Mutual Fund."]["rt"]
    assert by_client["FAST MAKER"]["type"] == "PROP_HFT" and by_client["FAST MAKER"]["rt"]
    assert s["flows"]["FII"]["netValue"] == -35.5 and s["flows"]["DII"]["netValue"] == 20
    assert s["roundtrip_share"] == pytest.approx(2 / 3, abs=1e-3)
    idx = json.loads((out / "sessions.json").read_text())
    assert idx[0]["date"] == "2026-10-09" and idx[0]["deals"] == 3


def _fields(o, acc: set) -> set:
    """Every key and every column name in a document — the FIELDS it publishes."""
    if isinstance(o, dict):
        acc.update(k.lower() for k in o)
        if isinstance(o.get("cols"), list):
            acc.update(str(c).lower() for c in o["cols"])
        for v in o.values():
            _fields(v, acc)
    elif isinstance(o, list):
        for v in o:
            _fields(v, acc)
    return acc


def test_nothing_published_carries_a_return_or_a_kite_field(wh):
    """On FIELD names, not values: a fund may be called '... Total Return Fund'."""
    out = wh / "site"
    X.export(out)
    fields = set()
    for p in out.rglob("*.json"):
        _fields(json.loads(p.read_text()), fields)
    for f in fields:
        for banned in ("ret", "return", "excess", "alpha", "kite", "signal", "perf", "pnl", "gain"):
            assert banned not in f.split("_") and not f.startswith(banned), f'field "{f}" looks like {banned}'
    assert {"sym", "cr", "rt"} <= fields                     # the check is reading real fields


def test_the_exporter_reads_no_kite_table_and_no_outcome_table():
    """Code, not prose: the docstring names Kite to say it is banned."""
    src = inspect.getsource(X)
    code = src.split('"""', 2)[2]                       # drop the module docstring
    for banned in ("archive import kite", "kite_daily", "/ \"KITE\"", "price_audit",
                   "deal_forward_outcomes", "outcome_benchmark_returns"):
        assert banned not in code, banned


def test_stock_and_participant_files_are_written_and_indexed(wh):
    out = wh / "site"
    meta = X.export(out)
    assert meta["stocks"] == 1 and meta["participants"] == 2
    acme = json.loads((out / "stocks" / "ACME.json").read_text())
    assert acme["co"] == "Acme Ltd" and len(acme["deals"]["rows"]) == 3
    fast = json.loads((out / "participants" / f"{X.slug('FAST MAKER')}.json").read_text())
    assert fast["stats"]["roundtrip_share"] == 1.0 and fast["label"] == "HFT / round-trip"
    idx = json.loads((out / "participants.json").read_text())
    assert {r[0] for r in idx} == {"SBI MUTUAL FUND", "FAST MAKER"}


def test_a_fund_house_key_is_shown_as_a_name():
    assert X.house_name("FUND HOUSE SBI_FUNDS") == "SBI Funds"
    assert X.house_name("FUND HOUSE NIPPON_INDIA_AMC") == "Nippon India AMC"
    assert X.house_name(None) is None


def test_markets_and_insights_are_written_and_carry_no_return(wh):
    out = wh / "site"
    X.export(out)
    m = json.loads((out / "markets.json").read_text())
    i = json.loads((out / "insights.json").read_text())
    assert m["fii_dii"]["rows"] == [["2026-10-09", -35.5, 20.0]]
    assert "oi_index_futures" in m
    assert i["roundtrip_by_year"]["rows"] == [["2026", 3, 2]]
    assert i["value_by_year_type"]["rows"] == [["2026", "MUTUAL_FUND", 10.0, 0.0]]   # the round trips are excluded
