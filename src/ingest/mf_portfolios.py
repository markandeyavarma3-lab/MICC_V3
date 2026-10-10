"""mf_portfolios.py — every mutual-fund scheme's month-end portfolio, one row
per (scheme, month, security).

WHY (2026-10-10). Part D of the site plan (docs/plan/WEBSITE_PLAN.md). The
shareholding filings name a fund house only when one scheme holds more than
1% of a company, and only quarterly. SEBI requires every scheme to publish
its full portfolio within ten days of each month-end; that is the complete
"which funds hold this stock, and how much" map, monthly.

ONE PARSER FOR EVERY FUND HOUSE. The archive (src/archive/mf_portfolios.py)
keeps each file as served: .xls, .xlsx, or a .zip of either. Measured that
day on SBI, ICICI, HDFC, Nippon, ABSL, Tata, Mirae, Groww, JM and Motilal,
every sheet follows the SEBI layout: a few title rows (scheme name, "as on"
date), then a header row with an ISIN column, an instrument name, an
industry or rating, a quantity, a market value and a percentage of net
assets. What differs is the column order, the title wording, the value unit
(Rs lakh nearly everywhere) and whether the percentage is 3.22 or 0.0322.
So the parser finds the header row by its ISIN cell, maps the columns by
their words, and normalises the unit and the scale per sheet.

A row is kept only when its ISIN cell is a valid Indian ISIN: totals, cash,
TREPS and derivatives without an ISIN fall away, and nothing is inferred.

    RESEARCH_ENV=prod .venv/bin/python -m src.ingest.mf_portfolios
"""

from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import COLLECTED  # noqa: E402

OUT = COLLECTED / "mf" / "mf_portfolios.parquet"

ISIN = re.compile(r"^IN[A-Z0-9]{10}$")
_HEADER_ISIN = re.compile(r"^\s*isin\b", re.I)
# Sheets that are not a portfolio. Only the sheet NAMED 'Index' is the table
# of contents: an index fund's sheet ('SBI BSE PSU Bank Index Fund') is a portfolio.
_SKIP_SHEET = re.compile(r"^\s*index\s*$|deriv|risk-?o-?meter|dividend|idcw|replication|disclaimer|^\s*notes?\s*$|summary",
                         re.I)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_PATTERNS = (
    re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s\-./_]+([A-Za-z]{3,9})[\s\-.,/_]+(\d{4}|\d{2})(?!\d)"),   # 30-Sep-2026, 30th September 2026, 30-Sep-26
    re.compile(r"([A-Za-z]{3,9})[\s\-._]+(\d{1,2})(?:st|nd|rd|th)?[\s,\-./_]+(\d{4})"),     # September 30, 2026; february-28-2026
    re.compile(r"(?<!\d)(\d{1,2})[\-./](\d{1,2})[\-./](\d{4}|\d{2})(?!\d)"),                           # 30.09.2026, 30-09-26 (Tata)
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),                                                  # 2026-09-30
)


def _s(c) -> str:
    return re.sub(r"\s+", " ", str(c)).strip() if c not in (None, "") else ""


def _num(c) -> float | None:
    if isinstance(c, (int, float)) and not isinstance(c, bool):
        return float(c)
    t = _s(c).replace(",", "").replace("%", "")
    if t in ("", "-", "--", "NIL", "Nil"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_date(text) -> date | None:
    """The first date in a title cell, in any of the forms the fund houses use."""
    if isinstance(text, datetime):
        return text.date()
    if isinstance(text, date):
        return text
    t = _s(text)
    for i, rx in enumerate(_DATE_PATTERNS):
        for m in rx.finditer(t):
            a, b, c = m.groups()
            if i in (0, 1, 2) and len(c) == 2:
                c = "20" + c
            try:
                if i == 0:
                    mo = _MONTHS.get(b[:3].lower())
                    d = date(int(c), mo, int(a)) if mo else None
                elif i == 1:
                    mo = _MONTHS.get(a[:3].lower())
                    d = date(int(c), mo, int(b)) if mo else None
                elif i == 2:
                    d = date(int(c), int(b), int(a))
                else:
                    d = date(int(a), int(b), int(c))
            except ValueError:
                d = None
            if d and 2000 <= d.year <= 2100:
                return d
    return None


def _month_end(ym: str) -> date:
    y, m = int(ym[:4]), int(ym[5:7])
    return date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1)


def _clean_scheme(name: str) -> str:
    name = re.sub(r"^[A-Z0-9]{2,8}\s*-\s*", "", name)               # "IB01-Groww Large Cap Fund"
    name = re.split(r"\s*\((?:an |a |formerly|erstwhile|earlier)", name, maxsplit=1, flags=re.I)[0]
    return name.strip(" -:")


