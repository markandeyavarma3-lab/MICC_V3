"""results.py — archived results XBRL (src/archive/results.py) -> one row per
(company, quarter-end, standalone/consolidated).

THE QUARTER IS THE `OneD` CONTEXT. Measured 2026-10-10 on old-route
(INFY 2024-12-31), new-route (TCS 2026-06-30) and bank (HDFCBANK 2026-06-30)
filings: `OneD` carries the three months to the quarter-end; `FourD`, where
present, the year to date. A filing without a `OneD` falls back to the
undimensioned duration context whose span is 80-100 days.

BANKS NAME THINGS DIFFERENTLY: InterestEarned (not RevenueFromOperations),
ProfitLossForThePeriod, BasicEarningsPerShareAfterExtraordinaryItems. Each
field below lists its synonyms in priority order; `bank` records which taxonomy
answered. Amounts are rupees in the filing and Rs crore here.

Paid-up equity capital / face value = shares outstanding, which with a price
gives market capitalisation on the site.

    RESEARCH_ENV=prod .venv/bin/python -m src.ingest.results
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.archive import results as R  # noqa: E402
from src.common.paths import COLLECTED  # noqa: E402

OUT = COLLECTED / "results" / "results_quarterly.parquet"
CR = 1e7

FIELDS: dict[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromOperations", "InterestEarned"),
    "other_income": ("OtherIncome",),
    "total_income": ("Income", "TotalIncome"),
    "expenses": ("Expenses", "TotalExpenses"),
    "finance_costs": ("FinanceCosts", "InterestExpended"),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense",),
    "operating_expenses": ("OperatingExpenses",),
    "pbt": ("ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax"),
    "tax": ("TaxExpense",),
    "pat": ("ProfitLossForPeriod", "ProfitLossForThePeriod"),
    "pat_owners": ("ProfitOrLossAttributableToOwnersOfParent",),
    "eps": ("BasicEarningsLossPerShareFromContinuingOperations", "BasicEarningsPerShareAfterExtraordinaryItems",
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations"),
    "face_value": ("FaceValueOfEquityShareCapital",),
    "paid_up": ("PaidUpValueOfEquityShareCapital",),
}
RUPEE_FIELDS = {"revenue", "other_income", "total_income", "expenses", "finance_costs", "depreciation",
                "operating_expenses", "pbt", "tax", "pat", "pat_owners", "paid_up"}

_QUARTER_NO = {"first quarter": 1, "second quarter": 2, "third quarter": 3, "fourth quarter": 4}
_CTX = re.compile(r'<xbrli:context id="([^"]+)"[^>]*>(.*?)</xbrli:context>', re.S)
_START = re.compile(r"<xbrli:startDate>([\d-]+)</xbrli:startDate>")
_END = re.compile(r"<xbrli:endDate>([\d-]+)</xbrli:endDate>")
_FACT = re.compile(r'<[A-Za-z0-9-]+:([A-Za-z0-9]+)\s[^>]*contextRef="([^"]+)"[^>]*>([^<]*)<')


def quarter_context(text: str) -> str | None:
    spans = {}
    for cid, body in _CTX.findall(text):
        if "xbrldi:" in body:
            continue
        s, e = _START.search(body), _END.search(body)
        if s and e:
            spans[cid] = (date.fromisoformat(s.group(1)), date.fromisoformat(e.group(1)))
    if "OneD" in spans:
        return "OneD"
    for cid, (s, e) in spans.items():
        if 80 <= (e - s).days <= 100:
            return cid
    # NSE's 2016-2023 '_WEB' renderings (INDAS, NBFC, BANKING) reference OneD
    # without defining it (ALKEM 2021-06-30, measured 2026-10-21); their
    # dimensioned 'One...' contexts span the quarter, so OneD is the quarter.
    # parse() checks the filing's own reporting-period dates before keeping it.
    if 'contextRef="OneD"' in text:
        return "OneD"
    return None


def parse(text: str) -> dict | None:
    cid = quarter_context(text)
    if not cid:
        return None
    facts: dict[str, str] = {}
    for name, ref, val in _FACT.findall(text):
        if ref == cid:
            facts.setdefault(name, val.strip())
    row: dict = {}
    for field, names in FIELDS.items():
        for n in names:
            if facts.get(n) not in (None, ""):
                try:
                    v = float(facts[n])
                except ValueError:
                    continue
                row[field] = v / CR if field in RUPEE_FIELDS else v
                break
    row["bank"] = "InterestEarned" in facts
    s, e = facts.get("DateOfStartOfReportingPeriod"), facts.get("DateOfEndOfReportingPeriod")
    row["period_start"], row["period_end"] = s, e
    if cid == "OneD" and f'id="{cid}"' not in text:
        # An undefined OneD is trusted only when the filing states a quarter-long
        # period, or (banks and pre-Ind-AS filings, which state no start date) names
        # its ReportingQuarter as a quarter: the quarter's end is then the financial
        # year's start plus 3, 6, 9 or 12 months, and main() checks it against the
        # quarter NSE files it under. 'Half yearly' and 'Yearly' filings stay out:
        # their figures may span six or twelve months.
        try:
            if not 80 <= (date.fromisoformat(e) - date.fromisoformat(s)).days <= 100:
                return None
        except (TypeError, ValueError):
            k = _QUARTER_NO.get((facts.get("ReportingQuarter") or "").strip().lower())
            try:
                fy = date.fromisoformat(facts.get("DateOfStartOfFinancialYear") or "")
            except ValueError:
                return None
            if not k:
                return None
            y, m = divmod(fy.year * 12 + fy.month - 1 + 3 * k, 12)
            row["period_end"] = (date(y, m + 1, 1) - timedelta(days=1)).isoformat()
    row["nature"] = facts.get("NatureOfReportStandaloneConsolidated")
    row["audited"] = facts.get("WhetherResultsAreAuditedOrUnaudited")
    return row if any(k in row for k in ("revenue", "pat")) else None


# --- the pre-XBRL HTML tables (2005-2017) ----------------------------------
# NSE's nsearchives/archives/financial_results/financial_res_<SYM>_<seq>.html:
# one <tr> per line item, label then amount, the unit stated once
# ('Amount(Rs. in lakhs)'). The wording differs by format and by bank/non-bank
# (INFY 2014, HDFCBANK 2012, 20MICRONS 2011, measured 2026-10-24); each field
# lists its wordings in priority order, matched at the start of the label.
HTML_FIELDS: dict[str, tuple[str, ...]] = {
    "revenue": (r"(\(a\) )?net sales ?/ ?income from operation", r"interest earned", r"total income from operations"),
    "other_income": (r"other income",),
    "total_income": (r"total income$",),
    "expenses": (r"total expen",),
    "finance_costs": (r"finance costs", r"interest$", r"interest expended"),
    "depreciation": (r"(\(e\) )?depreciation",),
    "pbt": (r".*from ordinary activities before tax",),
    "tax": (r"tax expense",),
    "pat": (r"net profit ?(\(\+\) ?)?/ ?\(?loss\)? ?(\(-\) )?for the period",),
    "pat_owners": (r"net profit.*after taxes, minority interest",),
    "eps": (r"(\(a\) )?basic( eps before extraordinary items)?\b",),
    "face_value": (r"face value",),
    "paid_up": (r"paid-?up equity share capital",),
}
_UNIT = {"lakh": 100.0, "crore": 1.0, "thousand": 1e4, "million": 10.0}
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)


def _cell(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&amp;", "&").replace("&nbsp;", " ").strip()


def parse_html(text: str) -> dict | None:
    """One pre-XBRL results table -> the same row parse() returns, amounts in Rs crore."""
    pairs = []
    for tr in _TR.findall(text):
        cells = [_cell(c) for c in _TD.findall(tr)]
        # Header rows hold several label | value pairs ('Period | Quarterly | Period Ended | 31-Dec-2014').
        for i in range(0, len(cells) - 1, 2):
            if cells[i]:
                pairs.append((cells[i].lower(), cells[i + 1]))
    if not pairs:
        return None
    unit = next((v.lower() + " " + k for k, v in pairs if k.startswith("description") or "amount" in k), "")
    div = next((d for w, d in _UNIT.items() if w in unit), None)
    if div is None:
        div = 1e7 if re.search(r"rs\.?\)|in rs\b|rupees", unit) else None
    if div is None:
        return None                                  # no stated unit: an amount cannot be read safely
    row: dict = {}
    for field, pats in HTML_FIELDS.items():
        for pat in pats:
            v = next((v for k, v in pairs if re.match(pat, k)), None)
            if v in (None, "", "-"):
                continue
            try:
                x = float(v.replace(",", ""))
            except ValueError:
                continue
            row[field] = x / div if field in RUPEE_FIELDS else x
            break
    row["bank"] = any(k.startswith("interest earned") for k, _ in pairs)
    pe = next((v for k, v in pairs if k.startswith("period ended")), None)
    try:
        row["period_end"] = datetime.strptime(pe, "%d-%b-%Y").date().isoformat() if pe else None
    except ValueError:
        row["period_end"] = None
    row["period_start"] = None
    row["nature"] = next((v for k, v in pairs if k.startswith("consolidated / non")), None)
    row["audited"] = next((v for k, v in pairs if k.startswith("audited / un") or k.startswith("un-audited")), None)
    return row if any(k in row for k in ("revenue", "pat")) else None


def main() -> int:
    import duckdb
    rows = []
    bad = mislabelled = 0
    for ln in R.MANIFEST.read_text().splitlines() if R.MANIFEST.exists() else []:
        r = json.loads(ln)
        if r.get("kind") not in ("xbrl", "html") or r.get("status") != "STORED":
            continue
        try:
            text = gzip.decompress(Path(r["path"]).read_bytes()).decode("utf-8", "replace")
            p = parse_html(text) if r["kind"] == "html" else parse(text)
        except (OSError, ValueError):
            p = None
        if not p:
            bad += 1
            continue
        if p.get("period_end") and p["period_end"] != r["qe"]:
            # NSE's index files some filings under the wrong quarter (AEGISLOG's
            # '2017-03-31' is Jan-Mar 2018; 13 of 35,901 on 2026-10-21). The file's own
            # period is right, but relabelling could collide with a genuine filing: drop it.
            mislabelled += 1
            continue
        rows.append({"symbol": r["symbol"], "qe": r["qe"], "consolidated": r["consolidated"], "filed": r["filed"],
                     "route": r["route"], **p})
    cols = ["symbol", "qe", "consolidated", "filed", "route", "nature", "audited", "bank", "period_start",
            "period_end", *FIELDS]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE t (" + ", ".join(
            f"{c} {'BOOLEAN' if c in ('consolidated', 'bank') else 'DOUBLE' if c in FIELDS else 'VARCHAR'}"
            for c in cols) + ")")
        con.executemany(f"INSERT INTO t VALUES ({', '.join('?' * len(cols))})",
                        [[r.get(c) for c in cols] for r in rows])
        tmp = OUT.with_suffix(".parquet.partial")
        con.execute(f"COPY (SELECT * FROM t ORDER BY symbol, qe) TO '{tmp}' (FORMAT PARQUET)")
        tmp.replace(OUT)
    finally:
        con.close()
    print(f"  RESULTS: {len(rows):,} quarterly rows for {len({r['symbol'] for r in rows}):,} companies"
          f" ({bad} files without a quarter or a revenue/profit line; {mislabelled} filed under the wrong quarter, dropped) -> {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
