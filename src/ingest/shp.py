"""shp.py — archived shareholding-pattern bytes become one holdings table.

TWO ARCHIVES, ONE JOIN KEY. The master JSON (per symbol) lists every filing
with its quarter-end (`date`) and when it reached the public (`broadcastDate`);
the XBRL (per filing) carries the category breakdown — percent, holder count,
share count per shareholder class — but not `broadcastDate`. Checked directly
(2026-09-18, ANANDRATHI 2026-06-04 filing): the master's `date` and the XBRL's
own `xbrli:period/endDate` are the SAME string. So `(symbol, quarter_end)`
joins the two without guessing, and every holdings row carries the timestamp
`exp_004`'s point-in-time rule needs — entry is the session after
`broadcast_date`, never the quarter-end.

CATEGORIES ARE KEPT LONG, NOT AGGREGATED. Each XBRL context carries one
`in-bse-shp:CategoryOfShareholdersAxis` member in its `xbrli:scenario`; every
fact referencing that context belongs to that category. This produces one row
per (filing, category) — FPI Category I and II stay separate, promoter stays
separate from public — because collapsing them here is a research decision
(which categories sum to "FPI") that belongs in a registration, not a parser.
`category_raw` is the XBRL member name; `category` is a short label for the
handful the exp_004 draft names, everything else passes through unchanged —
the same shape as `src/ingest/insider.py`'s `_CATEGORY` map, for the same
reason: an unrecognised category is information, not noise to be dropped.

WHAT IS NOT DERIVED HERE. No return, no rank, no decile. This produces one row
per (ISIN, quarter, category); what to compute from it is exp_004's question.
"""

from __future__ import annotations

import glob
import gzip
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, COLLECTED  # noqa: E402
from src.governance import provenance as prov  # noqa: E402

MASTER_GLOB = str(ARCHIVE / "SHP" / "NSE" / "**" / "*.json.gz")
XBRL_GLOB = str(ARCHIVE / "SHP_XBRL" / "NSE" / "**" / "*.xml.gz")
OUT = COLLECTED / "shp" / "shp_holdings.parquet"
PRODUCED_BY = "src/ingest/shp.py"

#: `in-bse-shp:CategoryOfShareholdersAxis` member -> a short label, for the
#: handful of categories exp_004 names. Everything else keeps its raw member
#: name as `category` too — unmapped is information, not NULL.
_CATEGORY = {
    "shareholdingofpromoterandpromotergroupmember": "Promoter",
    "mutualfundsorutimember": "MutualFund",
    # ALL foreign institutions — FPI Cat I + II AND FDI, FVCI, sovereign wealth
    # funds, other foreign. Labelled "FPI_Total" on the first run; wrong. Cat I +
    # Cat II differ from this total in 185 of 991 filings, which is the proof.
    "institutionsforeignmember": "ForeignInst_Total",
    "institutionsforeignportfolioinvestorcategoryonemember": "FPI_Cat1",
    "institutionsforeignportfolioinvestorcategorytwomember": "FPI_Cat2",
    # NSE's 2022-2024 taxonomy spells it "Catergory". Corrected in 2025. Same
    # line, misspelled member — without both spellings FPI has a two-year hole
    # (0 rows in 2023 and 2024 on the second parse).
    "institutionsforeignportfolioinvestorcatergoryonemember": "FPI_Cat1",
    "institutionsforeignportfolioinvestorcatergorytwomember": "FPI_Cat2",
    # The 2020-2022 taxonomy: FPI undivided. Measured across 1,047 old files:
    # this member carries the values (523 non-zero, max 52%); the similarly
    # named ForeignPortfolioInvestorMember and ForeignInstitutionsMember are
    # ALWAYS zero there — dead lines, deliberately unmapped. Cat I/II never
    # co-occur with this in one file, so the FPI signal sums all three.
    "institutionsforeignportfolioinvestormember": "FPI_Undivided",
    # The old taxonomy's parent of every institution, domestic and foreign.
    "institutionsmember": "Institutions_Total_OldTaxonomy",
    "institutionsdomesticmember": "DomesticInstitution",
    "banksmember": "Bank",
    "insurancecompaniesmember": "Insurance",
    "providentfundsorpensionfundsmember": "PensionFund",
    "alternativeinvestmentfundsmember": "AIF",
    "publicshareholdingmember": "PublicTotal",
    "individualsorhinduundividedfamilymember": "Individual",
    "noninstitutionsmember": "NonInstitutionTotal",
}

