"""index_tri.py — archived NIFTY 500 total-return slices become one table.

WHAT THIS IS FOR. benchmarks.yml's NIFTY500_TR points at `warehouse.
benchmark_n500tr`, which has never existed; every study's "market" has been
the PRICE index, which understates the market by its dividend yield — about
1.2% a year on the NIFTY 500, or 0.3% a quarter, which is a fifth of
exp_004's 1.5%/quarter bound. This lands the archived slices (INDEX_TRI/,
`src/archive/index_tri.py`) as the table that name has always promised.

ONE ROW PER DATE, LATEST SLICE WINS. The slices overlap by construction — a
year-long backfill window and a 45-day daily top-up both contain last
Tuesday — and the host may restate a value. The row from the slice archived
LAST is kept, and `source_file` says which, so a restatement is visible in
the archive and not silent in the table.

Numbers are parsed as written. TotalReturnsIndex is a string like "742.26";
NTR_Value (net of withholding on dividends) is "-" before the host started
computing it — 2,898 of 7,855 rows carry one — and lands as NULL there.
No return is derived here, and no rebasing: a study reads the level and
takes the ratio it needs.
"""

from __future__ import annotations

import glob
import gzip
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, COLLECTED  # noqa: E402
from src.governance import provenance as prov  # noqa: E402
from src.ingest.index_close import _num, index_key  # noqa: E402

GLOB = str(ARCHIVE / "INDEX_TRI" / "NSE" / "**" / "*.json.gz")
OUT = COLLECTED / "index_tri" / "index_tri.parquet"
PRODUCED_BY = "src/ingest/index_tri.py"


@dataclass(frozen=True, slots=True)
class Row:
    date: str
    index_name: str
    index_key: str
    tri: float | None
    ntr: float | None
    source_file: str


def parse_file(path: str) -> list[Row]:
    with gzip.open(path, "rb") as fh:
        try:
            items = json.loads(fh.read())
        except json.JSONDecodeError:
            return []
    if not isinstance(items, list):
        return []
    out: list[Row] = []
    for r in items:
        name = (r.get("Index Name") or "").strip()
        raw = (r.get("Date") or "").strip()
        if not name or not raw:
            continue
        try:
            d = datetime.strptime(raw, "%d %b %Y").date().isoformat()
        except ValueError:
            continue
        out.append(Row(d, name, index_key(name), _num(r.get("TotalReturnsIndex")),
                       _num(r.get("NTR_Value")), Path(path).name))
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
        con.execute("CREATE TABLE t (date DATE, index_name VARCHAR, index_key VARCHAR,"
                    " tri DOUBLE, ntr DOUBLE, source_file VARCHAR)")
        con.executemany("INSERT INTO t VALUES (?,?,?,?,?,?)",
                        [(r.date, r.index_name, r.index_key, r.tri, r.ntr, r.source_file) for r in rows])
        # Latest slice wins. File names carry the slice's end date and then
        # its digest, so the lexically greatest name for a date is the slice
        # archived for the latest window — the daily top-up, over the backfill.
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
        print("INDEX TRI: no archived slices to parse")
        return 0
    write(rows)
    prov.register_dataset(OUT.parent, artefact_type="SOURCE", logical_name="collected:index_tri",
                          produced_by=PRODUCED_BY, pattern="**/*.parquet",
                          params={"source": "niftyindices /BackPage/getTotalReturnIndexString"})
    dates = sorted({r.date for r in rows})
    print(f"  {len(rows):,} slice row(s) -> {len(dates):,} session(s) {dates[0]} -> {dates[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
