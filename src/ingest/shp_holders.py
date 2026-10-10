"""shp_holders.py — every NAMED holder in every shareholding filing.

WHY (2026-10-10). `shp.py` reads the category totals (FPI 9.07%, MF 5.68%)
and, for the identity layer, the named PROMOTERS. The same filings also name
every PUBLIC holder above 1% — the FPIs, mutual-fund schemes, insurers, bodies
corporate and individuals — and nothing read them. Across ~41,000 filings
that is a "who owns what" map of the listed market: what each named investor
holds, in which companies, quarter by quarter. It feeds the public site's
investor and company-holder pages (docs/plan/WEBSITE_PLAN.md).

ONE ROW PER (filing, axis, holder): the holder's name as filed, its table
(PROMOTER or PUBLIC), a group (MF, FPI, FOREIGN, INSURANCE, AIF, BANK_FI,
GOVERNMENT, CORPORATE, INDIVIDUAL, OTHER), its percentage of shares (on the
filing's own scale, normalised to percent exactly as shp.py does) and its
share count. Nothing is inferred: a holder below the 1% disclosure line is
simply absent, and absence is not a sale.

The axis -> table rule is shp.PROMOTER_AXES (measured, not read off the
taxonomy); every other named axis is PUBLIC.

    RESEARCH_ENV=prod .venv/bin/python -m src.ingest.shp_holders
"""

from __future__ import annotations

import glob
import gzip
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import COLLECTED  # noqa: E402
from src.ingest import shp  # noqa: E402

OUT = COLLECTED / "shp" / "shp_named_holders.parquet"

#: Public axes -> group. Matched on substrings of the axis name, first hit
#: wins, so the specific lines come before the general ones. Measured on 400
#: random filings (2026-10-10): these cover every named public axis seen.
GROUP_RULES: tuple[tuple[str, str], ...] = (
    ("MutualFunds", "MF"),
    ("ForeignPortfolioInvestor", "FPI"),
    ("InsuranceCompanies", "INSURANCE"),
    ("AlternativeInvestmentFunds", "AIF"),
    ("ProvidentFundsOrPensionFunds", "BANK_FI"),
    ("Banks", "BANK_FI"), ("FinancialInstitution", "BANK_FI"), ("NBFCs", "BANK_FI"),
    ("OtherFinancialInstitutions", "BANK_FI"),
    ("Government", "GOVERNMENT"), ("PresidentOfIndia", "GOVERNMENT"),
    ("InvestorEducationAndProtectionFund", "GOVERNMENT"),
    ("OtherInstitutionsForeign", "FOREIGN"), ("ForeignCompanies", "FOREIGN"),
    ("ForeignDirectInvestment", "FOREIGN"), ("ForeignNationals", "FOREIGN"),
    ("NonResidentIndians", "FOREIGN"), ("OverseasDepositories", "FOREIGN"),
    ("CustodianOrDRHolder", "FOREIGN"), ("ForeignInstitutions", "FOREIGN"),
    ("OtherForeignShareholders", "FOREIGN"), ("NonResidentIndividualsOrForeignIndividuals", "FOREIGN"),
    ("BodiesCorporate", "CORPORATE"),
    ("IndividualShareholders", "INDIVIDUAL"), ("IndividualsOrHUF", "INDIVIDUAL"),
    ("DirectorsAndDirectorsRelatives", "INDIVIDUAL"), ("KeyManagerialPersonnel", "INDIVIDUAL"),
    ("RelativesOfPromoters", "INDIVIDUAL"),
)

#: Category LABELS that filings put in the name field of the "other
#: non-institutions" table — "HUF", "Clearing Members", "Trusts". They are
#: summary lines, not holders; flagged (is_label) and kept, never shown as an
#: investor. Measured 2026-10-10 on the 45 most widespread public names.
_LABEL = re.compile(
    r"^(clearing members?|huf|hindu undivided famil(y|ies)|bodies corporates?|trusts?|llps?|"
    r"limited liability partnerships?|non[- ]resident indians?( \(nris?\))?|nris?|iepf|others?|"
    r"unclaimed( or suspense)?( or escrow)? (shares |securities )?(suspense )?accounts?|foreign nationals?|"
    r"overseas corporate bodies|ocbs?|directors?( or director'?s relatives)?|"
    r"foreign portfolio investors?( \(category[ -]*(i|ii|iii)\))?|firms?|employees|"
    r"foreign institutional investors?|foreign banks?|qualified institutional buyers?|"
    r"key managerial personnel|kmp|escrow accounts?|suspense accounts?|investor education and protection fund)$",
    re.IGNORECASE)


def is_label(name: str) -> bool:
    return bool(_LABEL.match(re.sub(r"\s+", " ", name.strip().rstrip("."))))


_NAMED_TYPED = re.compile(
    r'<xbrldi:typedMember dimension="in-bse-shp:([A-Za-z0-9]+)">\s*'
    r'<in-bse-shp:[A-Za-z0-9]+>([^<]*)</in-bse-shp:[A-Za-z0-9]+>')


