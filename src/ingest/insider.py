"""insider.py — archived insider XBRL becomes typed transactions.

ONE FILING, MANY TRANSACTIONS. The header fields (`Symbol`, `ISINCode`,
`DateOfFiling`) appear once under `contextRef="MainI"`; each disclosed
transaction repeats the detail fields under its own `Disclosure1`, `Disclosure2`
context. Twenty-two filings held thirty-nine transactions in the sample, so
parsing one row per file would silently drop 44% of them.

THE VOCABULARY IS NORMALISED AT INGEST, and MICC's fetcher explains why in its
own comment, recovered from the bundle 0042 salvaged:

    Map new-XBRL CategoryOfPerson vocab onto the legacy values the scored
    event layer filters on ... Normalizing at ingest keeps the frozen scoring
    layer untouched. Raw value preserved in category_raw.

The seed's 283,281 rows use `Promoters` / `Promoter Group` / `Buy` / `Sell`;
the XBRL says `Promoter` / `Acquisition` / `Disposal`. Decision
[0046](../../docs/decisions/0046-the-data-we-already-have-is-better-powered.md)
measured promoter sells at 1.25x short **on the seed's vocabulary**, so new rows
that do not map onto it would not join the population that measurement was about.
The raw value is kept alongside, because a normalisation nobody can audit is a
guess with a schema.

WHAT IS NOT DERIVED HERE. No price, no return, no eligibility. This produces
transactions; whether one is an event is the study's question, and putting that
judgement in the parser is how a filter becomes invisible.
"""

from __future__ import annotations

import glob
import gzip
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, COLLECTED  # noqa: E402
from src.governance import provenance as prov  # noqa: E402

XBRL_GLOB = str(ARCHIVE / "INSIDER" / "NSE" / "**" / "xbrl_*.xml.gz")
OUT = COLLECTED / "insider" / "insider_trading.parquet"
PRODUCED_BY = "src/ingest/insider.py"

_EL = re.compile(r'<in-bse-co:([A-Za-z0-9]+)\s+contextRef="([^"]+)"[^>]*>([^<]*)</in-bse-co:\1>')

#: XBRL vocabulary -> the seed's vocabulary. Unmapped values pass through
#: unchanged rather than becoming NULL: an unknown category is information, and
#: category_raw always holds the original.
_CATEGORY = {
    "promoter": "Promoters",
    "promoters": "Promoters",
    "promoter group": "Promoter Group",
    "promoters group": "Promoter Group",
    "director": "Director",
    "directors": "Director",
    "kmp": "Key Managerial Personnel",
    "key managerial personnel": "Key Managerial Personnel",
    # "Promoter and Director" is one person in both roles. MICC's fetcher mapped
    # it to Promoters with the comment "promoter is the stronger class", and the
    # seed's 283,281 rows were normalised that way — so 0046's promoter power
    # figures are ON that convention. Diverging here would silently exclude
    # these from the population that measurement was about.
    "promoter and director": "Promoters",
    "promoter & director": "Promoters",
    "immediate relative": "Immediate Relative",
    "designated person": "Employees/Designated Employees",
    "employee": "Employees/Designated Employees",
}
_TXN = {
    "acquisition": "Buy", "acquired": "Buy", "buy": "Buy", "purchase": "Buy",
    "disposal": "Sell", "disposed": "Sell", "sell": "Sell", "sale": "Sell",
}


@dataclass(frozen=True, slots=True)
class Txn:
    filing_date: str
    symbol: str
    isin: str
    company: str
    person: str
    category: str
    category_raw: str
    transaction_type: str
    transaction_type_raw: str
    quantity: float | None
    value: float | None
    post_holding: float | None
    pct_post: float | None
    mode: str
    regulation: str
    from_date: str
    to_date: str
    source_file: str


