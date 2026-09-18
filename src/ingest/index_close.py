"""index_close.py — archived all-index daily closes become one long table.

WHAT THIS IS FOR. benchmarks.yml names the NIFTY 500 as the market leg and
the studies compute market-relative returns against the seed's
`global_indices_daily.parquet` — which ends 2026-07-07. Every cohort after
2026-Q1 therefore has no market return in the seed, and exp_004's panel would
lose its most recent quarters to a stale benchmark file. The archive holds
every NSE index's close daily from 2021-10-18 (`src/archive/index_close.py`,
1,281 sessions on 2026-09-18); this lands it as a table the studies can read.

ONE ROW PER (session, index), LONG. 92 indices in 2021, 167 in 2026 — NSE
adds indices; a wide table would need a schema change every time. The name is
kept exactly as NSE writes it ("Nifty 50", "Nifty 500") plus a normalised key
(`index_key`: upper, no spaces — NIFTY50, NIFTY500) that matches the seed's
`symbol` column so a study can UNION the two series at the seed's end date.

THE DATE IS VERIFIED TWICE. The archive verified the file's own `Index Date`
against the requested session before storing it; this parser reads the date
from the ROW, not the filename, and refuses a row whose date disagrees with
the file's session — a defence against a file that lies internally.

Numbers are parsed as written; NSE writes ".76" for 0.76 and "-" for missing.
Nothing is derived. No return, no rebasing, no total-return construction —
the TRI is a different archive (INDEX_TRI/) and a different decision.
"""

from __future__ import annotations

import csv
import glob
import gzip
import io
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, COLLECTED  # noqa: E402
from src.governance import provenance as prov  # noqa: E402

GLOB = str(ARCHIVE / "INDEX_CLOSE" / "NSE" / "**" / "*.csv.gz")
OUT = COLLECTED / "index_close" / "index_close.parquet"
PRODUCED_BY = "src/ingest/index_close.py"

COLS = {
    "Index Name": "index_name", "Index Date": "date", "Open Index Value": "open",
    "High Index Value": "high", "Low Index Value": "low", "Closing Index Value": "close",
    "Points Change": "points_change", "Change(%)": "change_pct", "Volume": "volume",
    "Turnover (Rs. Cr.)": "turnover_cr", "P/E": "pe", "P/B": "pb", "Div Yield": "div_yield",
}
_SESSION = re.compile(r"_(\d{8})_[0-9a-f]{8}\.csv\.gz$")


@dataclass(frozen=True, slots=True)
class Row:
    date: str
    index_name: str
    index_key: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    points_change: float | None
    change_pct: float | None
    volume: float | None
    turnover_cr: float | None
    pe: float | None
    pb: float | None
    div_yield: float | None
    source_file: str


def _num(s: str) -> float | None:
    s = (s or "").strip().replace(",", "")
    if s in ("", "-", "NA", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def index_key(name: str) -> str:
    """'Nifty 50' -> 'NIFTY50', matching the seed's symbol convention."""
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def parse_file(path: str) -> list[Row]:
    m = _SESSION.search(path)
    session = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else None
    with gzip.open(path, "rb") as fh:
        text = fh.read().decode("utf-8", "replace")
    reader = csv.DictReader(io.StringIO(text))
    out: list[Row] = []
    for r in reader:
        name = (r.get("Index Name") or "").strip()
        raw = (r.get("Index Date") or "").strip()
        if not name or not raw:
            continue
        try:
            d = datetime.strptime(raw, "%d-%m-%Y").date().isoformat()
        except ValueError:
            continue
        if session and d != session:
            # The file's own rows disagree with the session it was archived
            # under. The archive checked the FIRST row; this checks every row.
            continue
        out.append(Row(d, name, index_key(name), _num(r.get("Open Index Value")), _num(r.get("High Index Value")),
                       _num(r.get("Low Index Value")), _num(r.get("Closing Index Value")), _num(r.get("Points Change")),
                       _num(r.get("Change(%)")), _num(r.get("Volume")), _num(r.get("Turnover (Rs. Cr.)")),
                       _num(r.get("P/E")), _num(r.get("P/B")), _num(r.get("Div Yield")), Path(path).name))
    return out


def parse() -> list[Row]:
    out: list[Row] = []
    for f in sorted(glob.glob(GLOB, recursive=True)):
        out.extend(parse_file(f))
    return out


def write(rows: list[Row]) -> Path:
    import duckdb

    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("""CREATE TABLE t (date DATE, index_name VARCHAR, index_key VARCHAR,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, points_change DOUBLE, change_pct DOUBLE,
            volume DOUBLE, turnover_cr DOUBLE, pe DOUBLE, pb DOUBLE, div_yield DOUBLE, source_file VARCHAR)""")
        con.executemany("INSERT INTO t VALUES (" + ",".join("?" * 15) + ")",
                        [(r.date, r.index_name, r.index_key, r.open, r.high, r.low, r.close, r.points_change,
                          r.change_pct, r.volume, r.turnover_cr, r.pe, r.pb, r.div_yield, r.source_file) for r in rows])
        # One row per (date, index): a session archived twice under two digests
        # (a re-published file) keeps the LATER archive's row.
        tmp = OUT.with_suffix(".parquet.partial")
        con.execute(f"""COPY (SELECT * EXCLUDE rn FROM (
                           SELECT *, ROW_NUMBER() OVER (PARTITION BY date, index_key ORDER BY source_file DESC) rn FROM t)
                         WHERE rn = 1 ORDER BY date, index_key) TO '{tmp}' (FORMAT PARQUET)""")
        tmp.replace(OUT)
    finally:
        con.close()
    return OUT


def main() -> int:
    rows = parse()
    if not rows:
        print("INDEX CLOSE: no archived files to parse")
        return 0
    write(rows)
    prov.register_dataset(OUT.parent, artefact_type="SOURCE", logical_name="collected:index_close",
                          produced_by=PRODUCED_BY, pattern="**/*.parquet",
                          params={"source": "nsearchives ind_close_all_{DDMMYYYY}.csv"})
    dates = sorted({r.date for r in rows})
    keys = {r.index_key for r in rows}
    print(f"  {len(rows):,} row(s), {len(dates):,} session(s) {dates[0]} -> {dates[-1]}, {len(keys)} distinct index(es)")
    for k in ("NIFTY50", "NIFTY500", "NIFTYMIDCAP150", "NIFTYSMALLCAP250"):
        n = sum(1 for r in rows if r.index_key == k)
        print(f"    {k:<18} {n:,} session(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
