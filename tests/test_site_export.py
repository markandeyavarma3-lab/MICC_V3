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
    from src.ingest import mf_portfolios
    monkeypatch.setattr(mf_portfolios, "OUT", tmp_path / "collected" / "mf" / "none.parquet")
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


def test_market_structure_reaches_the_stock_file_and_the_filings_feed(wh):
    arch = wh / "archive"
    for rep, rows in (("CORPACT", [{"symbol": "ACME", "exDate": "05-Jun-2026", "recDate": "05-Jun-2026",
                                     "subject": "Dividend - Rs 6 Per Share"}]),
                      ("ANNOUNCE", [{"symbol": "ACME", "sort_date": "2026-10-09 12:00:00", "desc": "Credit Rating",
                                      "attchmntText": "Acme has informed", "attchmntFile": "https://x/y.pdf",
                                      "seq_id": "1", "sm_name": "Acme Ltd", "smIndustry": "Widgets"}]),
                      ("BOARDMTG", [{"bm_symbol": "ACME", "bm_date": "30-Dec-2099", "bm_purpose": "Financial Results",
                                      "bm_desc": "To consider results", "sm_indusrty": "-"}])):
        d = arch / rep / "NSE" / "year=2026"
        d.mkdir(parents=True)
        (d / f"{rep}_1.json.gz").write_bytes(gzip.compress(json.dumps(rows).encode()))
    out = wh / "site"
    X.export(out)
    acme = json.loads((out / "stocks" / "ACME.json").read_text())
    assert acme["actions"]["rows"] == [["2026-06-05", "Dividend - Rs 6 Per Share", "2026-06-05"]]
    assert acme["announcements"]["rows"][0][1] == "Credit Rating" and acme["industry"] == "Widgets"
    f = json.loads((out / "filings.json").read_text())
    assert f["meetings"]["rows"][0][:2] == ["2099-12-30", "ACME"]
    assert f["announcements"]["rows"][0][0] == "ACME"


def test_the_screener_and_search_index_are_written(wh):
    out = wh / "site"
    X.export(out)
    sc = json.loads((out / "screener.json").read_text())
    row = dict(zip(sc["cols"], sc["rows"][0], strict=True))
    assert row["sym"] == "ACME" and row["deals_12m"] == 1      # the mutual fund buy; round trips are not activity
    search = json.loads((out / "search.json").read_text())
    assert ["ACME", "s", "ACME", "Acme Ltd"] in search and any(r[1] == "p" and r[0] == "SBI MUTUAL FUND" for r in search)


LOG = """--- 2026-10-25 18:39:59 IST pid=1
deals=1
  stage alert: desktop=True; email=email sent to someone@example.com via 587/starttls; telegram=telegram FAILED after 0/1 part(s): URLError
❌ FAILED — 3 stage(s)   34 stages in 205m 09s
--- 2026-10-26 18:37:54 IST pid=2
  email sent to someone@example.com via 587/starttls
  telegram sent to 12345 (1 message(s))
✅ ALL CLEAN   33 stages in 37m 22s
--- 2026-10-26 21:00:01 IST pid=3
deals=0
"""


@pytest.mark.unit
def test_recent_runs_are_read_from_the_log_newest_first_and_an_unfinished_run_is_left_out():
    runs = X._runs_from_log(LOG)
    assert [r["started"] for r in runs] == ["2026-10-26 18:37:54 IST", "2026-10-25 18:39:59 IST"]
    assert runs[0] | {} == {"started": "2026-10-26 18:37:54 IST", "ok": True, "failed": 0, "stages": 33,
                            "minutes": 37, "email": "sent", "telegram": "sent"}
    assert (runs[1]["ok"], runs[1]["failed"], runs[1]["minutes"], runs[1]["telegram"]) == (False, 3, 205, "failed")


