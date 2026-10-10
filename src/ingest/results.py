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
from datetime import date
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
    row["nature"] = facts.get("NatureOfReportStandaloneConsolidated")
    row["audited"] = facts.get("WhetherResultsAreAuditedOrUnaudited")
    return row if any(k in row for k in ("revenue", "pat")) else None


def main() -> int:
    import duckdb
    rows = []
    bad = 0
    for ln in R.MANIFEST.read_text().splitlines() if R.MANIFEST.exists() else []:
        r = json.loads(ln)
        if r.get("kind") != "xbrl" or r.get("status") != "STORED":
            continue
        try:
            p = parse(gzip.decompress(Path(r["path"]).read_bytes()).decode("utf-8", "replace"))
        except (OSError, ValueError):
            p = None
        if not p:
            bad += 1
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
          f" ({bad} files without a quarter or a revenue/profit line) -> {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