def scheme_index(wb) -> dict[str, str]:
    """Sheet code -> scheme name, from an 'Index' sheet when the file has one
    (SBI, Tata, ABSL, Nippon, Motilal). The name is the row's longest text;
    the codes are its short, space-free cells — Motilal puts the code last,
    SBI first."""
    for s in wb.sheet_names:
        if not re.fullmatch(r"\s*index\s*", s, re.I):
            continue
        out: dict[str, str] = {}
        for r in wb.get_sheet_by_name(s).to_python():
            cells = [_s(c) for c in r if isinstance(c, str) and _s(c)]
            names = [c for c in cells if " " in c and re.search(r"[a-z]", c, re.I)]
            if not names or re.search(r"scheme name|fund name|^index$", names[0], re.I):
                continue
            name = max(names, key=len)
            for c in cells:
                if c != name and " " not in c and len(c) <= 16:
                    out.setdefault(c.upper(), name)
        return out
    return {}


def _columns(header: list) -> dict[str, int]:
    cols: dict[str, int] = {}
    for i, c in enumerate(header):
        t = _s(c).lower()
        if not t:
            continue
        if _HEADER_ISIN.match(t):
            cols.setdefault("isin", i)
        elif re.search(r"yield|ytm|ytc|coupon|maturity|put/call|sr\.? ?no", t):
            continue
        elif re.search(r"%|percent|to net asset|to nav|of nav|to aum", t):
            cols.setdefault("pct", i)
        elif re.search(r"value|exposure|mkt\.? ?val", t):
            cols.setdefault("value", i)
            cols.setdefault("_unit", i)
        elif re.search(r"quantity|no\.? of shares|units|^qty", t):
            cols.setdefault("qty", i)
        elif re.search(r"industry|rating|sector", t):
            cols.setdefault("industry", i)
        elif re.search(r"name|instrument|issuer|security|company", t):
            cols.setdefault("name", i)
    return cols


def _value_divisor(header_cell: str) -> float:
    """-> divide by this to get Rs crore."""
    t = header_cell.lower()
    if re.search(r"lakh|lac", t):
        return 100.0
    if re.search(r"crore|\bcr\b", t):
        return 1.0
    if re.search(r"thousand|'000", t):
        return 1e4
    if re.search(r"rs|inr|₹|rupee", t):
        return 1e7
    return 100.0


def parse_sheet(rows: list[list], sheet: str, index: dict[str, str]) -> list[dict]:
    hi = None
    for i, r in enumerate(rows[:60]):
        if any(_HEADER_ISIN.match(_s(c)) for c in r):
            hi = i
            break
    if hi is None:
        return []
    cols = _columns(rows[hi])
    if "isin" not in cols or "pct" not in cols and "value" not in cols:
        return []
    title = [c for r in rows[:hi] for c in r if c not in (None, "")]
    # A dated title ("Portfolio as on ...") first; any other date in the
    # title rows (a launch date, a risk-o-meter date) only as a fallback.
    stated = [c for c in title if re.search(r"as on|as at|ended|portfolio", _s(c), re.I)]
    as_of = next((d for d in (parse_date(c) for c in [*stated, *title]) if d), None)
    scheme = index.get(sheet.strip().upper(), "")
    if not scheme:
        for r in rows[:hi]:                       # 'SCHEME NAME' | 'Helios Flexi Cap Fund' (Helios)
            cells = [_s(c) for c in r if _s(c)]
            for a, b in zip(cells, cells[1:]):
                if re.fullmatch(r"(name of the )?scheme( name)?\s*:?", a, re.I):
                    scheme = b
    if not scheme:                            # 'MONTHLY PORTFOLIO STATEMENT OF SAMCO ... FUND AS ON ...' (Samco)
        for c in title:
            m = re.search(r"portfolio statement (?:of|for)\s+(?!the period)(.+?)(?:\s+(?:as on|as at|for the)\b.*)?$",
                          _s(c), re.I)
            if m and re.search(r"fund|scheme|etf|fof", m.group(1), re.I):
                scheme = m.group(1)
                break
    if not scheme:
        for c in title:
            t = _s(c)
            if (re.search(r"fund|scheme|etf|fof|plan|portfolio\b.*\bseries", t, re.I)
                    and not t.startswith("(")
                    and not re.search(r"portfolio (statement|as on)|as on|mutual fund\)?$|^monthly|investment manager|"
                                      r"asset management company|registered office|\bcin\b|e-?mail|trustee", t, re.I)):
                scheme = t
                break
    scheme = _clean_scheme(scheme or sheet)
    div = _value_divisor(_s(rows[hi][cols["_unit"]])) if "_unit" in cols else 100.0
    out = []
    for r in rows[hi + 1:]:
        # A sheet may carry several sections (equity, then debt), each under
        # its own header row and column order (ABSL, DSP; 2026-10-10).
        if any(_HEADER_ISIN.match(_s(c)) for c in r):
            nc = _columns(r)
            if "isin" in nc and ("pct" in nc or "value" in nc):
                cols = nc
                div = _value_divisor(_s(r[cols["_unit"]])) if "_unit" in cols else div
            continue
        if len(r) <= cols["isin"]:
            continue
        isin = _s(r[cols["isin"]]).upper()
        if not ISIN.match(isin):
            continue
        g = lambda k: r[cols[k]] if k in cols and cols[k] < len(r) else None  # noqa: E731
        v = _num(g("value"))
        out.append({"scheme": scheme, "sheet": sheet, "as_of": as_of, "isin": isin, "name": _s(g("name")),
                    "industry": _s(g("industry")), "qty": _num(g("qty")),
                    "value_cr": None if v is None else v / div, "pct": _num(g("pct"))})
    pcts = [x["pct"] for x in out if x["pct"] is not None]
    if pcts and max(pcts) <= 1.0 and sum(pcts) <= 1.6:
        for x in out:
            x["pct"] = None if x["pct"] is None else x["pct"] * 100
    return out


