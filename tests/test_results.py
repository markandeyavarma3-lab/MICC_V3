"""Quarterly results: which filing is fetched, how it is read, and the
valuation the site derives (src/archive/results.py, src/ingest/results.py,
src/site/export.valuation)."""

from __future__ import annotations

import pytest

from src.archive import results as R
from src.ingest import results as I
from src.site import export as X

pytestmark = pytest.mark.unit


def test_consolidated_and_latest_revision_win_and_only_the_newest_quarters_are_kept():
    old = [{"toDate": "31-Dec-2024", "consolidated": "Non-Consolidated", "xbrl": "s1.xml", "broadCastDate": "10-Jan-2025 10:00:00"},
           {"toDate": "31-Dec-2024", "consolidated": "Consolidated", "xbrl": "c1.xml", "broadCastDate": "10-Jan-2025 10:00:00"},
           {"toDate": "30-Sep-2024", "consolidated": "Non-Consolidated", "xbrl": "s0.xml", "broadCastDate": "10-Oct-2024 10:00:00"}]
    new = [{"qe_Date": "31-MAR-2025", "consolidated": "Consolidated", "xbrl": "c2.xml", "broadcast_Date": "10-Apr-2025 10:00:00",
            "type": "Integrated Filing- Financials"},
           {"qe_Date": "31-MAR-2025", "consolidated": "Consolidated", "xbrl": "c2r.xml", "broadcast_Date": "20-May-2025 10:00:00",
            "type": "Integrated Filing- Financials"}]
    t = R.targets(old, new, quarters=2)
    assert [(x["qe"], x["url"]) for x in t] == [("2025-03-31", "c2r.xml"), ("2024-12-31", "c1.xml")]


def _xbrl(facts: str, start="2026-04-01", end="2026-06-30") -> str:
    return (f'<xbrli:context id="OneD"><xbrli:entity/><xbrli:period><xbrli:startDate>{start}</xbrli:startDate>'
            f'<xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>' + facts)


def test_a_company_filing_reads_the_quarter_in_crore():
    x = _xbrl('<in-capmkt:RevenueFromOperations contextRef="OneD" unitRef="INR">722750000000</in-capmkt:RevenueFromOperations>'
              '<in-capmkt:ProfitLossForPeriod contextRef="OneD" unitRef="INR">134200000000</in-capmkt:ProfitLossForPeriod>'
              '<in-capmkt:BasicEarningsLossPerShareFromContinuingOperations contextRef="OneD" unitRef="INRPerShare">36.9</in-capmkt:BasicEarningsLossPerShareFromContinuingOperations>')
    r = I.parse(x)
    assert r["revenue"] == 72275.0 and r["pat"] == 13420.0 and r["eps"] == 36.9 and not r["bank"]


def test_an_undefined_oned_is_read_only_when_the_filing_states_a_quarter():
    # NSE's older _WEB renderings reference OneD without defining it (ALKEM 2021-06-30).
    def web(start, end):
        return (f'<in-bse-fin:DateOfStartOfReportingPeriod contextRef="OneD">{start}</in-bse-fin:DateOfStartOfReportingPeriod>'
                f'<in-bse-fin:DateOfEndOfReportingPeriod contextRef="OneD">{end}</in-bse-fin:DateOfEndOfReportingPeriod>'
                '<in-bse-fin:RevenueFromOperations contextRef="OneD" unitRef="INR">27313600000.00</in-bse-fin:RevenueFromOperations>')
    r = I.parse(web("2021-04-01", "2021-06-30"))
    assert r["revenue"] == 2731.36 and r["period_end"] == "2021-06-30"
    assert I.parse(web("2021-04-01", "2022-03-31")) is None        # a year, not a quarter
    assert I.parse(web("", "")) is None                              # no stated period


def test_a_filing_without_a_start_date_is_read_only_when_it_names_a_quarter():
    # Banks and pre-Ind-AS filings state no start date; ReportingQuarter decides (3PLAND, HDFCBANK).
    def old(quarter):
        return ('<in-bse-fin:DateOfStartOfFinancialYear contextRef="OneD">2018-04-01</in-bse-fin:DateOfStartOfFinancialYear>'
                f'<in-bse-fin:ReportingQuarter contextRef="OneD">{quarter}</in-bse-fin:ReportingQuarter>'
                '<in-bse-fin:ProfitLossForThePeriod contextRef="OneD" unitRef="INR">-1200000.00</in-bse-fin:ProfitLossForThePeriod>')
    r = I.parse(old("Third quarter"))
    assert r["pat"] == -0.12 and r["period_end"] == "2018-12-31"
    assert I.parse(old("Fourth quarter"))["period_end"] == "2019-03-31"
    assert I.parse(old("Half yearly")) is None                       # may be six months
    assert I.parse(old("Yearly")) is None


def test_a_bank_filing_reads_interest_earned_as_revenue():
    x = _xbrl('<in-capmkt:InterestEarned contextRef="OneD" unitRef="INR">905753300000</in-capmkt:InterestEarned>'
              '<in-capmkt:ProfitLossForThePeriod contextRef="OneD" unitRef="INR">203826900000</in-capmkt:ProfitLossForThePeriod>')
    r = I.parse(x)
    assert r["bank"] and round(r["revenue"]) == 90575 and round(r["pat"]) == 20383