@pytest.mark.unit
def test_the_system_page_never_carries_an_address_or_a_chat_id(tmp_path, monkeypatch):
    # Real data stays out of a unit test: the archive walk, the coverage scan and health.
    monkeypatch.setattr(X, "_archive_inventory", lambda: [{"source": "BULK", "files": 3, "mb": 1}])
    monkeypatch.setattr(X, "_coverage", lambda: [])
    monkeypatch.setattr(X, "_health", lambda: [])
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "collect_2026-10.log").write_text(LOG)
    (logs / "last_run.tsv").write_text("# started 2026-10-26T13:07:54+00:00\ndeals\t0\t1593\nhealth\t0\t1\n")
    doc = X.export_system(tmp_path, logs)
    text = (tmp_path / "system.json").read_text()
    assert "@" not in text and "12345" not in text
    assert doc["last_run"]["stages"] == [{"stage": "deals", "exit": 0, "seconds": 1593},
                                         {"stage": "health", "exit": 0, "seconds": 1}]


@pytest.mark.unit
def test_export_stocks_never_rebinds_its_deal_list():
    """A loop `for sym, rows in history.items()` shadowed the deals and crashed
    every site export on 2026-10-27/28 (the latest 'session' read as 'ZYLO')."""
    import ast
    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(X))) if isinstance(n, ast.FunctionDef) and n.name == "export_stocks")
    targets = [t for n in ast.walk(fn) if isinstance(n, (ast.For, ast.comprehension, ast.Assign))
               for t in ast.walk(n.target if hasattr(n, "target") else n.targets[0]) if isinstance(t, ast.Name)]
    assert "rows" not in {t.id for t in targets}


def test_share_counts_divide_out_a_paid_up_capital_filed_in_lakh_or_rupees():
    # FIVESTAR 2026-06-30: paid-up 29,51,797.88 (lakh), face 1, profit 271.41 cr, EPS 9.19.
    lakh = X.share_counts([(2951797.88, 271.41, 9.19), (29.4469, 286.14, 9.72)])
    assert lakh[0] == pytest.approx(29.518, rel=1e-3) and lakh[1] == pytest.approx(29.4469)
    rupees = X.share_counts([(1.012e8, 50.0, 4.94)])
    assert rupees[0] == pytest.approx(10.12)


def test_share_counts_leave_a_real_split_alone():
    # A 10-for-1 split: every quarter after it is ten times the ones before.
    rows = [(100.0, 50.0, 0.5), (100.0, 48.0, 0.48), (10.0, 45.0, 4.5), (10.0, 40.0, 4.0)]
    assert X.share_counts(rows) == [100.0, 100.0, 10.0, 10.0]


def test_share_counts_fix_one_quarter_ten_times_off_its_neighbours():
    rows = [(60.78, None, None), (6.078, None, None), (60.78, None, None)]
    assert X.share_counts(rows)[1] == pytest.approx(60.78)


def test_a_newest_quarter_far_off_the_two_before_takes_their_count():
    rows = [(0.002, None, None), (609.36, None, None), (609.36, None, None)]
    assert X.share_counts(rows)[0] == 609.36


def test_no_market_cap_when_shares_still_disagree_with_profit_over_eps():
    def q(qe, shares, pat, eps):
        return [qe, True, 100.0, 0.0, 0.0, pat, pat, eps, 0.0, 0.0, shares, False, qe]
    bad = [q("2026-06-30", 0.01, 26.4, 1.0)]
    assert X.valuation(bad, 500.0)["mcap_cr"] is None
    ok = [q("2026-06-30", 26.4, 26.4, 1.0)]
    assert X.valuation(ok, 500.0)["mcap_cr"] == 13200


# --- insider history and delivery (2026-11-05) ----------------------------------


