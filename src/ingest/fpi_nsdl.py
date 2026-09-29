"""fpi_nsdl.py — archived NSDL "Daily Trends in FPI Investments" pages become two tables.

INPUT: the raw pages `src/archive/fpi_nsdl.py` archived, one per month (the
current month's page is partial and re-fetched daily; the newest page for a
month wins).

OUTPUT, under collected/fpi_nsdl/:

  fpi_investment.parquet  one row per (reporting_date, category, route):
      category  Equity, Debt, Debt-General Limit, Debt-VRR, Debt-FAR, Hybrid,
                Mutual Funds and its scheme lines, AIFs, and Total
      route     "Stock Exchange", "Primary market & others", "Sub-total", or
                "" where the layout has no route (1998-2009, scheme lines, Total)
      gross_purchases_cr, gross_sales_cr, net_cr (Rs crore), net_usd_mn,
      usd_inr (the day's conversion rate, from the day's first row)
      is_daily_flow  False only for 1998-12-31, the opening balance (every
                FII flow since 1992, booked on the day the series starts)

  fpi_derivatives.parquet one row per (reporting_date, product):
      buy_contracts, buy_cr, sell_contracts, sell_cr, oi_contracts, oi_cr

THREE LAYOUTS, READ BY SHAPE, NOT BY YEAR. The header row says whether an
"Investment Route" column exists; each data row is then one of:

  a DATE row      the day's first line: date, category, [route], numbers, rate
  a ROUTE row     "Stock Exchange" / "Primary market & others" / "Sub-total"
                  continuing the current category
  a TOTAL row     the day's total across categories
  a CATEGORY row  a new category for the current day, with or without a route

"Total for <month>", "Total for <year>" and "Grand Total Till <date>" rows are
derived and dropped — AND every continuation row after them until the next
dated row, which belongs to the same derived block. So are the derivatives
table's upper-case period-summary rows ("INDEX OPTIONS").

NUMBERS AS NSDL WRITES THEM: "(6139.56)" is -6139.56, commas are thousands
separators, "-" or blank is missing. Nothing is derived here.

POINT IN TIME: see src/archive/fpi_nsdl.py. `reporting_date` is the day the
custodians reported; a flow was not public before it.
"""

from __future__ import annotations

import glob
import gzip
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, COLLECTED  # noqa: E402
from src.governance import provenance as prov  # noqa: E402

GLOB = str(ARCHIVE / "FPI_DAILY" / "NSDL" / "**" / "*.html.gz")
OUT_DIR = COLLECTED / "fpi_nsdl"
PRODUCED_BY = "src/ingest/fpi_nsdl.py"

ROUTES = {"Stock Exchange", "Primary market & others", "Sub-total"}
_DATE = re.compile(r"^\d{2}-[A-Za-z]{3}-\d{4}$")
_FILE_DATE = re.compile(r"_(\d{8})_[0-9a-f]{8}\.html\.gz$")


#: NSDL's first "reporting day" is not a day. The 31-Dec-1998 page's only
#: rows equal its own "Grand Total Till December 31, 1998": every FII flow
#: since 1992, booked on the date the series starts. Kept, and flagged, so
#: a daily analysis can drop it and a stock-of-holdings one can use it.
OPENING_BALANCE_DATE = "1998-12-31"


@dataclass(frozen=True, slots=True)
class Flow:
    reporting_date: str
    category: str
    route: str
    gross_purchases_cr: float | None
    gross_sales_cr: float | None
    net_cr: float | None
    net_usd_mn: float | None
    usd_inr: float | None
    source_file: str
    #: False for the opening balance (see OPENING_BALANCE_DATE).
    is_daily_flow: bool = True
    #: True where the page printed a repeated date and the row was moved to
    #: the next day — see _resolve_date.
    date_corrected: bool = False


@dataclass(frozen=True, slots=True)
class Deriv:
    reporting_date: str
    product: str
    buy_contracts: float | None
    buy_cr: float | None
    sell_contracts: float | None
    sell_cr: float | None
    oi_contracts: float | None
    oi_cr: float | None
    source_file: str
    date_corrected: bool = False


