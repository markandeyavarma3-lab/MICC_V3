"""NSDL daily FPI flows: the month request, the page check, and the three layouts.

NSDL's archive serves any month since December 1998, one month per form
post. The page layout changed twice — no route column before ~2009, more
debt and fund categories by 2026 — and the parser reads each row by its shape.
These tests use small hand-built pages in each layout; no test touches NSDL.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.archive import fpi_nsdl as col
from src.ingest import fpi_nsdl as ing

pytestmark = pytest.mark.unit


def _page(title_date: str, header: list[str], rows: list[list[str]],
          deriv_rows: list[list[str]] | None = None) -> str:
    tr = lambda cells: "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"  # noqa: E731
    body = [tr([f"Daily Trends in FPI Investments up to {title_date}"]), tr(header)] + [tr(r) for r in rows]
    if deriv_rows is not None:
        body += [tr(["Reporting Date", "Derivative Products", "Buy", "Sell", "Open Interest at the end of the date"]),
                 tr(["No. of Contracts", "Amount in Crore", "No. of Contracts", "Amount in Crore",
                     "No. of Contracts", "Amount in Crore"])] + [tr(r) for r in deriv_rows]
    return f"<html><div id='dvArchiveData'><table>{''.join(body)}</table></div></html>"


OLD_HEAD = ["Reporting Date", "Debt/Equity", "Gross Purchases(Rs Crore)", "Gross Sales(Rs Crore)",
            "Net Investment (Rs Crore)", "Net Investment US($) million", "Conversion (1 USD TO INR)*"]
NEW_HEAD = ["Reporting Date", "Debt/Equity", "Investment Route", "Gross Purchases(Rs Crore)",
            "Gross Sales(Rs Crore)", "Net Investment (Rs Crore)", "Net Investment US($) million",
            "Conversion (1 USD TO INR)*"]


# --- numbers as NSDL writes them ------------------------------------------------------


def test_parenthesised_numbers_are_negative_and_commas_are_thousands():
    assert ing.num("(6139.56)") == -6139.56
    assert ing.num("1,234.50") == 1234.5
    assert ing.num("-") is None and ing.num("") is None


def test_the_rate_is_read_after_the_rs_prefix_not_from_its_dot():
    """'Rs.95.4509' matched '.' first and raised on the first real page."""
    assert ing.fx("Rs.95.4509") == 95.4509
    assert ing.fx("Rs. 42.49") == 42.49


# --- the three layouts -------------------------------------------------------------------


def test_the_1999_layout_has_no_route_and_the_debt_line_inherits_the_date():
    html = _page("31-Jan-1999", OLD_HEAD, [
        ["01-Jan-1999", "Equity", "32.50", "7.50", "25.00", "5.90", "Rs. 42.48"],
        ["Debt", "0.00", "0.00", "0.00", "0.00"],
    ])
    flows, derivs = ing.parse_page(html)
    assert [(f.reporting_date, f.category, f.route, f.net_cr) for f in flows] == [
        ("1999-01-01", "Equity", "", 25.0), ("1999-01-01", "Debt", "", 0.0)]
    assert all(f.usd_inr == 42.48 for f in flows) and derivs == []


def test_the_route_layout_carries_category_and_date_down_its_rows():
    html = _page("31-Jan-2010", NEW_HEAD, [
        ["04-Jan-2010", "Equity", "Stock Exchange", "2688.80", "1841.30", "847.50", "181.55", "Rs.46.68"],
        ["Primary market & others", "13.70", "27.10", "(13.40)", "(2.88)"],
        ["Sub-total", "2702.50", "1868.50", "834.00", "178.67"],
        ["Debt", "Stock Exchange", "1065.10", "214.10", "851.00", "182.31"],
        ["Primary market & others", "20.80", "454.80", "(434.00)", "(92.97)"],
        ["Sub-total", "1085.90", "668.90", "417.00", "89.33"],
        ["Total", "3788.40", "2537.40", "1251.00", "268.00"],
        ["Total for January", "1", "2", "3", "4", "5", "6", "7"],
    ])
    flows, _ = ing.parse_page(html)
    got = {(f.category, f.route): f.net_cr for f in flows}
    assert got[("Equity", "Primary market & others")] == -13.4
    assert got[("Debt", "Sub-total")] == 417.0
    assert got[("Total", "")] == 1251.0
    assert {f.reporting_date for f in flows} == {"2010-01-04"}
    assert not any(f.category.startswith("Total for") for f in flows), "derived month totals kept"


def test_a_2026_scheme_line_without_a_route_is_its_own_category():
    html = _page("25-Sep-2026", NEW_HEAD, [
        ["01-Sep-2026", "Equity", "Stock Exchange", "65512.88", "71652.44", "(6139.56)", "(643.22)", "Rs.95.4509"],
        ["Mutual Funds", "Stock Exchange", "10.00", "5.00", "5.00", "0.52"],
        ["Debt schemes", "1.00", "0.00", "1.00", "0.10"],
    ])
    flows, _ = ing.parse_page(html)
    assert ("Debt schemes", "") in {(f.category, f.route) for f in flows}
    assert next(f for f in flows if f.category == "Equity").net_cr == -6139.56


def test_derivatives_are_read_and_upper_case_period_summaries_are_dropped():
    html = _page("25-Sep-2026", NEW_HEAD, [
        ["01-Sep-2026", "Equity", "Stock Exchange", "1", "1", "0", "0", "Rs.95"]],
        deriv_rows=[
            ["01-Sep-2026", "Index Futures", "11853.00", "1915.47", "18599.00", "2962.68", "258931.00", "42189.53"],
            ["Index Options", "10.00", "1.00", "20.00", "2.00", "30.00", "3.00"],
            ["INDEX OPTIONS", "99", "99", "99", "99", "99", "99"],
        ])
    _, derivs = ing.parse_page(html)
    assert [(d.product, d.oi_cr) for d in derivs] == [("Index Futures", 42189.53), ("Index Options", 3.0)]
    assert all(d.reporting_date == "2026-09-01" for d in derivs)


def test_the_newest_page_for_a_month_wins():
    files = ["x/FPI_DAILY_NSDL_20260925_aaaaaaaa.html.gz",
             "x/FPI_DAILY_NSDL_20260929_bbbbbbbb.html.gz",
             "x/FPI_DAILY_NSDL_20260831_cccccccc.html.gz"]
    assert ing.newest_per_month(files) == [files[2], files[1]]


# --- the collector's month arithmetic and page check ----------------------------------------


def test_each_month_is_asked_for_by_its_last_day_or_today():
    assert col.request_date(date(2024, 2, 1), date(2026, 9, 29)) == date(2024, 2, 29)
    assert col.request_date(date(2026, 9, 1), date(2026, 9, 29)) == date(2026, 9, 29)


def test_months_run_from_first_to_last_inclusive():
    assert col.months(date(1998, 12, 15), date(1999, 2, 1)) == [
        date(1998, 12, 1), date(1999, 1, 1), date(1999, 2, 1)]


def test_a_page_for_a_different_date_is_refused():
    html = _page("31-Jan-2010", NEW_HEAD, [["04-Jan-2010", "Equity", "Stock Exchange", "1", "1", "0", "0", "Rs.46"]])
    assert col.verify(html.encode(), date(2010, 1, 31)) is None
    assert "asked for" in col.verify(html.encode(), date(2010, 2, 28))


def test_a_partial_page_is_not_filed_as_the_whole_month():
    """Same month, earlier date: a page 'up to 25-Jan' stored for 31-Jan would
    mark January settled with its last week missing, and never re-fetch it."""
    html = _page("25-Jan-2010", NEW_HEAD, [["04-Jan-2010", "Equity", "Stock Exchange", "1", "1", "0", "0", "Rs.46"]])
    assert "page says up to 2010-01-25" in col.verify(html.encode(), date(2010, 1, 31))


def test_a_page_that_is_not_the_report_is_refused():
    """The login page NSDL answered to a mis-formatted date on 2026-09-29."""
    assert "not the report page" in col.verify(b"<html>NSDL : Login</html>", date(2010, 1, 31))


def test_the_current_and_previous_month_are_always_refetched(monkeypatch):
    """NSDL fills the current month in daily and may revise the last one."""
    monkeypatch.setattr(col, "settled_months", lambda: {"2026-08", "2026-07"})
    w = col.wanted(date(2026, 9, 29), start=date(2026, 7, 1))
    assert w == [date(2026, 8, 1), date(2026, 9, 1)]


# --- found on the real pages (2026-09-29) ---------------------------------------------------


def test_rows_continuing_a_month_total_are_not_attached_to_the_last_day():
    """THE BUG THE REAL PAGES SHOWED. After 'Total for January' (Equity), the
    next row is the MONTH's Debt total. It was filed as the last day's Debt,
    overwriting the real figure — invisible in any hand-built page that did
    not continue past a total row."""
    html = _page("31-Jan-1999", OLD_HEAD, [
        ["29-Jan-1999", "Equity", "10.00", "5.00", "5.00", "1.00", "Rs. 42.40"],
        ["Debt", "1.00", "0.00", "1.00", "0.20"],
        ["Total for January", "Equity", "999.00", "1.00", "998.00", "200.00", ""],
        ["Debt", "777.00", "0.00", "777.00", "150.00"],
        ["Grand Total Till January 31, 1999", "Equity", "50000.00", "1.00", "49999.00", "9000.00", ""],
        ["Debt", "3000.00", "0.00", "3000.00", "600.00"],
    ])
    flows, _ = ing.parse_page(html)
    debt = [f for f in flows if f.category == "Debt"]
    assert [(f.reporting_date, f.net_cr) for f in debt] == [("1999-01-29", 1.0)]
    assert len(flows) == 2


def test_the_series_opening_balance_is_flagged_not_counted_as_a_day():
    """31-Dec-1998 equals the page's own 'Grand Total Till December 31, 1998':
    every FII flow since 1992, not one day's."""
    html = _page("31-Dec-1998", OLD_HEAD, [
        ["31-Dec-1998", "Equity", "65416.40", "36352.60", "29064.10", "8698.40", "Rs. 42.54"],
        ["Debt", "1744.10", "2037.20", "(293.10)", "(48.30)"],
    ])
    flows, _ = ing.parse_page(html)
    assert flows and not any(f.is_daily_flow for f in flows)
    later, _ = ing.parse_page(html.replace("31-Dec-1998", "04-Jan-1999"))
    assert all(f.is_daily_flow for f in later)