def _insider_files(tmp_path, seed_rows, collected_rows):
    con = duckdb.connect()
    con.execute("""CREATE TABLE s (symbol VARCHAR, filing_date VARCHAR, name VARCHAR, category VARCHAR,
                   transaction_type VARCHAR, quantity BIGINT, value DOUBLE, mode VARCHAR)""")
    con.execute("""CREATE TABLE k (symbol VARCHAR, filing_date VARCHAR, person VARCHAR, category VARCHAR,
                   transaction_type VARCHAR, quantity DOUBLE, value DOUBLE, mode VARCHAR)""")
    for name, rows in (("s", seed_rows), ("k", collected_rows)):
        if rows:
            con.executemany(f"INSERT INTO {name} VALUES (?,?,?,?,?,?,?,?)", rows)
    seed, coll = tmp_path / "seed.parquet", tmp_path / "coll.parquet"
    con.execute(f"COPY s TO '{seed}' (FORMAT PARQUET)")
    con.execute(f"COPY k TO '{coll}' (FORMAT PARQUET)")
    return con, seed, coll


def test_insider_history_comes_from_the_seed_too(tmp_path):
    """Until 2026-11-05 only the collector's file was read: TCS, with 131 seed
    filings, showed none."""
    con, seed, coll = _insider_files(
        tmp_path, [("TCS", "2022-03-30", "Tata Sons", "Promoters", "Sell", 0, 1e9, None)], [])
    got = X.insider_rows(con, seed, coll)
    assert got["TCS"] == [["2022-03-30", "Tata Sons", "Promoters", "Sell", None, 100.0, None]], (
        "a quantity of 0 in the seed means not stated, never zero shares")


def test_one_trade_in_both_files_counts_once_though_their_dates_differ(tmp_path):
    """The seed dated these 2 to 4 days away from the collected XBRL."""
    con, seed, coll = _insider_files(
        tmp_path,
        [("X", "2026-05-23", "A Person ", "Promoters", "Buy", 10, 1e7, None),
         ("X", "2026-01-02", "A Person", "Promoters", "Buy", 10, 1e7, None)],
        [("X", "2026-05-26", "a person", "Promoters", "Buy", 10.0, 1e7, "Market")])
    rows = X.insider_rows(con, seed, coll)["X"]
    assert [r[0] for r in rows] == ["2026-01-02", "2026-05-26"], "the same value months apart is another trade"


def test_a_filing_larger_than_the_company_is_blanked_and_counted():
    """The seed's Rs 54.98 lakh crore sale of SJS. 10 crore shares at Rs 100 is
    Rs 1,000 crore of company."""
    rows = [["2023-08-23", "Big", "Promoters", "Sell", None, 5e6, None],
            ["2023-08-23", "Real", "Promoters", "Sell", None, 500.0, None]]
    doc = X.insider_doc(rows, [["2023-08-25", 100.0]], 10.0)
    assert doc["insider_doubt"] == 1
    assert [r[5] for r in doc["insider"]["rows"]] == [None, 500.0]
    assert doc["insider_sum"]["rows"] == [["2023", "Promoter", 2, 0.0, 500.0, 0.0, 0.0, 0.0]], (
        "an impossible value must not reach a total either")


def test_a_value_stands_when_the_check_has_nothing_to_check_against():
    doc = X.insider_doc([["2023-08-23", "P", "Other", "Buy", None, 5e6, None]], [], None)
    assert doc["insider_doubt"] == 0 and doc["insider"]["rows"][0][5] == 5e6


def test_the_page_carries_the_newest_filings_and_the_summary_all_of_them():
    rows = [[f"20{10 + i % 10}-01-01", "P", "Employee", "Sell", None, 1.0, None] for i in range(X.INSIDER_KEEP + 50)]
    rows.sort(key=lambda r: r[0])
    doc = X.insider_doc(rows, [], None)
    assert len(doc["insider"]["rows"]) == X.INSIDER_KEEP
    assert doc["insider"]["rows"][-1][0] == rows[-1][0]
    assert doc["insider_n"] == X.INSIDER_KEEP + 50
    assert sum(r[2] for r in doc["insider_sum"]["rows"]) == X.INSIDER_KEEP + 50