def num(s: str) -> float | None:
    """NSDL's number: '(6139.56)' -> -6139.56, '1,234.5' -> 1234.5, '-' -> None."""
    s = (s or "").strip().replace(",", "")
    if s in ("", "-", "NA"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def fx(s: str) -> float | None:
    """'Rs.95.4509' / 'Rs. 42.49' -> 95.4509 / 42.49."""
    m = re.search(r"\d+(?:\.\d+)?", (s or "").replace(",", ""))
    return float(m.group()) if m else None


def _iso(d: str) -> str:
    return datetime.strptime(d, "%d-%b-%Y").date().isoformat()


def rows_of(html: str) -> list[list[str]]:
    """Every non-empty table row of the report, as a list of cell texts."""
    i = html.find("dvArchiveData")
    html = html[i:] if i >= 0 else html
    out = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).replace("&nbsp;", " ").strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S | re.I)]
        if any(cells):
            out.append(cells)
    return out


_UPTO = re.compile(r"up\s*to\s+(\d{2}-[A-Za-z]{3}-\d{4})", re.I)


def _resolve_date(iso: str, seen: set[str], on_page: set[str], upto: str | None) -> tuple[str | None, bool]:
    """(date to file the day under, corrected?) — or (None, False) to drop it.

    A DATE THE PAGE PRINTS TWICE. February 2000's page has two different days
    both dated 28-Feb-2000 and none dated 29-Feb, in a leap year, on a page
    "up to 29-Feb-2000"; its own month total (Rs 2,784.5 crore) includes both.
    So the second is a real day with a misprinted date. It is moved to the
    next calendar day ONLY when that day is absent from the page and not past
    the page's own end date. Anything else is dropped, never guessed.
    """
    if iso not in seen:
        return iso, False
    nxt = (datetime.fromisoformat(iso) + timedelta(days=1)).date().isoformat()
    if nxt not in on_page and (upto is None or nxt <= upto) and nxt[:7] == iso[:7]:
        return nxt, True
    return None, False


def parse_page(html: str, source_file: str = "") -> tuple[list[Flow], list[Deriv]]:
    flows: list[Flow] = []
    derivs: list[Deriv] = []
    section = None          # "inv" | "deriv"
    has_route = False
    day = cat = None
    corrected = False
    rate: float | None = None
    rows = rows_of(html)
    on_page = {_iso(r[0]) for r in rows if r and _DATE.match(r[0])}
    m = _UPTO.search(" ".join(r[0] for r in rows[:3] if r))
    upto = _iso(m.group(1)) if m else None
    seen: dict[str, set[str]] = {"inv": set(), "deriv": set()}

    def flow(category: str, route: str, nums: list[str]) -> None:
        g, s, n, u = (num(x) for x in (nums + ["", "", "", ""])[:4])
        flows.append(Flow(day, category, route, g, s, n, u, rate, source_file,
                          day != OPENING_BALANCE_DATE, corrected))

    def open_day(printed: str, sec: str) -> str | None:
        nonlocal corrected
        d, corrected = _resolve_date(_iso(printed), seen[sec], on_page, upto)
        if d:
            seen[sec].add(d)
        return d

    for r in rows:
        head = r[0]
        if head == "Reporting Date":
            if any("Derivative" in c for c in r):
                section, day = "deriv", None
            else:
                section, day, has_route = "inv", None, any("Investment Route" in c for c in r)
            continue
        if head.startswith("Total for") or head.startswith("Grand Total"):
            # A DERIVED BLOCK STARTS HERE and its continuation rows ("Debt",
            # "Sub-total", ...) carry the MONTH's, YEAR's or all-time totals.
            # Until 2026-09-29 those rows were attached to the month's last
            # reporting day, overwriting its real figures. Nothing counts
            # again until the next dated row opens a real day.
            day = None
            continue
        if head == "No. of Contracts" or len(r) < 5:
            continue
        if section == "inv":
            if _DATE.match(head):
                day, cat = open_day(head, "inv"), r[1]
                if day is None:
                    continue
                rate = fx(r[-1])
                if has_route:
                    flow(cat, r[2], r[3:7])
                else:
                    flow(cat, "", r[2:6])
            elif day is None:
                continue
            elif head in ROUTES:
                flow(cat, head, r[1:5])
            elif head == "Total":
                flow("Total", "", r[1:5])
            elif has_route and len(r) >= 6 and r[1] in ROUTES:
                cat = head
                flow(cat, r[1], r[2:6])
            else:
                # A category with no route: the 1998-2009 layout's second line,
                # or a Mutual Fund scheme line under the new layout.
                cat = head
                flow(cat, "", r[1:5])
        elif section == "deriv":
            if _DATE.match(head):
                day, prod, nums = open_day(head, "deriv"), r[1], r[2:8]
                if day is None:
                    continue
            elif day is None or head.isupper():
                continue
            else:
                prod, nums = head, r[1:7]
            v = [num(x) for x in (nums + [""] * 6)[:6]]
            derivs.append(Deriv(day, prod, *v, source_file, corrected))
    return flows, derivs