def test_a_repeated_date_moves_to_the_missing_next_day_and_says_so():
    """February 2000: two days printed 28-Feb, none 29-Feb, page up to
    29-Feb, and the month total includes both. The second is the 29th."""
    html = _page("29-Feb-2000", OLD_HEAD, [
        ["28-Feb-2000", "Equity", "552.90", "383.00", "169.90", "38.90", "Rs. 43.63"],
        ["Debt", "0.00", "0.00", "0.00", "0.00"],
        ["28-Feb-2000", "Equity", "224.90", "152.10", "72.80", "16.70", "Rs. 43.63"],
        ["Debt", "0.00", "0.00", "0.00", "0.00"],
    ])
    flows, _ = ing.parse_page(html)
    eq = {f.reporting_date: (f.net_cr, f.date_corrected) for f in flows if f.category == "Equity"}
    assert eq == {"2000-02-28": (169.9, False), "2000-02-29": (72.8, True)}


def test_a_repeated_date_is_dropped_when_the_next_day_is_already_there():
    """Never guessed: with the 29th present, a second 28th has nowhere to go."""
    html = _page("29-Feb-2000", OLD_HEAD, [
        ["28-Feb-2000", "Equity", "1", "0", "1", "0", "Rs. 43"],
        ["28-Feb-2000", "Equity", "2", "0", "2", "0", "Rs. 43"],
        ["29-Feb-2000", "Equity", "3", "0", "3", "0", "Rs. 43"],
    ])
    flows, _ = ing.parse_page(html)
    assert [(f.reporting_date, f.net_cr) for f in flows] == [("2000-02-28", 1.0), ("2000-02-29", 3.0)]