def test_delivery_is_weighted_by_quantity_and_leaves_debt_series_out(tmp_path):
    con = duckdb.connect()
    con.execute("""CREATE TABLE d AS SELECT * FROM (VALUES
        ('2026-01-05', 'X', 'EQ', 100.0, 90.0),
        ('2026-01-06', 'X', 'EQ', 900.0, 90.0),
        ('2026-01-06', 'X', 'GB', 500.0, 500.0)) t(date, symbol, series, traded_qty, deliverable_qty)""")
    path = tmp_path / "d.parquet"
    con.execute(f"COPY d TO '{path}' (FORMAT PARQUET)")
    got = X.delivery_series(con, path)["X"]
    assert got["dlv"]["rows"] == [["2026-01", 18.0]], "a plain mean of 90% and 10% would say 50%"
    assert got["dlv_s"]["s20"] == 18.0 and got["dlv_s"]["as_of"] == "2026-01-06"
    assert got["dlv_d"]["rows"][-1] == ["2026-01-06", 10.0, 900.0]


def test_one_early_scheme_does_not_make_a_new_month_latest():
    """5 rows dated 31 October blanked the fund holdings on every stock page."""
    assert X.latest_full_month(["2026-09-30"] * 1300 + ["2026-10-31"]) == "2026-09-30"
    assert X.latest_full_month(["2026-09-30"] * 500 + ["2026-10-31"] * 800) == "2026-10-31"


def test_a_share_split_s_new_isin_keeps_the_shareholding_filed_before_it():
    """IEX: INE022Q01012 until the split, INE022Q01020 after."""
    own = {"INE022Q01012": [["2018-03-31", 1.0], ["2021-06-30", 2.0]],
           "INE022Q01020": [["2021-09-30", 3.0], ["2026-06-30", 4.0]]}
    got = X.chain_isins(own, {"INE022Q01020"})
    assert [r[0] for r in got["INE022Q01020"]] == ["2018-03-31", "2021-06-30", "2021-09-30", "2026-06-30"]


def test_quarters_filed_under_an_old_isin_fill_in_though_they_interleave():
    """Most companies look like this: 2016-17 under today's ISIN, 2018-21 under
    the old one, then today's again. CLEDUCATE, 12 quarters."""
    own = {"INE201M01029": [["2017-03-31", 1.0], ["2021-09-30", 3.0]],
           "INE201M01011": [["2018-06-30", 2.0], ["2021-06-30", 2.5]]}
    got = X.chain_isins(own, {"INE201M01029"})["INE201M01029"]
    assert [r[0] for r in got] == ["2017-03-31", "2018-06-30", "2021-06-30", "2021-09-30"]


def test_on_a_quarter_both_report_the_current_isin_wins():
    own = {"INE389K01028": [["2021-03-31", 9.0], ["2021-06-30", 9.5]], "INE389K01010": [["2021-03-31", 1.0], ["2019-09-30", 2.0]]}
    got = X.chain_isins({k: sorted(v) for k, v in own.items()}, {"INE389K01028"})["INE389K01028"]
    assert got == [["2019-09-30", 2.0], ["2021-03-31", 9.0], ["2021-06-30", 9.5]]


def test_an_isin_with_its_own_page_is_never_absorbed():
    both = {"INE001A01011": [["2019-12-31", 1.0]], "INE001A01029": [["2020-03-31", 2.0]]}
    assert X.chain_isins(both, set(both)) == both
    assert [r[0] for r in X.chain_isins(both, {"INE001A01029"})["INE001A01029"]] == ["2019-12-31", "2020-03-31"]


