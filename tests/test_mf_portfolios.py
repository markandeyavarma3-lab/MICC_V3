"""Monthly mutual-fund portfolios: the parser every fund house shares, the
month a file URL names, which files are fetched, and the site's shape."""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from src.archive import mf_portfolios as A
from src.ingest import mf_portfolios as P
from src.site import export as E


@pytest.mark.unit
@pytest.mark.parametrize("text, want", [
    ("Portfolio as on 30-09-26", date(2026, 9, 30)),                       # Tata
    ("Monthly Portfolio Statement as on September 30, 2026", date(2026, 9, 30)),
    ("Portfolio as on Sep 30,2026", date(2026, 9, 30)),                    # ICICI
    ("Monthly  Portfolio Statement for the period ended 30.09.2026", date(2026, 9, 30)),   # JM
    ("as on 30th September 2026", date(2026, 9, 30)),
    ("2026-09-30", date(2026, 9, 30)),                                     # an ISO cell must not read as 26-09-30
    ("monthend-portfolio-february-28-2026", date(2026, 2, 28)),
    ("BOBBNPMF_Monthly_Portfolio_30-09-2026_20376", date(2026, 9, 30)),    # digits run on after the year
    ("no date here", None),
])
def test_every_title_date_form_the_fund_houses_use_is_read(text, want):
    assert P.parse_date(text) == want


@pytest.mark.unit
@pytest.mark.parametrize("url, want", [
    ("all-schemes-monthly-portfolio---as-on-30th-september-2026.xlsx", "2026-09"),
    ("monthend-portfolio-31march2026.zip", "2026-03"),
    ("monthend-portfolio-november-2025.zip", "2025-11"),
    ("30092026_abslmf_monthlydisclosure.zip", "2026-09"),
    ("sensex_sept2026.xlsx", "2026-09"),
    ("NIMF-MONTHLY-PORTFOLIO-30-Sep-26.xls", "2026-09"),
    ("/2012/dec/7a181-989112922monthly_portfolio_disclosure_-_dec12.xls", "2012-12"),
    ("IN_MF_MONTHLY_PORTFOLIO_Apirl_2026_SamcoFund.xlsx", "2026-04"),      # the site's own spelling
    ("business-cycle-fund0dabfc07eee8616aaa28ff00007d74af.xlsx", None),
])
def test_the_month_is_read_from_the_file_name(url, want):
    assert A.month_of(url) == want


def _sheet(pct_scale: float = 1.0, unit: str = "Market/Fair Value (Rs. in Lacs)"):
    return [
        ["RLMF001", "Nippon India Growth Mid Cap Fund (An open-ended equity scheme)", "Index"],
        ["Monthly Portfolio Statement as on September 30,2026"],
        [],
        ["", "ISIN", "Name of the Instrument", "Industry / Rating", "Quantity", unit, "% to NAV", "YIELD"],
        ["Equity & Equity related"],
        ["MCEX02", "INE745G01043", "Multi Commodity Exchange of India Limited", "Capital Markets", 4901000.0,
         161752.6, 3.22 * pct_scale],
        ["AFPL02", "INE949L01017", "AU Small Finance Bank Limited", "Banks", 14100000.0, 142452.3, 2.84 * pct_scale],
        ["", "", "Sub Total", "", "", 304204.9, 6.06 * pct_scale],
        ["", "TREPS", "Clearing Corporation", "", "", 1000.0, 0.5 * pct_scale],
    ]


@pytest.mark.unit
def test_a_sheet_is_read_by_its_isin_header_and_totals_fall_away():
    rows = P.parse_sheet(_sheet(), "GF", {})
    assert [r["isin"] for r in rows] == ["INE745G01043", "INE949L01017"]
    r = rows[0]
    assert r["scheme"] == "Nippon India Growth Mid Cap Fund"            # description stripped
    assert r["as_of"] == date(2026, 9, 30)
    assert r["value_cr"] == pytest.approx(1617.526)                     # lakh -> crore
    assert r["pct"] == pytest.approx(3.22) and r["qty"] == 4901000.0
    assert r["industry"] == "Capital Markets"


@pytest.mark.unit
def test_a_fraction_percentage_is_put_on_the_percent_scale():
    rows = P.parse_sheet(_sheet(pct_scale=0.01), "GF", {})
    assert rows[0]["pct"] == pytest.approx(3.22)


