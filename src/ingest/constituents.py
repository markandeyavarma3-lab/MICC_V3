"""constituents.py — archived index lists become point-in-time membership.

WHAT THIS IS FOR. `sector_history` has 0 rows and `char_panel` declares
industry MISSING; exp_004 names index inclusion as a confound it cannot yet
control. The archive (`src/archive/constituents.py`) holds six index lists —
the NIFTY 500 and the size buckets that compose it — stored ONLY when a list
changes, so it is a change log: one file per (index, rebalance), not per day.

THE TABLE IS SNAPSHOTS, NOT DAYS. One row per (snapshot date, index, ISIN),
with the industry NSE assigns. Membership on any date is the most recent
snapshot at or before it — an ASOF join, the same construction `char_panel`
uses for characteristics. No daily expansion is materialised: 2,900 names x
6 lists x every day is a large table saying the same thing as 6 small ones.

THE MANIFEST SAYS WHICH INDEX A FILE IS. The 2026-09-15 proof file carries no
index in its name; the later ones do. Reading the name would misfile the
proof. The manifest row has source_id, session_date and path for every one.

HISTORY STARTS 2026-09-15. There is no dated route anywhere (probed
2026-09-18, both hosts); the first snapshot is the earliest membership this
project can ever assert. A study that needs 2021 membership does not have it,
and the table cannot pretend otherwise — a query for a date before the first
snapshot gets no rows, not the first snapshot.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, COLLECTED  # noqa: E402
from src.governance import provenance as prov  # noqa: E402

MANIFEST = ARCHIVE / "manifest.jsonl"
OUT = COLLECTED / "constituents" / "constituents.parquet"
PRODUCED_BY = "src/ingest/constituents.py"

#: source_id -> the index key the closes table uses (src/ingest/index_close.py).
INDEX_KEY = {
    "nifty500_constituents": "NIFTY500",
    "nifty50_constituents": "NIFTY50",
    "niftynext50_constituents": "NIFTYNEXT50",
    "niftymidcap150_constituents": "NIFTYMIDCAP150",
    "niftysmallcap250_constituents": "NIFTYSMALLCAP250",
    "niftymicrocap250_constituents": "NIFTYMICROCAP250",
}


@dataclass(frozen=True, slots=True)
class Member:
    snapshot_date: str
    index_key: str
    isin: str
    symbol: str
    company: str
    industry: str
    series: str
    source_file: str


def snapshots() -> list[tuple[str, str, Path]]:
    """(session_date, index_key, path) for every STORED constituents file, from the manifest."""
    out = []
    if not MANIFEST.exists():
        return out
    for line in MANIFEST.read_text(errors="ignore").splitlines():
        if "_constituents" not in line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = INDEX_KEY.get(r.get("source_id", ""))
        if key and r.get("status") == "STORED" and r.get("path") and r.get("session_date"):
            p = Path(r["path"])
            if not p.is_absolute():
                p = ARCHIVE / p
            out.append((r["session_date"][:10], key, p))
    return sorted(out)


def parse_file(path: Path, snapshot_date: str, index_key: str) -> list[Member]:
    with gzip.open(path, "rb") as fh:
        text = fh.read().decode("utf-8", "replace")
    out: list[Member] = []
    for r in csv.DictReader(io.StringIO(text)):
        isin = (r.get("ISIN Code") or "").strip().upper()
        sym = (r.get("Symbol") or "").strip().upper()
        if not isin or not sym:
            continue
        out.append(Member(snapshot_date, index_key, isin, sym, (r.get("Company Name") or "").strip(),
                          (r.get("Industry") or "").strip(), (r.get("Series") or "").strip(), path.name))
    return out


def parse() -> list[Member]:
    out: list[Member] = []
    for d, key, p in snapshots():
        if p.exists():
            out.extend(parse_file(p, d, key))
    return out


def write(rows: list[Member]) -> Path:
    import duckdb

    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("""CREATE TABLE t (snapshot_date DATE, index_key VARCHAR, isin VARCHAR, symbol VARCHAR,
                       company VARCHAR, industry VARCHAR, series VARCHAR, source_file VARCHAR)""")
        con.executemany("INSERT INTO t VALUES (?,?,?,?,?,?,?,?)",
                        [(m.snapshot_date, m.index_key, m.isin, m.symbol, m.company, m.industry, m.series, m.source_file) for m in rows])
        tmp = OUT.with_suffix(".parquet.partial")
        con.execute(f"COPY (SELECT DISTINCT * FROM t ORDER BY index_key, snapshot_date, isin) TO '{tmp}' (FORMAT PARQUET)")
        tmp.replace(OUT)
    finally:
        con.close()
    return OUT


def membership_sql(index_key: str, table: str | Path = OUT) -> str:
    """SQL for (d, isin) membership of `index_key` on every date d in `dates`
    — a CTE the caller supplies — by ASOF against the snapshots. Dates before
    the first snapshot get NO rows: membership this project cannot assert is
    not asserted."""
    return f"""
        SELECT x.d, s.isin, s.industry
        FROM dates x
        -- LEFT TABLE FIRST in the inequality. DuckDB reads ASOF's condition
        -- as `left >= right`; written `right <= left` it matched the nearest
        -- snapshot AFTER the date, and a 09-10 query returned the 09-17 list.
        ASOF JOIN (SELECT DISTINCT snapshot_date FROM read_parquet('{table}') WHERE index_key = '{index_key}') snap
          ON x.d >= snap.snapshot_date
        JOIN read_parquet('{table}') s ON s.index_key = '{index_key}' AND s.snapshot_date = snap.snapshot_date"""


def main() -> int:
    rows = parse()
    if not rows:
        print("CONSTITUENTS: no archived lists to parse")
        return 0
    write(rows)
    prov.register_dataset(OUT.parent, artefact_type="SOURCE", logical_name="collected:constituents",
                          produced_by=PRODUCED_BY, pattern="**/*.parquet",
                          params={"source": "nsearchives ind_*list.csv, six lists, sha256 change log"})
    by: dict[str, set[str]] = {}
    for m in rows:
        by.setdefault(m.index_key, set()).add(m.snapshot_date)
    print(f"  {len(rows):,} membership row(s) across {len(by)} index(es)")
    for k, ds in sorted(by.items()):
        n = sum(1 for m in rows if m.index_key == k and m.snapshot_date == max(ds))
        print(f"    {k:<18} {len(ds)} snapshot(s), {min(ds)} -> {max(ds)}, {n} name(s) in the latest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
