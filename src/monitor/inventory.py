"""inventory.py — every table on disk, counted rather than remembered.

WHY THIS IS GENERATED AND NOT WRITTEN.

On 2026-09-01 both predecessor repositories were deleted (decision 0042) and the
reasonable question that followed was "where did the data go?". Answering it
required counting 126 seed tables, four spines, the salvage and two databases by
hand, and a hand-written answer would have been stale the next time the collector
ran.

The same argument as `status.py`: MICCV2's README described a cron schedule that
had drifted from the actual crontab. A data inventory drifts faster than a
schedule does, because every collection changes it.

WHAT "CROSS-CHECKED" MEANS HERE. Three things, and they are different:

  ROWS      counted from the parquet or the database, now, not from a note.
  SPAN      min and max of the date column where one exists, so a table that
            silently stopped updating is visible as a stale max rather than as
            a healthy row count.
  DUPLICATE the seed and the spines overlap by design — `stock_data` is the
            seed's copy and `price_spine` is the built one. Reporting their sum
            as a total would double-count 7.6M rows, so provenance is stated per
            table and the totals are grouped, never summed across groups.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import duckdb

from src.common.paths import (
    COLLECTED, DOCS, ROOT, SALVAGED, SEED, SEED_INCREMENTS,
    governance_db, research_db, warehouse_dir,
)

INVENTORY_PATH = DOCS / "DATA_INVENTORY.md"

#: Columns that mean "when", in the order we prefer them. Tables use different
#: names for the same idea and guessing wrongly reports a healthy table as
#: undated, which reads like a defect.
DATE_COLS = ("date", "trade_date", "TradDt", "session_date", "ex_date",
             "as_of_date", "period_end", "timestamp", "dt")


@dataclass(frozen=True, slots=True)
class Table:
    group: str
    name: str
    rows: int
    cols: int
    span: str
    bytes: int
    note: str = ""


def _dir_bytes(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _span(con, glob: str, columns: list[str]) -> str:
    for c in DATE_COLS:
        if c in columns:
            try:
                lo, hi = con.execute(
                    f'SELECT MIN(CAST("{c}" AS VARCHAR)), MAX(CAST("{c}" AS VARCHAR))'
                    f" FROM read_parquet('{glob}')").fetchone()
                if lo:
                    return f"{str(lo)[:10]} → {str(hi)[:10]}"
            except duckdb.Error:
                continue
    return "—"


def _parquet_group(con, root: Path, group: str, note: str = "") -> list[Table]:
    out: list[Table] = []
    if not root.exists():
        return out
    for p in sorted(root.iterdir()):
        if p.name.startswith("."):
            continue
        if p.is_file() and p.suffix == ".parquet":
            glob = str(p)
        elif p.is_dir() and any(p.rglob("*.parquet")):
            glob = f"{p}/**/*.parquet"
        else:
            continue
        try:
            cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{glob}')").fetchall()]
            rows = con.execute(f"SELECT COUNT(*) FROM read_parquet('{glob}')").fetchone()[0]
        except duckdb.Error as exc:
            out.append(Table(group, p.stem, -1, 0, "—", _dir_bytes(p), f"UNREADABLE: {exc}"[:60]))
            continue
        out.append(Table(group, p.stem, rows, len(cols), _span(con, glob, cols), _dir_bytes(p), note))
    return out


def collect(env: str = "prod") -> list[Table]:
    con = duckdb.connect()
    con.execute("SET memory_limit='6GB'; SET preserve_insertion_order=false;")
    t: list[Table] = []
    t += _parquet_group(con, SEED, "1. Seed — v1_export",
                        "carried from MICCV2 under 0027")
    t += _parquet_group(con, SEED_INCREMENTS, "2. Increments — v1_increments",
                        "MICCV2 collector, 2026-07-09 onward")
    t += _parquet_group(con, COLLECTED, "3. Collected by this project",
                        "NSE direct, 2026-08-17 onward")
    t += _parquet_group(con, warehouse_dir(env), "4. Built warehouse",
                        "DERIVED — rebuildable from 1+2+3")
    for sub, note in (("seasonality", "the atlas Phase 7 validates (0026)"),
                      ("miccv2_state", "MICCV2 state, kept whole")):
        t += _parquet_group(con, SALVAGED / sub, "5. Salvaged (0042)", note)
    con.close()
    return t


def databases(env: str = "prod") -> list[Table]:
    out: list[Table] = []
    db = research_db(env)
    if db.exists():
        con = duckdb.connect(str(db), read_only=True)
        for (n,) in con.execute("SELECT table_name FROM duckdb_tables() ORDER BY table_name").fetchall():
            rows = con.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0]
            cols = con.execute(f"SELECT COUNT(*) FROM duckdb_columns() WHERE table_name='{n}'").fetchone()[0]
            out.append(Table("6. research.duckdb", n, rows, cols, "—",
                             0, "" if rows else "empty — not yet built"))
        con.close()
    g = governance_db(env)
    if g.exists():
        gc = sqlite3.connect(g)
        for (n,) in gc.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            if n.startswith("sqlite_"):
                continue
            rows = gc.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0]
            cols = len(gc.execute(f"PRAGMA table_info({n})").fetchall())
            out.append(Table("7. governance.sqlite", n, rows, cols, "—",
                             0, "" if rows else "empty — not yet built"))
        gc.close()
    return out


def render(tables: list[Table]) -> str:
    from datetime import UTC, datetime

    lines = [
        "# Data inventory",
        "",
        "**Generated by `src/monitor/inventory.py`. Do not edit.**",
        "",
        f"Counted at {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC. Every row "
        "count and date span below was measured at generation time, not recorded "
        "from a previous run.",
        "",
        "**Groups do not sum.** `stock_data` in group 1 and `price_spine` in "
        "group 4 are the same prices — one carried, one built. Adding the group "
        "totals would double-count roughly 190 million rows. Group 4 is derived "
        "and rebuildable; groups 1, 2, 3 and 5 are the inputs, and only those are "
        "irreplaceable.",
        "",
    ]
    groups: dict[str, list[Table]] = {}
    for t in tables:
        groups.setdefault(t.group, []).append(t)

    lines += ["## Totals by group", "", "| group | tables | rows | on disk |", "|---|---:|---:|---:|"]
    for g, ts in groups.items():
        r = sum(max(0, x.rows) for x in ts)
        b = sum(x.bytes for x in ts)
        size = f"{b/1e9:.2f} GB" if b >= 1e9 else (f"{b/1e6:.0f} MB" if b else "—")
        lines.append(f"| {g} | {len(ts)} | {r:,} | {size} |")
    lines.append("")

    for g, ts in groups.items():
        lines += [f"## {g}", "", "| table | rows | cols | span | size | note |",
                  "|---|---:|---:|---|---:|---|"]
        for x in sorted(ts, key=lambda x: -x.rows):
            size = (f"{x.bytes/1e9:.2f} GB" if x.bytes >= 1e9
                    else f"{x.bytes/1e6:.1f} MB" if x.bytes >= 1e6
                    else f"{x.bytes/1e3:.0f} KB" if x.bytes else "—")
            rows = "UNREADABLE" if x.rows < 0 else f"{x.rows:,}"
            lines.append(f"| `{x.name}` | {rows} | {x.cols} | {x.span} | {size} | {x.note} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    tables = collect() + databases()
    INVENTORY_PATH.write_text(render(tables))
    groups: dict[str, list[Table]] = {}
    for t in tables:
        groups.setdefault(t.group, []).append(t)
    print("DATA INVENTORY")
    for g, ts in groups.items():
        r = sum(max(0, t.rows) for t in ts)
        print(f"  {g:<32}{len(ts):>4} tables{r:>16,} rows")
    bad = [t for t in tables if t.rows < 0]
    for t in bad:
        print(f"  UNREADABLE: {t.group} / {t.name}")
    print(f"\n  wrote {INVENTORY_PATH.relative_to(ROOT)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