def newest_per_month(files: list[str]) -> list[str]:
    """One file per month: the one asked for the latest date, then the latest name."""
    best: dict[str, tuple[str, str]] = {}
    for f in files:
        m = _FILE_DATE.search(f)
        if not m:
            continue
        ymd = m.group(1)
        key = ymd[:6]
        cand = (ymd, Path(f).name)
        if key not in best or cand > best[key][0:2]:
            best[key] = (*cand, f)  # type: ignore[assignment]
    return [v[2] for v in sorted(best.values())]  # type: ignore[index]


def parse() -> tuple[list[Flow], list[Deriv]]:
    flows: list[Flow] = []
    derivs: list[Deriv] = []
    for f in newest_per_month(glob.glob(GLOB, recursive=True)):
        with gzip.open(f, "rb") as fh:
            html = fh.read().decode("utf-8", "replace")
        a, b = parse_page(html, Path(f).name)
        flows += a
        derivs += b
    return flows, derivs


def write(flows: list[Flow], derivs: list[Deriv]) -> tuple[Path, Path]:
    import duckdb

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("""CREATE TABLE f (reporting_date DATE, category VARCHAR, route VARCHAR,
            gross_purchases_cr DOUBLE, gross_sales_cr DOUBLE, net_cr DOUBLE, net_usd_mn DOUBLE,
            usd_inr DOUBLE, source_file VARCHAR, is_daily_flow BOOLEAN, date_corrected BOOLEAN)""")
        con.executemany("INSERT INTO f VALUES (?,?,?,?,?,?,?,?,?,?,?)", [tuple(vars_(x)) for x in flows])
        con.execute("""CREATE TABLE d (reporting_date DATE, product VARCHAR, buy_contracts DOUBLE,
            buy_cr DOUBLE, sell_contracts DOUBLE, sell_cr DOUBLE, oi_contracts DOUBLE, oi_cr DOUBLE,
            source_file VARCHAR, date_corrected BOOLEAN)""")
        con.executemany("INSERT INTO d VALUES (?,?,?,?,?,?,?,?,?,?)", [tuple(vars_(x)) for x in derivs])
        fo, do = OUT_DIR / "fpi_investment.parquet", OUT_DIR / "fpi_derivatives.parquet"
        for tbl, key, out in (("f", "reporting_date, category, route", fo), ("d", "reporting_date, product", do)):
            tmp = out.with_suffix(".parquet.partial")
            con.execute(f"""COPY (SELECT * EXCLUDE rn FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY {key} ORDER BY source_file DESC) rn FROM {tbl})
                WHERE rn = 1 ORDER BY {key}) TO '{tmp}' (FORMAT PARQUET)""")
            tmp.replace(out)
    finally:
        con.close()
    return fo, do


def vars_(x) -> list:
    return [getattr(x, k) for k in x.__slots__]


def main() -> int:
    flows, derivs = parse()
    if not flows:
        print("NSDL FPI: no archived pages to parse")
        return 0
    fo, do = write(flows, derivs)
    prov.register_dataset(OUT_DIR, artefact_type="SOURCE", logical_name="collected:fpi_nsdl",
                          produced_by=PRODUCED_BY, pattern="*.parquet",
                          params={"source": "NSDL FPI Monitor, Archive.aspx (Daily Trends in FPI Investments)"})
    days = sorted({f.reporting_date for f in flows})
    print(f"  investment: {len(flows):,} row(s), {len(days):,} reporting day(s) {days[0]} -> {days[-1]}")
    print(f"  derivatives: {len(derivs):,} row(s)")
    moved = sorted({f.reporting_date for f in flows if f.date_corrected})
    if moved:
        print(f"  {len(moved)} day(s) printed with a repeated date, filed under the missing next day: {moved[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