@pytest.mark.unit
def test_the_index_sheet_names_the_scheme_and_the_value_unit_is_read():
    rows = P.parse_sheet(_sheet(unit="Market Value (Rs. in Crore)"), "GF", {"GF": "Index Name Fund"})
    assert rows[0]["scheme"] == "Index Name Fund"
    assert rows[0]["value_cr"] == pytest.approx(161752.6)


SRC = {"amc": "X", "page": "https://x.example/p/", "match": "monthly", "base": "https://x.example/blob"}


@pytest.mark.unit
def test_candidates_keep_monthly_files_in_the_window_and_drop_the_rest():
    links = [("https://x.example/f/monthly-portfolio-september-2026.xlsx", ""),
             ("https://x.example/f/monthly-portfolio-january-2025.xlsx", ""),        # outside the window
             ("https://x.example/f/fortnightly-monthly-debt-30-sep-2026.xlsx", ""),  # excluded by default
             ("https://x.example/f/annual-report-2026.pdf", "")]
    got = A.candidates(SRC, links, [], months=3, today=date(2026, 10, 10))
    assert [c["url"] for c in got] == ["https://x.example/f/monthly-portfolio-september-2026.xlsx"]
    assert got[0]["month"] == "2026-09"


@pytest.mark.unit
def test_api_paths_with_spaces_join_the_source_base():
    body = '{"files":[{"url":"/downloads/Files/Monthly Portfolio Disclosures/2026/Sep/Monthly-Portfolio-Disclosure-September-2026.zip"}]}'
    got = A.candidates({**SRC, "mode": "api"}, [], [body], months=3, today=date(2026, 10, 10))
    assert got[0]["url"] == ("https://x.example/blob/downloads/Files/Monthly%20Portfolio%20Disclosures/2026/Sep/"
                             "Monthly-Portfolio-Disclosure-September-2026.zip")


@pytest.mark.unit
def test_an_undated_source_is_fetched_and_left_to_its_title():
    links = [("https://x.example/f/monthly-holding-business-cycle-fund0dabfc07.xlsx", "")]
    assert A.candidates(SRC, links, [], 3, date(2026, 10, 10)) == []
    got = A.candidates({**SRC, "undated": True}, links, [], 3, date(2026, 10, 10))
    assert got[0]["month"] == "undated"


@pytest.mark.unit
def test_only_company_equity_isins_count_as_equity():
    assert E.is_equity_isin("INE745G01043")
    assert not E.is_equity_isin("INE020B08DH1")       # a debenture
    assert not E.is_equity_isin("INF204KB14I2")       # fund units
    assert not E.is_equity_isin("IN0020230085")       # government paper