def _num(s: str) -> float | None:
    try:
        return float(str(s).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_file(path: str) -> list[Txn]:
    text = gzip.open(path, "rb").read().decode("utf-8", "replace")
    by_ctx: dict[str, dict[str, str]] = {}
    for name, ctx, val in _EL.findall(text):
        by_ctx.setdefault(ctx, {})[name] = val.strip()

    head: dict[str, str] = {}
    for ctx, d in by_ctx.items():
        if "Symbol" in d or "ISINCode" in d:
            head.update(d)

    out: list[Txn] = []
    for ctx, d in by_ctx.items():
        if "SecuritiesAcquiredOrDisposedTransactionType" not in d:
            continue
        cat_raw = d.get("CategoryOfPerson", "")
        txn_raw = d.get("SecuritiesAcquiredOrDisposedTransactionType", "")
        out.append(Txn(
            filing_date=head.get("DateOfFiling", ""),
            symbol=(head.get("Symbol") or "").strip().upper(),
            isin=head.get("ISINCode", ""),
            company=head.get("NameOfTheCompany", ""),
            person=d.get("NameOfThePerson", ""),
            category=_CATEGORY.get(cat_raw.strip().lower(), cat_raw),
            category_raw=cat_raw,
            transaction_type=_TXN.get(txn_raw.strip().lower(), txn_raw),
            transaction_type_raw=txn_raw,
            quantity=_num(d.get("SecuritiesAcquiredOrDisposedNumberOfSecurity", "")),
            value=_num(d.get("SecuritiesAcquiredOrDisposedValueOfSecurity", "")),
            post_holding=_num(d.get("SecuritiesHeldPostAcquistionOrDisposalNumberOfSecurity", "")),
            pct_post=_num(d.get("SecuritiesHeldPostAcquistionOrDisposalPercentageOfShareholding", "")),
            mode=d.get("ModeOfAcquisitionOrDisposal", ""),
            regulation=head.get("DisclosureUnderRegulation", ""),
            from_date=d.get("DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate", ""),
            to_date=d.get("DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate", ""),
            source_file=Path(path).name,
        ))
    return out


def parse() -> list[Txn]:
    out: list[Txn] = []
    for f in sorted(glob.glob(XBRL_GLOB, recursive=True)):
        out.extend(parse_file(f))
    return out


def write(txns: list[Txn]) -> Path:
    import duckdb

    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("""CREATE TABLE t (
            filing_date VARCHAR, symbol VARCHAR, isin VARCHAR, company VARCHAR,
            person VARCHAR, category VARCHAR, category_raw VARCHAR,
            transaction_type VARCHAR, transaction_type_raw VARCHAR,
            quantity DOUBLE, value DOUBLE, post_holding DOUBLE, pct_post DOUBLE,
            mode VARCHAR, regulation VARCHAR, from_date VARCHAR, to_date VARCHAR,
            source_file VARCHAR)""")
        con.executemany(
            "INSERT INTO t VALUES (" + ",".join("?" * 18) + ")",
            [(t.filing_date, t.symbol, t.isin, t.company, t.person, t.category,
              t.category_raw, t.transaction_type, t.transaction_type_raw,
              t.quantity, t.value, t.post_holding, t.pct_post, t.mode,
              t.regulation, t.from_date, t.to_date, t.source_file) for t in txns])
        tmp = OUT.with_suffix(".parquet.partial")
        con.execute(f"COPY (SELECT * FROM t ORDER BY filing_date, symbol) TO '{tmp}' (FORMAT PARQUET)")
        tmp.replace(OUT)
    finally:
        con.close()
    return OUT


def main() -> int:
    txns = parse()
    if not txns:
        print("INSIDER: no archived XBRL to parse")
        return 0
    write(txns)
    digest = prov.register_dataset(
        OUT.parent, artefact_type="SOURCE", logical_name="collected:insider",
        produced_by=PRODUCED_BY, pattern="**/*.parquet",
        params={"source": "NSE /api/corporates-pit-gg + XBRL detail"})
    files = len({t.source_file for t in txns})
    print(f"  {len(txns):,} transaction(s) from {files:,} filing(s)")
    by = {}
    for t in txns:
        by[(t.category, t.transaction_type)] = by.get((t.category, t.transaction_type), 0) + 1
    for (c, tt), n in sorted(by.items(), key=lambda x: -x[1])[:8]:
        print(f"    {c:<34}{tt:<8}{n:>6}")
    unmapped = {t.category_raw for t in txns if t.category == t.category_raw}
    if unmapped:
        print(f"\n  categories passed through unmapped (raw kept): {sorted(unmapped)[:6]}")
    print(f"\nINSIDER: {OUT}")
    print(f"  registered collected:insider as {digest[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