#: The context BLOCK only. Its date and category are searched for inside it
#: separately: an optional group placed after a lazy quantifier is never
#: reached — the engine succeeds with the group empty and stops — so a single
#: regex reported 84 contexts and 0 categories on the first real file.
_CONTEXT_BLOCK = re.compile(r'<xbrli:context id="([^"]+)"[^>]*>(.*?)</xbrli:context>', re.S)
_CONTEXT_DATE = re.compile(r'<xbrli:(?:instant|endDate)>(\d{4}-\d{2}-\d{2})</xbrli:(?:instant|endDate)>')
_CONTEXT_CATEGORY = re.compile(
    r'<xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">'
    r'in-bse-shp:([A-Za-z0-9]+)</xbrldi:explicitMember>')

_FACT = re.compile(r'<in-bse-shp:([A-Za-z0-9]+)\s+contextRef="([^"]+)"[^>]*>([^<]*)</in-bse-shp:\1>')


@dataclass(frozen=True, slots=True)
class Filing:
    symbol: str
    isin: str
    record_id: str
    quarter_end: str
    broadcast_date: str
    revised: bool


@dataclass(frozen=True, slots=True)
class Holding:
    isin: str
    symbol: str
    company: str
    quarter_end: str
    broadcast_date: str
    #: "master" (the filing list's broadcastDate), "xbrl_url" (the upload
    #: timestamp NSE embeds in the XBRL filename, used when no master row
    #: joins — 68 companies whose ISIN changed in a scheme), or "" (neither).
    broadcast_source: str
    #: Calendar quarter-end (03-31/06-30/09-30/12-31) or an off-cycle filing —
    #: listing day, rights issue, demerger date. 6.6% of filings. The study
    #: keeps both (owner decision 2026-09-18) and a change-since-last-filing
    #: therefore spans an irregular interval; this flag is how it knows.
    is_calendar_quarter: bool
    #: Promoter + Public + NonPromoterNonPublic for the FILING, in percent.
    #: 100 by definition; 97 with an employee-trust bucket is fine; 119.6 is a
    #: bad filing. Carried so the study can filter, not silently dropped here.
    identity_total: float | None
    category_raw: str
    category: str
    pct_shares: float | None
    pct_scale_raw: str
    num_shareholders: float | None
    num_shares: float | None
    revised: bool
    source_file: str