@pytest.fixture
def mf_parquet(tmp_path, monkeypatch):
    out = tmp_path / "mf.parquet"
    rows = [  # (amc, scheme, as_of, isin, name, industry, qty, value_cr, pct, source_file)
        ("SBI", "SBI Alpha Fund", "2026-08-31", "INE745G01043", "MCX", "Capital Markets", 100.0, 10.0, 5.0, "a"),
        ("SBI", "SBI Alpha Fund", "2026-08-31", "INE949L01017", "AU Bank", "Banks", 50.0, 5.0, 2.5, "a"),
        ("SBI", "SBI Alpha Fund", "2026-09-30", "INE745G01043", "MCX", "Capital Markets", 160.0, 16.0, 8.0, "b"),
        ("SBI", "SBI Alpha Fund", "2026-09-30", "INE171A01029", "Federal Bank", "Banks", 70.0, 7.0, 3.5, "b"),
        ("SBI", "SBI Alpha Fund", "2026-09-30", "INE020B08DH1", "REC 7.5% NCD", "CRISIL AAA", 1.0, 3.0, 1.5, "b"),
        ("HDFC", "HDFC Beta Fund", "2026-09-30", "INE745G01043", "MCX", "Capital Markets", 40.0, 4.0, 2.0, "c"),
    ]
    con = duckdb.connect()
    con.execute("CREATE TABLE t (amc VARCHAR, scheme VARCHAR, as_of VARCHAR, isin VARCHAR, name VARCHAR,"
                " industry VARCHAR, qty DOUBLE, value_cr DOUBLE, pct DOUBLE, source_file VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.execute(f"COPY t TO '{out}' (FORMAT PARQUET)")
    con.close()
    monkeypatch.setattr(P, "OUT", out)
    return out


@pytest.mark.unit
def test_a_stock_shows_every_scheme_holding_it_with_the_monthly_change(mf_parquet):
    mf = E.mf_holdings()
    assert mf["latest"] == "2026-09-30"
    doc = E.mf_stock_doc(mf, "INE745G01043", shares_cr=0.1)          # 0.1 crore = 1,000,000 shares
    assert doc["schemes"] == 2 and doc["houses"] == 2 and doc["qty"] == 200.0
    held = {r[1]: r for r in doc["held"]["rows"]}
    assert held["SBI Alpha Fund"][6] == 60.0                        # 160 now vs 100 last month
    assert held["HDFC Beta Fund"][6] is None                        # no prior month held for that scheme
    assert doc["pct_of_company"] == pytest.approx(0.02)
    # AU Bank was held in August and not in September: a full sale by that scheme.
    assert E.mf_holdings()["by_isin"]["INE949L01017"]["exits"][0][1] == "SBI Alpha Fund"
    fed = E.mf_stock_doc(mf, "INE171A01029", None)
    assert fed["new"] == 1 and fed["held"]["rows"][0][7] == "NEW"


@pytest.mark.unit
def test_scheme_pages_split_equity_from_bonds_and_list_the_sales(mf_parquet, tmp_path):
    import json
    mf = E.mf_holdings()
    n = E.export_funds(tmp_path / "site", mf, {"INE745G01043": ("MCX", "MCX", "Multi Commodity Exchange")})
    assert n == 2
    idx = json.loads((tmp_path / "site" / "funds.json").read_text())
    alpha = next(r for r in idx["rows"] if r[3] == "SBI Alpha Fund")
    doc = json.loads((tmp_path / "site" / "funds" / f"{alpha[0]}.json").read_text())
    assert [r[0] for r in doc["equity"]["rows"]] == ["INE745G01043", "INE171A01029"]
    assert doc["equity"]["rows"][0][1] == "MCX"                      # linked to the stock page
    assert [r[0] for r in doc["other"]["rows"]] == ["INE020B08DH1"]
    assert [r[0] for r in doc["exited"]["rows"]] == ["INE949L01017"]
    assert doc["total_cr"] == 26.0 and doc["equity_pct"] == 11.5


@pytest.mark.unit
def test_a_day_after_the_month_is_not_read_as_a_two_digit_year():
    # Measured 2026-10-10: PPFAS's '..._December_31_2025.xls' was first read as December 2031.
    assert A.month_of("PPFAS_Monthly_Portfolio_Report_December_31_2025.xls") == "2025-12"
    links = [("https://x.example/f/monthly-portfolio-dec-2031.xlsx", "")]
    assert A.candidates(SRC, links, [], 3, date(2026, 10, 10)) == []     # a future month is never a file


@pytest.mark.unit
def test_a_separated_two_digit_year_is_read_when_no_full_year_follows():
    assert A.month_of("Old_Bridge_Focused_Fund_Monthly_Portfolio_Feb_26_4211b7c07a.xlsx") == "2026-02"


@pytest.mark.unit
def test_a_labelled_scheme_name_and_company_boilerplate_are_handled():
    head = [["SCHEME NAME", "Helios Flexi Cap Fund"], ["Portfolio as on 30-Sep-2026"],
            ["ISIN", "Name of Instrument", "Quantity", "Market Value (Rs. in Lakhs)", "% to NAV"],
            ["INE040A01034", "HDFC Bank", 10.0, 1.0, 5.0]]
    assert P.parse_sheet(head, "HFCF", {})[0]["scheme"] == "Helios Flexi Cap Fund"
    mo = [["Motilal Oswal Asset Management Company Limited"], ["(Investment Manager for Motilal Oswal Mutual Fund)"],
          ["MONTHLY PORTFOLIO STATEMENT AS ON SEPTEMBER 30, 2026"], ["Motilal Oswal Nifty 50 ETF"],
          ["Sr. No.", "Name of the Instrument", "ISIN", "Industry*", "Quantity", "Market/Fair Value (Rs. in Lakhs)", "% to Net Assets"],
          ["1", "HDFC Bank", "INE040A01034", "Banks", 10.0, 1.0, 5.0]]
    assert P.parse_sheet(mo, "YO01", {})[0]["scheme"] == "Motilal Oswal Nifty 50 ETF"


@pytest.mark.unit
def test_each_section_of_a_sheet_is_read_under_its_own_header():
    rows = [["DSP Aggressive Hybrid Fund"], ["Portfolio as on September 30, 2026"],
            ["Name of Instrument", "ISIN", "Rating/Industry", "Quantity", "Market value (Rs. In lakhs)", "% to Net Assets"],
            ["HDFC Bank Limited", "INE040A01034", "Banks", 100.0, 900.0, 0.09],
            ["Name of Instrument", "ISIN", "Coupon", "Rating", "Quantity", "Market value (Rs. In lakhs)", "% to Net Assets"],
            ["7.5% REC NCD", "INE020B08DH1", 7.5, "CRISIL AAA", 10.0, 100.0, 0.01]]
    got = P.parse_sheet(rows, "DSPAH", {})
    assert [r["pct"] for r in got] == pytest.approx([9.0, 1.0])     # fractions, scaled, from the right column each time
    assert got[1]["industry"] == "CRISIL AAA" and got[1]["value_cr"] == pytest.approx(1.0)


@pytest.mark.unit
def test_a_template_source_asks_for_each_month_in_the_window():
    src = {"template": "https://x.example/api?year={year}&month={month}&mm={mm}"}
    got = A.template_urls(src, 3, today=date(2026, 1, 15))
    assert [u for u, _ in got] == ["https://x.example/api?year=2025&month=December&mm=12",
                                   "https://x.example/api?year=2025&month=November&mm=11",
                                   "https://x.example/api?year=2025&month=October&mm=10"]


@pytest.mark.unit
def test_a_paginated_list_is_walked_page_by_page_once():
    src = {"template": "https://cms.example/api/p?page={page}&size=100", "pages": 3}
    got = A.template_urls(src, 24, today=date(2026, 10, 20))
    assert [u for u, _ in got] == [f"https://cms.example/api/p?page={p}&size=100" for p in (1, 2, 3)]
    blob = '{"data":[{"doc_file":{"url":"https://content.example/Mid_Cap_Fund_ed80fd3766.xls"}}]}'
    c = A.candidates({"page": "https://x.example/p", "mode": "template", "undated": True,
                      "match": "content\\.example/"}, [], [blob], 24, date(2026, 10, 20))
    assert [(x["url"], x["month"]) for x in c] == [("https://content.example/Mid_Cap_Fund_ed80fd3766.xls", "undated")]


@pytest.mark.unit
def test_a_per_year_post_is_asked_for_once_a_year_and_its_links_are_read():
    src = {"template": "https://x.example/m.aspx/list", "post": "{{id:'{year}',cat:'Monthly Portfolio'}}"}
    got = A.template_urls(src, 15, today=date(2026, 3, 15))      # Feb 2026 back to Dec 2024
    assert [b for _, b in got] == ["{id:'2026',cat:'Monthly Portfolio'}", "{id:'2025',cat:'Monthly Portfolio'}",
                                   "{id:'2024',cat:'Monthly Portfolio'}"]
    html = "<ul><li><a href='/Admin/disclouser/Monthly_portfolio_sept_30092025.xlsx'>x</a></li></ul>"
    c = A.candidates({"page": "https://x.example/p", "base": "https://x.example", "mode": "template",
                      "match": "portfolio"}, [], [html], 3, date(2025, 10, 20))
    assert [x["url"] for x in c] == ["https://x.example/Admin/disclouser/Monthly_portfolio_sept_30092025.xlsx"]


@pytest.mark.unit
def test_a_regulatory_notice_above_the_table_is_not_the_scheme_name():
    hdr = ["ISIN", "Name of Instrument", "Rating", "Quantity", "Market Value (In Rs. lakh)", "% To Net Assets"]
    rows = [["[Pursuant to Regulation 59 A of Securities and Exchange Board of India (Mutual Funds)"],
            ["", "Portfolio as on 30-Jun-2023"], hdr,
            ["INE040A01034", "HDFC Bank Ltd", "Banks", 10, 100, 0.05]]
    got = {r["scheme"] for r in P.parse_sheet(rows, "TRUSTMF Liquid Fund", {})}
    assert got == {"TRUSTMF Liquid Fund"}


@pytest.mark.unit
def test_stacked_schemes_and_dated_titles_are_named_right():
    assert P._clean_scheme("SCHEME: UTI - Large Cap Fund") == "UTI - Large Cap Fund"
    assert P._clean_scheme("IB01-Groww Large Cap Fund") == "Groww Large Cap Fund"
    assert P._clean_scheme("Franklin India Prima Fund As of Date - 30Aug2019") == "Franklin India Prima Fund"
    assert P._clean_scheme("Franklin India Flexi Cap Fund ( Formerly known as X) ^") == "Franklin India Flexi Cap Fund"
    hdr = ["NAME OF THE INSTRUMENT", "RATING/INDUSTRY", "QUANTITY", "MARKET-VALUE", "% TO NAV", "ISIN"]
    rows = [["SCHEME CODE002STARTS"], ["SCHEME: UTI - Unit Linked Insurance Plan"], ["AS ON 30/09/2026"], hdr,
            ["EQ - ETERNAL", "Retailing", 10, 100, 2.9, "INE758T01015"],
            ["SCHEME CODE017STARTS"], ["SCHEME: UTI - Large Cap Fund"], hdr,
            ["EQ - HDFC", "Banks", 5, 50, 3.1, "INE040A01034"]]
    got = [(r["scheme"], r["isin"]) for r in P.parse_sheet(rows, "EXPOSURE", {})]
    assert got == [("UTI - Unit Linked Insurance Plan", "INE758T01015"), ("UTI - Large Cap Fund", "INE040A01034")]


@pytest.mark.unit
def test_an_undated_template_source_reads_links_out_of_a_js_string():
    body = "<div><a href='/uploaddir/MonthlyPortfolio/monthlyportfolio_091026155031.xlsx'>x</a></div>"
    src = {"page": "https://x.example/p", "base": "https://x.example", "mode": "template",
           "match": "monthlyportfolio", "undated": True}
    got = A.candidates(src, [], [body], 3, date(2026, 10, 16))
    assert [(c["url"], c["month"]) for c in got] == [
        ("https://x.example/uploaddir/MonthlyPortfolio/monthlyportfolio_091026155031.xlsx", "undated")]


@pytest.mark.unit
def test_a_memo_table_after_the_portfolio_is_not_read_as_holdings():
    rows = [["Sundaram Aggressive Hybrid Fund"], ["Portfolio as on 30-Sep-2026"],
            ["SL No", "ISIN Code", "Name of the instrument", "Rating / Industry", "Quantity",
             "Mkt Value Rs. in Lacs", "% of Net Asset"],
            [1, "INE090A01021", "ICICI Bank Ltd", "Banks", 3280624, 43360.0, 0.0493],
            [2, "INE002A01018", "Reliance", "Petroleum Products", 2708684, 32152.0, 0.0366],
            [None, "ISIN", "NAME OF THE SECURITY", "TOTAL AMOUNT DUE (Rs. in Lacs)", None, None, "(Rs. in Lacs)"],
            [None, "INE123A07012", "Defaulted NCD", 1500.0, None, None, 1500.0]]
    got = P.parse_sheet(rows, "SPAHF", {})
    assert [r["isin"] for r in got] == ["INE090A01021", "INE002A01018"]
    assert got[0]["pct"] == pytest.approx(4.93)          # fractions rescaled once the memo rows are out


@pytest.mark.unit
def test_a_date_beside_its_label_wins_and_an_inception_date_never_does():
    rows = [["Capitalmind Mutual Fund"], ["SCHEME NAME :", "Capitalmind Multi Asset Allocation Fund"],
            ["INCEPTION DATE :", "March 16, 2026"], ["MONTHLY PORTFOLIO STATEMENT AS ON :", "September 30, 2026"],
            ["Name of Instrument / Issuer", "ISIN", "Rating / Industry", "Quantity", "Market Value (Rs. in Lakhs)", "% to NAV"],
            ["Bajaj Auto Limited", "INE917I01010", "Automobiles", 1164, 126.57, 0.0344]]
    r = P.parse_sheet(rows, "CMMAAF", {})[0]
    assert r["as_of"] == date(2026, 9, 30)
    assert r["scheme"] == "Capitalmind Multi Asset Allocation Fund"