def test_a_fund_industry_is_the_majority_label_for_an_equity_isin_only(tmp_path):
    con = duckdb.connect()
    con.execute("""CREATE TABLE m AS SELECT * FROM (VALUES
        ('a', 'INE429E01023', 'Consumer Durables'), ('b', 'INE429E01023', 'CONSUMER DURABLES'),
        ('c', 'INE429E01023', 'N.A.'), ('d', 'INE429E01023', '69.8'),
        ('a', 'INE134E08NP7', 'CRISIL AAA'),
        ('a', 'INE111A01011', 'Banks'), ('b', 'INE111A01011', 'Finance')) t(amc, isin, industry)""")
    path = tmp_path / "m.parquet"
    con.execute(f"COPY m TO '{path}' (FORMAT PARQUET)")
    got = X.fund_industries(path)
    assert got["INE429E01023"].lower() == "consumer durables"
    assert "INE134E08NP7" not in got, "a bond's rating is not an industry"
    assert "INE111A01011" not in got, "a tie names nothing"


def test_nifty_valuation_runs_the_seed_back_from_where_the_collected_series_starts(tmp_path):
    con = duckdb.connect()
    con.execute("""CREATE TABLE i AS SELECT DATE '2021-10-18' AS date, 'NIFTY50' AS index_key, 18000.0::DOUBLE AS close, 27.0::DOUBLE AS pe, 4.5::DOUBLE AS pb, 1.1::DOUBLE AS div_yield""")
    con.execute("""CREATE TABLE v AS SELECT * FROM (VALUES
        ('NIFTY 50', '2005-01-03', 15.0, 3.0, 1.5), ('NIFTY 50', '2021-10-18', 99.0, 9.0, 9.0),
        ('NIFTY IT', '2005-01-03', 50.0, 5.0, 0.5)) t(index_name, date, pe, pb, div_yield)""")
    con.execute("""CREATE TABLE c AS SELECT 'NIFTY 50' AS name, '2005-01-03' AS date, 2000.0 AS close""")
    con.execute(f"COPY i TO '{tmp_path}/i.parquet' (FORMAT PARQUET)")
    con.execute(f"COPY v TO '{tmp_path}/index_valuation.parquet' (FORMAT PARQUET)")
    con.execute(f"COPY c TO '{tmp_path}/indices_data.parquet' (FORMAT PARQUET)")
    got = X.nifty_valuation(con, tmp_path / "i.parquet", tmp_path)
    assert got == [["2005-01-03", 2000.0, 15.0, 3.0, 1.5], ["2021-10-18", 18000.0, 27.0, 4.5, 1.1]], (
        "the collected series wins on its own dates; another index stays out")


def test_a_share_split_on_a_stock_still_trading_is_not_a_delisting():
    """HAVELLS read "delisted 2014-08-06 (ISIN_CHANGE)" with a price from this week."""
    split = {"delisted": "2014-08-06", "reason": "ISIN_CHANGE", "status": "MERGED"}
    assert X.listing_state(split, [["2026-11-06", 1500.0]], "2026-11-06") == {
        "delisted": None, "reason": None, "status": "ACTIVE"}
    assert X.listing_state(split, [["2014-08-01", 100.0]], "2026-11-06")["delisted"] == "2014-08-06", "no current price: it stands"
    left = {"delisted": "2026-10-20", "reason": "LEFT_UNIVERSE", "status": "DELISTED"}
    assert X.listing_state(left, [["2026-10-16", 50.0]], "2026-11-06")["delisted"] == "2026-10-20", "only this reason is overruled"


def test_overlapping_quarters_do_not_stop_an_old_isin_filling_the_rest():
    """PCBL and DOLPHIN: most of the old ISIN's quarters are the current one's too."""
    own = {"INE602A01023": [[f"20{y}-03-31", 1.0] for y in (18, 19, 20, 21, 22)],
           "INE602A01031": [[f"20{y}-03-31", 2.0] for y in (19, 20, 21, 22)]}
    got = X.chain_isins(own, {"INE602A01031"})["INE602A01031"]
    assert [(r[0][:4], r[1]) for r in got] == [("2018", 1.0), ("2019", 2.0), ("2020", 2.0), ("2021", 2.0), ("2022", 2.0)]