def _workbooks(data: bytes, name: str):
    """(member name, workbook) for a file, or for each spreadsheet in a zip."""
    from python_calamine import CalamineWorkbook
    # An .xlsx is itself a zip (with xl/ members); any other zip is an archive
    # of spreadsheets (ICICI: one per scheme; ABSL: one for the house).
    # By the leading bytes, not zipfile.is_zipfile: that finds a zip directory
    # inside some old OLE .xls files (PPFAS, HDFC; measured 2026-10-10).
    z = zipfile.ZipFile(io.BytesIO(data)) if data[:4] == b"PK\x03\x04" else None
    if z is not None and not any(n.startswith("xl/") for n in z.namelist()):
        for n in sorted(z.namelist()):
            if n.lower().endswith((".xls", ".xlsx", ".xlsb")) and not n.startswith("__MACOSX"):
                yield n, CalamineWorkbook.from_filelike(io.BytesIO(z.read(n)))
        return
    yield name, CalamineWorkbook.from_filelike(io.BytesIO(data))


def parse_file(data: bytes, name: str) -> list[dict]:
    out = []
    for member, wb in _workbooks(data, name):
        index = scheme_index(wb)
        for s in wb.sheet_names:
            if _SKIP_SHEET.search(s) and not index.get(s.strip().upper()):
                continue
            try:
                rows = wb.get_sheet_by_name(s).to_python()
            except Exception:  # noqa: BLE001 - one unreadable sheet must not lose the file
                continue
            for r in parse_sheet(rows, s, index):
                out.append({**r, "member": member})
    # One file is one month: every row takes the date most sheets state, so a
    # sheet whose title carries some other date cannot split the file.
    dates = Counter(r["as_of"] for r in out if r["as_of"])
    if dates:
        month = dates.most_common(1)[0][0]
        for r in out:
            r["as_of"] = month
    return out


def main() -> int:
    import gzip

    import duckdb

    from src.archive import mf_portfolios as A
    rows: list[dict] = []
    bad: list[str] = []
    for ln in A.MANIFEST.read_text().splitlines() if A.MANIFEST.exists() else []:
        r = json.loads(ln)
        if r.get("kind") != "file" or r.get("status") != "STORED":
            continue
        try:
            got = parse_file(gzip.decompress(Path(r["path"]).read_bytes()), r["url"].split("?")[0])
        except Exception as e:  # noqa: BLE001
            bad.append(f"{r['amc']} {Path(r['path']).name}: {type(e).__name__}")
            continue
        if not got:
            bad.append(f"{r['amc']} {Path(r['path']).name}: no ISIN table")
        # The file's own title dates it; the month its URL named is the fallback
        # (month-end), and an undated file with no title date is left undated.
        fallback = _month_end(r["month"]) if re.fullmatch(r"\d{4}-\d{2}", r.get("month") or "") else None
        for g in got:
            d = g["as_of"] or fallback
            rows.append({"amc": r["amc"], **g, "as_of": d.isoformat() if d else None, "source_file": Path(r["path"]).name})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cols = ["amc", "scheme", "as_of", "isin", "name", "industry", "qty", "value_cr", "pct", "sheet", "member", "source_file"]
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE t (" + ", ".join(
            f"{c} {'DOUBLE' if c in ('qty', 'value_cr', 'pct') else 'VARCHAR'}" for c in cols) + ")")
        con.executemany(f"INSERT INTO t VALUES ({', '.join('?' * len(cols))})", [[r.get(c) for c in cols] for r in rows])
        tmp = OUT.with_suffix(".parquet.partial")
        con.execute(f"COPY (SELECT * FROM t ORDER BY amc, scheme, as_of, value_cr DESC) TO '{tmp}' (FORMAT PARQUET)")
        tmp.replace(OUT)
        by = con.execute("SELECT amc, max(as_of), count(DISTINCT scheme), count(*) FROM t GROUP BY 1 ORDER BY 4 DESC").fetchall()
    finally:
        con.close()
    print(f"  MF PORTFOLIOS: {len(rows):,} holdings rows -> {OUT.name}; {len(bad)} files without a table")
    for a, m, s, n in by:
        print(f"    {a:<12} latest {m}  {s:>4} schemes  {n:>8,} rows")
    for b in bad[:10]:
        print(f"    ! {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