def test_valuation_uses_profit_not_summed_eps_and_needs_four_consecutive_quarters():
    # rows as fundamentals() builds them: [qe, cons, rev, oi, pbt, pat, pat_owners, eps, fin, dep, shares_cr, bank, filed]
    q = lambda qe, pat, eps, sh: [qe, True, 1000.0, 0, 0, pat, pat, eps, 0, 0, sh, False, ""]  # noqa: E731
    res = [q("2026-06-30", 100, 10.0, 20.0), q("2026-03-31", 100, 10.0, 20.0),
           q("2025-12-31", 100, 20.0, 10.0), q("2025-09-30", 100, 20.0, 10.0)]   # a 1:1 bonus inside the window
    v = X.valuation(res, 50.0)
    assert v["mcap_cr"] == 1000 and v["ttm_profit_cr"] == 400 and v["pe"] == 2.5
    gap = [res[0], res[1], res[2], q("2024-06-30", 100, 20.0, 10.0)]
    assert X.valuation(gap, 50.0)["pe"] is None


def test_a_filing_without_an_xbrl_file_is_not_a_target():
    # AMARJOTHI, 2026-10-10: "-" in the xbrl field; six 404s stopped the night's sweep.
    from src.archive import results as R
    old = [{"toDate": "30-Jun-2026", "xbrl": "-", "broadCastDate": "10-Aug-2026 10:00:00", "consolidated": "Consolidated"},
           {"toDate": "30-Jun-2026", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/X_1.xml",
            "broadCastDate": "10-Aug-2026 10:00:00", "consolidated": "Non-Consolidated"}]
    got = R.targets(old, [])
    assert [t["url"] for t in got] == ["https://nsearchives.nseindia.com/corporate/xbrl/X_1.xml"]


def test_a_file_nse_answered_404_for_is_never_asked_for_again(tmp_path):
    import json
    m = tmp_path / "manifest.jsonl"
    rows = [{"kind": "xbrl", "status": "FAILED", "url": "u/missing", "error": "all 3 attempts failed: HTTP Error 404: Not Found"},
            {"kind": "xbrl", "status": "FAILED", "url": "u/refused", "error": "HTTP Error 403: Forbidden"},
            {"kind": "xbrl", "status": "STORED", "url": "u/held"}]
    m.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert R.gone(m) == {"u/missing"}          # a refusal is retried; only a 404 is final


def test_a_quarter_without_xbrl_falls_back_to_the_html_table_and_only_then():
    xml = {"toDate": "31-Mar-2018", "xbrl": "https://x/a.xml", "consolidated": "Consolidated",
           "broadCastDate": "10-May-2018 10:00:00", "period": "Quarterly",
           "resultDetailedDataLink": "https://x/financial_res_A_2.html"}
    old = {"toDate": "31-Dec-2014", "xbrl": "https://x/-", "consolidated": "Non-Consolidated",
           "broadCastDate": "19-Jan-2015 11:41:01", "period": "Quarterly",
           "resultDetailedDataLink": "https://x/financial_res_A_1.html"}
    got = {t["qe"]: (t["url"], t.get("kind", "xbrl")) for t in R.targets([xml, old], [], 90)}
    assert got == {"2018-03-31": ("https://x/a.xml", "xbrl"), "2014-12-31": ("https://x/financial_res_A_1.html", "html")}


def test_the_pre_xbrl_html_table_reads_in_crore():
    rows = [("Consolidated / Non-Consolidated", "Non-Consolidated", "Period Ended", "31-Dec-2014"),
            ("Description", "Amount(Rs. in lakhs)"),
            ("(a) Net sales/income from operations (Net of excise duty)", "1219200.00"),
            ("Net Profit / (Loss) for the period", "305500.00"), ("(a) Basic", "26.73"), ("Exceptional items", "-")]
    html = "<table>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>"
    r = I.parse_html(html)
    assert (r["revenue"], r["pat"], r["eps"], r["period_end"], r["bank"]) == (12192.0, 3055.0, 26.73, "2014-12-31", False)
    assert I.parse_html(html.replace("Amount(Rs. in lakhs)", "Amount")) is None   # no unit, no amounts


def test_an_empty_results_page_is_missing_for_good_not_a_refusal(tmp_path, monkeypatch):
    """nsearchives answers a page it does not hold with an empty 200; six in a row
    stopped the 2026-10-25 run as if refused."""
    import json
    monkeypatch.setattr(R, "MANIFEST", tmp_path / "manifest.jsonl")
    monkeypatch.setattr(R, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(R, "RATE_LIMIT", 0)
    old = [{"toDate": f"31-Dec-{y}", "xbrl": "https://x/-", "consolidated": "Non-Consolidated",
            "broadCastDate": f"10-Feb-{y + 1} 10:00:00", "period": "Quarterly",
            "resultDetailedDataLink": f"https://x/financial_res_A_{y}.html"} for y in range(2005, 2015)]
    monkeypatch.setattr(R, "latest_listings", lambda s: {"old": old, "new": []})
    monkeypatch.setattr(R, "state", lambda: ({"A": "9999"}, set()))
    monkeypatch.setattr(R.ca, "_opener", lambda: None)
    monkeypatch.setattr(R.ca, "_get", lambda op, u, ref: b"")
    st = R.sweep(["A"], max_files=100, max_minutes=5, quarters=90)
    assert st["stopped"] == "" and st["failed"] == 10                  # all ten tried; no breaker
    assert len(R.gone(R.MANIFEST)) == 10                                # and none asked for again
    assert all("404" in json.loads(ln)["error"] for ln in R.MANIFEST.read_text().splitlines())