def test_a_mistyped_isin_joins_only_on_the_filing_s_own_symbol():
    own = {"INE0LEZ01016": [["2026-06-30", 1.0]], "INE0LEZO1016": [["2026-03-31", 2.0]]}
    page = {"ATHERENERG": "INE0LEZ01016"}
    got = X.chain_isins(own, {"INE0LEZ01016"}, {"INE0LEZO1016": "ATHERENERG"}, page)
    assert [r[0] for r in got["INE0LEZ01016"]] == ["2026-03-31", "2026-06-30"]
    other = X.chain_isins(own, {"INE0LEZ01016"}, {"INE0LEZO1016": "SOMEONE"}, page)
    assert len(other["INE0LEZ01016"]) == 1, "near characters alone could be another issuer"


def _quarter(qe, rev):
    return [qe, True, rev, 1.0, 2.0, 3.0, 3.0, 4.75, 5.0, 6.0, None, False, "x"]


def test_a_quarter_an_exact_power_of_ten_off_its_neighbours_is_withheld():
    """COROMANDEL 2026-03-31 filed Rs 60 crore against about Rs 6,000 either side."""
    res = [_quarter("2026-06-30", 8165.0), _quarter("2026-03-31", 60.0), _quarter("2025-12-31", 8779.0)]
    assert X.withhold_mis_scaled(res) == ["2026-03-31"], "140 times off, COROMANDEL's real figures"
    assert res[1][2] is None and res[1][5] is None, "blanked, not rescaled"
    assert res[1][7] == 4.75 and res[0][2] == 8165.0


def test_a_real_jump_is_not_withheld():
    jump = [_quarter("2026-06-30", 6000.0), _quarter("2026-03-31", 3000.0), _quarter("2025-12-31", 100.0)]
    assert X.withhold_mis_scaled(jump) == [], "neighbours that disagree prove nothing"
    near = [_quarter("2026-06-30", 100.0), _quarter("2026-03-31", 300.0), _quarter("2025-12-31", 100.0)]
    assert X.withhold_mis_scaled(near) == [], "three times is not a slip of a power of ten"


def test_an_unknown_delisting_gives_way_to_a_current_price():
    nestle = {"delisted": "2019-12-06", "reason": "UNKNOWN", "status": "DELISTED"}
    assert X.listing_state(nestle, [["2026-11-06", 1200.0]], "2026-11-06")["status"] == "ACTIVE"


def test_half_year_results_keep_consolidated_and_are_kept_from_the_quarters(tmp_path):
    con = duckdb.connect()
    con.execute("""CREATE TABLE h AS SELECT * FROM (VALUES
        ('X', '2025-09-30', false, '2025-11-01', 10.0::DOUBLE, 2.0::DOUBLE, 1.0::DOUBLE, 0.5::DOUBLE),
        ('X', '2025-09-30', true, '2025-11-02', 12.0::DOUBLE, 3.0::DOUBLE, 2.0::DOUBLE, 0.6::DOUBLE),
        ('X', '2025-03-31', false, '2025-05-01', 9.0::DOUBLE, 1.0::DOUBLE, 1.0::DOUBLE, 0.4::DOUBLE))
        v(symbol, period_end, consolidated, filed, revenue, pbt, pat, eps)""")
    p = tmp_path / "h.parquet"
    con.execute(f"COPY h TO '{p}' (FORMAT PARQUET)")
    got = X.half_results(p)["X"]
    assert [r[0] for r in got] == ["2025-09-30", "2025-03-31"]
    assert got[0][:3] == ["2025-09-30", True, 12.0]


def test_a_mis_scaled_half_year_is_blanked_like_a_quarter():
    res = [["c", False, 100.0, 5.0, 4.0, 1.0, "x"], ["b", False, 1.0, 5.0, 4.0, 1.0, "x"], ["a", False, 90.0, 5.0, 4.0, 1.0, "x"]]
    assert X.withhold_mis_scaled(res, (2, 3, 4)) == ["b"]
    assert res[1][2:5] == [None, None, None] and res[1][5] == 1.0
