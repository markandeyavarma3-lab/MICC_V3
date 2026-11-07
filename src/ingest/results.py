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

INSURERS FILE A THIRD TAXONOMY (INTEGRATED_FILING_LI / _GI, measured 2026-11-06
on LICI and GICRE): no revenue line and no ProfitLossForPeriod, so every one
parsed to nothing. `revenue` is net premium for them, NetPremiumIncome for life
and PremiumEarned for general; they state no paid-up capital, so no share count.

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
#: Six-month figures, apart from the quarters: most SME companies report only this
#: way (1,020 of 1,152 filings on 2026-11-07), and a half-year in the quarterly file
#: would double a growth figure. The site shows them under their own heading.
OUT_HALF = COLLECTED / "results" / "results_half.parquet"
HALF_COLS = ["symbol", "period_end", "consolidated", "filed", "revenue", "pbt", "pat", "eps"]
CR = 1e7

FIELDS: dict[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromOperations", "InterestEarned", "NetPremiumIncome", "PremiumEarned"),
    "other_income": ("OtherIncome",),
    "total_income": ("Income", "TotalIncome"),
    "expenses": ("Expenses", "TotalExpenses"),
    "finance_costs": ("FinanceCosts", "InterestExpended"),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense",),
    "operating_expenses": ("OperatingExpenses",),
    "pbt": ("ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax", "ProfitLossBeforeTax", "ProfitOrLossBeforeTax"),
    "tax": ("TaxExpense",),
    "pat": ("ProfitLossForPeriod", "ProfitLossForThePeriod", "ProfitLossAfterTaxAndExtraordinaryItems", "ProfitLossAfterTax"),
    "pat_owners": ("ProfitOrLossAttributableToOwnersOfParent",),
    "eps": ("BasicEarningsLossPerShareFromContinuingOperations", "BasicEarningsPerShareAfterExtraordinaryItems",
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
            "BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized"),
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
    quarter = lambda c: 80 <= (spans[c][1] - spans[c][0]).days <= 100  # noqa: E731
    if "OneD" in spans and quarter("OneD"):
        return "OneD"
    # A defined OneD longer than a quarter is a half-year or year filing (365 of
    # them read as quarters until 2026-11-06: AARTIIND's 2026-09-30 was April to
    # September). Its quarter column, if it has one, is another context.
    for cid in spans:
        if quarter(cid):
            return cid
    if "OneD" in spans:
        return None
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
            if not k:
                # 'Half yearly' / 'Yearly' with no start date: banks filed their
                # September and March quarters this way 2018-2021 (KARURVYSYA,
                # INDUSINDBK). OneD is usually the quarter, but 8% of them came
                # out ~2x their neighbours, a half-year. Kept only if main()
                # finds the figure in line with the quarters either side.
                if (facts.get("ReportingQuarter") or "").strip().lower() not in ("half yearly", "yearly"):
                    return None
                try:
                    row["period_end"] = date.fromisoformat(e or "").isoformat()
                except ValueError:
                    return None
                row["span_unchecked"] = True
                return row if any(k in row for k in ("revenue", "pat")) else None
            try:
                fy = date.fromisoformat(facts.get("DateOfStartOfFinancialYear") or "")
            except ValueError:
                return None
            y, m = divmod(fy.year * 12 + fy.month - 1 + 3 * k, 12)
            row["period_end"] = (date(y, m + 1, 1) - timedelta(days=1)).isoformat()
    row["nature"] = facts.get("NatureOfReportStandaloneConsolidated")
    row["audited"] = facts.get("WhetherResultsAreAuditedOrUnaudited")
    return row if any(k in row for k in ("revenue", "pat")) else None


def parse_half(text: str) -> dict | None:
    """A filing whose OneD spans about six months: its figures, or None. Only
    called on a filing parse() refused, so a quarter column always wins."""
    spans = {cid: (_START.search(b), _END.search(b)) for cid, b in _CTX.findall(text) if "xbrldi:" not in b}
    s, e = spans.get("OneD", (None, None))
    if not (s and e):
        return None
    start, end = date.fromisoformat(s.group(1)), date.fromisoformat(e.group(1))
    if not 170 <= (end - start).days <= 190:
        return None
    facts: dict[str, str] = {}
    for name, ref, val in _FACT.findall(text):
        if ref == "OneD":
            facts.setdefault(name, val.strip())
    row: dict = {"period_end": end.isoformat()}
    for field in ("revenue", "pbt", "pat", "eps"):
        for n in FIELDS[field]:
            try:
                v = float(facts[n])
            except (KeyError, ValueError):
                continue
            row[field] = v / CR if field in RUPEE_FIELDS else v
            break
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


def _q(qe: str, k: int) -> str:
    """The quarter-end k quarters from `qe`."""
    y, m = divmod(int(qe[:4]) * 12 + int(qe[5:7]) - 1 + 3 * k, 12)  # m: 0-based month
    first_after = date(y + 1, 1, 1) if m == 11 else date(y, m + 2, 1)
    return (first_after - timedelta(days=1)).isoformat()


#: A quarter's revenue against the mean of the quarters either side. A
#: half-year comes out near 2, a year near 4; 0.6-1.5 holds 85% of real ones.
SPAN_BAND = (0.6, 1.5)


def check_spans(rows: list[dict]) -> tuple[list[dict], int, int]:
    """Keep a 'Half yearly'/'Yearly' figure only when its revenue sits within
    SPAN_BAND of the neighbouring quarters of the same company and basis. No
    neighbour, no revenue, or out of band: left out, not guessed."""
    rev = {(r["symbol"], r["qe"], r["consolidated"]): r.get("revenue")
           for r in rows if not r.get("span_unchecked")}
    out, kept, unsure = [], 0, 0
    for r in rows:
        if not r.pop("span_unchecked", False):
            out.append(r)
            continue
        nb = [v for k in (-1, 1) if (v := rev.get((r["symbol"], _q(r["qe"], k), r["consolidated"])))]
        if r.get("revenue") and nb and SPAN_BAND[0] <= r["revenue"] / (sum(nb) / len(nb)) <= SPAN_BAND[1]:
            out.append(r)
            kept += 1
        else:
            unsure += 1
    return out, kept, unsure


def main() -> int:
    import duckdb
    rows = []
    halves: list[dict] = []
    relabel: list[dict] = []
    bad = mislabelled = 0
    for ln in R.MANIFEST.read_text().splitlines() if R.MANIFEST.exists() else []:
        r = json.loads(ln)
        if r.get("kind") not in ("xbrl", "html") or r.get("status") != "STORED":
            continue
        text = ""
        try:
            text = gzip.decompress(Path(r["path"]).read_bytes()).decode("utf-8", "replace")
            p = parse_html(text) if r["kind"] == "html" else parse(text)
        except (OSError, ValueError):
            p = None
        if not p:
            h = parse_half(text) if r["kind"] == "xbrl" and text else None
            if h:
                halves.append({"symbol": r["symbol"], "consolidated": r["consolidated"], "filed": r["filed"], **h})
            else:
                bad += 1
            continue
        if p.get("period_end") and p["period_end"] != r["qe"]:
            # NSE's index files some filings under the wrong quarter (AEGISLOG's
            # '2017-03-31' is Jan-Mar 2018; 13 of 35,901 on 2026-10-21). The file's own
            # period is right, but relabelling could collide with a genuine filing: drop it.
            relabel.append({"symbol": r["symbol"], "qe": p["period_end"], "consolidated": r["consolidated"],
                            "filed": r["filed"], "route": r["route"], **p})
            continue
        rows.append({"symbol": r["symbol"], "qe": r["qe"], "consolidated": r["consolidated"], "filed": r["filed"],
                     "route": r["route"], **p})
    rows, checked, unsure = check_spans(rows)
    held = {(r["symbol"], r["qe"], r["consolidated"]) for r in rows}
    for r in relabel:
        # The file's own period, where no other filing holds that quarter. Where
        # one does, relabelling would collide with a genuine filing: dropped.
        if (r["symbol"], r["qe"], r["consolidated"]) in held or r["qe"][5:] not in ("03-31", "06-30", "09-30", "12-31"):
            mislabelled += 1
        else:
            held.add((r["symbol"], r["qe"], r["consolidated"]))
            rows.append(r)
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
        con.execute("CREATE TABLE h (symbol VARCHAR, period_end VARCHAR, consolidated BOOLEAN, filed VARCHAR,"
                    " revenue DOUBLE, pbt DOUBLE, pat DOUBLE, eps DOUBLE)")
        if halves:
            con.executemany("INSERT INTO h VALUES (?,?,?,?,?,?,?,?)", [[r.get(c) for c in HALF_COLS] for r in halves])
        tmp = OUT_HALF.with_suffix(".parquet.partial")
        con.execute(f"COPY (SELECT * FROM h ORDER BY symbol, period_end) TO '{tmp}' (FORMAT PARQUET)")
        tmp.replace(OUT_HALF)
    finally:
        con.close()
    print(f"  RESULTS: {len(halves):,} half-yearly rows -> {OUT_HALF.name}")
    print(f"  RESULTS: {len(rows):,} quarterly rows for {len({r['symbol'] for r in rows}):,} companies"
          f" ({bad} files without a quarter or a revenue/profit line; {mislabelled} filed under the wrong quarter and"
          f" colliding, dropped; {len(relabel) - mislabelled} re-dated to their own quarter; {checked} half-yearly/yearly"
          f" kept as in line with their neighbours, {unsure} left out) -> {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