def group_of(axis: str) -> str:
    for needle, g in GROUP_RULES:
        if needle in axis:
            return g
    return "OTHER"


def parse_file(path: str) -> list[dict]:
    """Every named holder in one filing. Scale and header exactly as shp.py."""
    with gzip.open(path, "rb") as fh:
        text = fh.read().decode("utf-8", "replace")
    ctx: dict[str, tuple[str, str | None]] = {}
    typed: dict[str, tuple[str, str]] = {}
    for m in shp._CONTEXT_BLOCK.finditer(text):
        cid, block = m.group(1), m.group(2)
        d = shp._CONTEXT_DATE.search(block)
        c = shp._CONTEXT_CATEGORY.search(block)
        if d:
            ctx[cid] = (d.group(1), c.group(1) if c else None)
        t = _NAMED_TYPED.search(block)
        if t:
            typed[cid] = (t.group(1), t.group(2).strip())
    facts: dict[str, dict[str, str]] = {}
    for m in shp._FACT.finditer(text):
        facts.setdefault(m.group(2), {})[m.group(1)] = m.group(3).strip()
    head: dict[str, str] = {}
    for d in facts.values():
        if "ISIN" in d:
            head.update(d)
            break
    total = 0.0
    quarter = ""
    for cref, (period, cat) in ctx.items():
        if cat is None or cref not in facts:
            continue
        quarter = quarter or period
        if cat.lower() in ("shareholdingofpromoterandpromotergroupmember", "publicshareholdingmember",
                           "nonpromoternonpublicmember"):
            total += shp._num(facts[cref].get("ShareholdingAsAPercentageOfTotalNumberOfShares", "")) or 0.0
    factor = 100.0 if 0.5 <= total <= 1.5 else 1.0
    holder: dict[tuple[str, str], dict[str, str]] = {}
    for cref, key in typed.items():
        holder.setdefault(key, {}).update(facts.get(cref, {}))
    out = []
    for (axis, _key), d in sorted(holder.items()):
        # XBRL text arrives entity-encoded ("FASHION &amp; RETAIL"); decoded once here.
        name = html.unescape(d.get("NameOfTheShareholder") or "").strip()
        if not name:
            continue
        pct = shp._num(d.get("ShareholdingAsAPercentageOfTotalNumberOfShares", ""))
        shares = shp._num(d.get("NumberOfSharesOnFullyDilutedBasisIncludingWarrantsESOPAndConvertibleSecurities")
                          or d.get("NumberOfFullyPaidUpEquityShares") or d.get("NumberOfShares", ""))
        promoter = axis in shp.PROMOTER_AXES
        out.append({"isin": head.get("ISIN", ""), "symbol": (head.get("Symbol") or head.get("SymbolOfListedEntity") or "").strip().upper(),
                    "company": html.unescape(head.get("NameOfTheCompany", "")), "quarter_end": quarter,
                    "table": "PROMOTER" if promoter else "PUBLIC",
                    "group": "PROMOTER" if promoter else group_of(axis), "axis": axis, "name": name,
                    "is_label": is_label(name),
                    "pct": None if pct is None else round(pct * factor, 4), "shares": shares,
                    "source_file": Path(path).name})
    return out


def main() -> int:
    import duckdb
    files = sorted(glob.glob(shp.XBRL_GLOB, recursive=True))
    rows: list[dict] = []
    for f in files:
        try:
            rows.extend(parse_file(f))
        except (OSError, EOFError, UnicodeError) as e:
            print(f"  unreadable {Path(f).name}: {type(e).__name__}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE t (isin VARCHAR, symbol VARCHAR, company VARCHAR, quarter_end VARCHAR,"
                    " tbl VARCHAR, grp VARCHAR, axis VARCHAR, name VARCHAR, is_label BOOLEAN, pct DOUBLE, shares DOUBLE,"
                    " source_file VARCHAR)")
        con.executemany("INSERT INTO t VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(r["isin"], r["symbol"], r["company"], r["quarter_end"], r["table"], r["group"],
                          r["axis"], r["name"], r["is_label"], r["pct"], r["shares"], r["source_file"]) for r in rows])
        tmp = OUT.with_suffix(".parquet.partial")
        con.execute(f"COPY (SELECT * FROM t ORDER BY isin, quarter_end, tbl, pct DESC) TO '{tmp}' (FORMAT PARQUET)")
        tmp.replace(OUT)
        by = con.execute("SELECT tbl, grp, count(*) FILTER (WHERE NOT is_label) FROM t GROUP BY 1, 2 ORDER BY 3 DESC").fetchall()
        labels = con.execute("SELECT count(*) FROM t WHERE is_label").fetchone()[0]
    finally:
        con.close()
    print(f"  {len(rows):,} named holder rows from {len(files):,} filings -> {OUT.name} ({labels:,} are category labels, flagged)")
    for t, g, n in by:
        print(f"    {t:<9} {g:<11} {n:>9,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