def _num(s: str) -> float | None:
    try:
        return float(str(s).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def _date(raw: str) -> str:
    """'30-JUN-2026' or '30-Jun-2026 19:32:59' -> ISO date. Empty on failure —
    never a guess, because a wrong date silently mis-joins two filings."""
    raw = str(raw or "").strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def parse_master_file(path: str) -> list[Filing]:
    with gzip.open(path, "rb") as fh:
        rows = json.load(fh)
    rows = rows.get("data", rows) if isinstance(rows, dict) else rows
    out = []
    for r in rows if isinstance(rows, list) else []:
        q = _date(r.get("date", ""))
        if not q or not r.get("recordId"):
            continue
        out.append(Filing(
            symbol=str(r.get("symbol", "")).strip().upper(),
            isin=str(r.get("isin", "")).strip().upper(),
            record_id=str(r.get("recordId")),
            quarter_end=q,
            broadcast_date=_date(r.get("broadcastDate", "")),
            # The master's own flag: `revisedStatus` is the string "Revised"
            # or the placeholder "-" (never empty), so truthiness reads every
            # filing as revised — 4,049 of 4,140 on the second run. The first
            # parser guessed an XBRL element name and found 0. Both wrong.
            revised=str(r.get("revisedStatus") or "").strip().lower() == "revised",
        ))
    return out


def parse_xbrl_file(path: str) -> list[Holding]:
    with gzip.open(path, "rb") as fh:
        text = fh.read().decode("utf-8", "replace")

    # context id -> (period date, category member or None)
    ctx: dict[str, tuple[str, str | None]] = {}
    for m in _CONTEXT_BLOCK.finditer(text):
        cid, block = m.group(1), m.group(2)
        d = _CONTEXT_DATE.search(block)
        c = _CONTEXT_CATEGORY.search(block)
        if d:
            ctx[cid] = (d.group(1), c.group(1) if c else None)

    facts: dict[str, dict[str, str]] = {}
    for m in _FACT.finditer(text):
        name, cref, val = m.group(1), m.group(2), m.group(3)
        facts.setdefault(cref, {})[name] = val.strip()

    # The header is WHICHEVER context carries the ISIN — `OneD` in the 2018-2024
    # schema, `MainD` from V1.1 (2025-12). Guessing "the first context without
    # a category" picked a named-holder detail block instead and left 147,518
    # rows with an empty symbol on the first real run. The element names are
    # the stable part; the context ids are not.
    head: dict[str, str] = {}
    for d in facts.values():
        if "ISIN" in d:
            head.update(d)
            break
    isin = head.get("ISIN", "")
    symbol = (head.get("Symbol") or head.get("SymbolOfListedEntity") or "").strip().upper()
    company = head.get("NameOfTheCompany", "")
    # ONE SCALE. The 2018-2024 schema reports the holding as a PERCENT (41.37);
    # V1.1+ reports a FRACTION (0.4137) — `unitRef="pure"`. Mixed across the
    # panel, every quarter-over-quarter change for a company whose filings
    # straddle the schema change would be off by a factor of 100. Detected per
    # FILE from the promoter + public total, which is 100 or 1 by definition;
    # the raw scale is kept on every row so the normalisation can be audited.
    cat_rows = [(cref, period, cat) for cref, (period, cat) in ctx.items() if cat is not None and cref in facts]
    total = 0.0
    for cref, _, cat in cat_rows:
        if cat.lower() in ("shareholdingofpromoterandpromotergroupmember", "publicshareholdingmember",
                           "nonpromoternonpublicmember"):
            total += _num(facts[cref].get("ShareholdingAsAPercentageOfTotalNumberOfShares", "")) or 0.0
    if 0.5 <= total <= 1.5:
        scale, factor = "fraction", 100.0
    elif 50.0 <= total <= 150.0:
        scale, factor = "percent", 1.0
    else:
        scale, factor = "unknown", 1.0  # left as-is; the row says so
    identity_total = total * factor if scale != "unknown" else None

    out: list[Holding] = []
    for cref, period, cat_raw in cat_rows:
        d = facts[cref]
        raw_pct = _num(d.get("ShareholdingAsAPercentageOfTotalNumberOfShares", ""))
        out.append(Holding(
            isin=isin, symbol=symbol, company=company,
            quarter_end=period, broadcast_date="", broadcast_source="",  # joined below
            is_calendar_quarter=period[5:] in ("03-31", "06-30", "09-30", "12-31"),
            identity_total=identity_total,
            category_raw=cat_raw, category=_CATEGORY.get(cat_raw.lower(), cat_raw),
            pct_shares=None if raw_pct is None else raw_pct * factor,
            pct_scale_raw=scale,
            num_shareholders=_num(d.get("NumberOfShareholders", "")),
            num_shares=_num(d.get("NumberOfSharesOnFullyDilutedBasisIncludingWarrantsESOPAndConvertibleSecurities")
                            or d.get("NumberOfShares", "")),  # the old taxonomy's name
            revised=False,  # from the master, joined below
            source_file=Path(path).name,
        ))
    return out


def parse() -> list[Holding]:
    """Every XBRL, joined to its filing's broadcast date by (symbol, quarter_end).

    A holding with no matching filing (the master for that symbol was never
    archived, or a symbol was renamed between the two archives) keeps an empty
    `broadcast_date` rather than being dropped — the category data is still
    real; only the point-in-time entry rule cannot use that row.
    """
    # KEYED ON ISIN, NOT SYMBOL. The XBRL's `Symbol` is the symbol AT FILING
    # TIME; the master was fetched under today's. ANGELBRKG became ANGELONE,
    # ADANITRANS became ADANIENSOL, IIFLWAM became 360ONE — 80 symbols, 11,390
    # rows, silently unjoined on the first run. Decision 0069 found the same
    # error keying the EXPLORE partition on the symbol; the ISIN survives a
    # rename, the symbol does not. Symbol is the fallback only when the master
    # row has no ISIN.
    by_isin: dict[tuple[str, str], Filing] = {}
    by_symbol: dict[tuple[str, str], Filing] = {}
    for f in sorted(glob.glob(MASTER_GLOB, recursive=True)):
        for fl in parse_master_file(f):
            if fl.isin:
                by_isin[(fl.isin, fl.quarter_end)] = fl
            by_symbol[(fl.symbol, fl.quarter_end)] = fl
    url_stamp = _xbrl_upload_dates()

    out: list[Holding] = []
    for f in sorted(glob.glob(XBRL_GLOB, recursive=True)):
        for h in parse_xbrl_file(f):
            fl = by_isin.get((h.isin, h.quarter_end)) or by_symbol.get((h.symbol, h.quarter_end))
            if fl and fl.broadcast_date:
                bd, src, rev = fl.broadcast_date, "master", fl.revised
            else:
                bd, src, rev = url_stamp.get(h.source_file, ""), "xbrl_url" if h.source_file in url_stamp else "", False
            out.append(Holding(h.isin, h.symbol, h.company, h.quarter_end, bd, src,
                               h.is_calendar_quarter, h.identity_total,
                               h.category_raw, h.category, h.pct_shares, h.pct_scale_raw,
                               h.num_shareholders, h.num_shares, rev, h.source_file))
    return out


def _xbrl_upload_dates() -> dict[str, str]:
    """archived filename -> upload date, from the timestamp NSE embeds in the
    XBRL URL (`SHP_1693635_15072026073252_WEB.xml` = 2026-07-15 07:32:52).

    THE FALLBACK for a filing with no master row — 68 companies whose ISIN
    changed in a scheme of arrangement, 2.2% of rows on the first run. The URL
    is in the manifest, keyed by the archived path. It is the time the file
    reached NSE's static host, which is at or before `broadcastDate`, so an
    entry rule using it is conservative, never early.
    """
    man = ARCHIVE / "manifest.jsonl"
    out: dict[str, str] = {}
    if not man.exists():
        return out
    for line in man.read_text(errors="ignore").splitlines():
        if '"nse_shp_xbrl"' not in line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        m = re.search(r"_(\d{2})(\d{2})(\d{4})\d{6}_WEB\.xml", r.get("url", ""))
        if m and r.get("path"):
            out[Path(r["path"]).name] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return out


def write(rows: list[Holding]) -> Path:
    import duckdb

    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("""CREATE TABLE t (
            isin VARCHAR, symbol VARCHAR, company VARCHAR, quarter_end VARCHAR,
            broadcast_date VARCHAR, broadcast_source VARCHAR, is_calendar_quarter BOOLEAN,
            identity_total DOUBLE, category_raw VARCHAR, category VARCHAR,
            pct_shares DOUBLE, pct_scale_raw VARCHAR, num_shareholders DOUBLE,
            num_shares DOUBLE, revised BOOLEAN, source_file VARCHAR)""")
        con.executemany(
            "INSERT INTO t VALUES (" + ",".join("?" * 16) + ")",
            [(r.isin, r.symbol, r.company, r.quarter_end, r.broadcast_date, r.broadcast_source,
              r.is_calendar_quarter, r.identity_total, r.category_raw, r.category,
              r.pct_shares, r.pct_scale_raw, r.num_shareholders, r.num_shares,
              r.revised, r.source_file) for r in rows])
        tmp = OUT.with_suffix(".parquet.partial")
        con.execute(f"COPY (SELECT * FROM t ORDER BY symbol, quarter_end, category) "
                    f"TO '{tmp}' (FORMAT PARQUET)")
        tmp.replace(OUT)
    finally:
        con.close()
    return OUT


def main() -> int:
    rows = parse()
    if not rows:
        print("SHP: no archived XBRL to parse")
        return 0
    write(rows)
    prov.register_dataset(
        OUT.parent, artefact_type="SOURCE", logical_name="collected:shp",
        produced_by=PRODUCED_BY, pattern="**/*.parquet",
        params={"source": "NSE corporate-share-holdings-master + XBRL detail"})
    files = len({r.source_file for r in rows})
    symbols = len({r.symbol for r in rows if r.symbol})
    quarters = len({r.quarter_end for r in rows})
    srcs: dict[str, int] = {}
    for r in rows:
        srcs[r.broadcast_source or "none"] = srcs.get(r.broadcast_source or "none", 0) + 1
    cal = len({r.quarter_end for r in rows if r.is_calendar_quarter})
    print(f"  {len(rows):,} row(s) from {files:,} filing(s), {symbols:,} symbol(s), "
          f"{cal} calendar quarter(s) + {quarters - cal} off-cycle date(s)")
    print(f"  broadcast_date from: {srcs}")
    bad = len({r.source_file for r in rows if r.identity_total is not None and abs(r.identity_total - 100) > 1})
    print(f"  {bad} filing(s) whose promoter+public+other != 100 by more than 1pt (identity_total says which)")
    print(f"  {len({r.source_file for r in rows if r.revised})} revised filing(s), per the master")
    scales = {}
    for r in rows:
        scales[r.pct_scale_raw] = scales.get(r.pct_scale_raw, 0) + 1
    print(f"  pct scale as filed: {scales}  (all normalised to PERCENT)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
