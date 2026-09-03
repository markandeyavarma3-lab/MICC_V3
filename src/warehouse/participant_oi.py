"""participant_oi.py — loads the FII/DII proxy that has sat unread in the seed.

WHY THIS EXISTS. `configs/sources.yml` has carried `participant_oi` since
decision 0027 — HAVE status, 15,359 rows, 2014-01-01 -> 2026-06-25, ported from
the V1 export. Nothing ever loaded it: an audit found 109 of the seed's 119
tables were never read by any code, and this was one of them. Actual cash-flow
FII/DII history is nearly unobtainable (`sources.yml`'s own note: "History is
unobtainable retrospectively — it accrues forward only," and this project's
live collector holds 12 days). This table has ELEVEN YEARS, already on disk,
for the price of a load.

IT IS NOT FII/DII CASH FLOW. `sources.yml`, in capitals: *"This is F&O
participant-wise open interest — DERIVATIVES POSITIONING, NOT CASH-MARKET
FLOW. A different measure, and every study using it must say so rather than
calling it FII/DII flow."* The migration's column names (`oi_*`, not `flow_*`)
and this module's own vocabulary hold that line: nothing here is called a
"flow" or a "trade". A position is not a transaction, and open interest can grow
without anyone buying anything today — it can also just be yesterday's position
carried forward.

TOTAL IS A COMPUTED ROW, KEPT. The source data includes a `TOTAL` category that
sums the other four. Dropping it silently would make a naive `GROUP BY
session_date` double the true total for anyone who forgets to filter it out;
keeping it and constraining the five values in the schema (0004 migration) makes
that a query decision, not a landmine.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import duckdb  # noqa: E402

from src.common.hashing import hash_file  # noqa: E402
from src.common.paths import SEED, research_db  # noqa: E402
from src.common.migrate import migrate_duckdb  # noqa: E402
from src.governance import provenance as prov  # noqa: E402

SOURCE_FILE = SEED / "participant_oi.parquet"
PRODUCED_BY = "src/warehouse/participant_oi.py"

#: The seed's column names, in the exact order the migration declares them.
#: Declared once so a schema drift in either file breaks loudly at the INSERT
#: rather than silently reordering values into the wrong column.
_COLUMNS = (
    "date", "category", "index_fut_long", "index_fut_short", "index_fut_net",
    "index_call_long", "index_call_short", "index_put_long", "index_put_short",
    "stock_fut_long", "stock_fut_short", "stock_fut_net",
    "stock_call_long", "stock_put_long",
)


def load(env: str | None = None) -> int:
    """Load `participant_oi.parquet` into the `participant_oi` table.

    Idempotent: rewrites the table from the seed file each run rather than
    appending, because the seed file is the single source of truth for this
    range and nothing else writes to this table yet. A future live collector
    (0007-style stopgap) would append past `MAX(session_date)`, not replace.
    """
    if not SOURCE_FILE.exists():
        raise FileNotFoundError(
            f"{SOURCE_FILE} not found — the seed must be carried first "
            f"(python -m src.warehouse.seed)"
        )

    db = research_db(env)
    migrate_duckdb(db)
    con = duckdb.connect(str(db))
    try:
        other_cols = ", ".join(f'"{c}"' for c in _COLUMNS if c != "date")
        con.execute(f"""
            CREATE OR REPLACE TEMP VIEW _src AS
            SELECT CAST(date AS DATE) AS session_date, {other_cols}
            FROM read_parquet('{SOURCE_FILE}')
        """)
        con.execute("DELETE FROM participant_oi WHERE source = 'v1_export'")
        con.execute(f"""
            INSERT INTO participant_oi (
                session_date, category, index_fut_long, index_fut_short,
                index_fut_net, index_call_long, index_call_short,
                index_put_long, index_put_short, stock_fut_long,
                stock_fut_short, stock_fut_net, stock_call_long, stock_put_long
            )
            SELECT session_date, {other_cols} FROM _src
        """)
        n = con.execute(
            "SELECT COUNT(*) FROM participant_oi WHERE source = 'v1_export'"
        ).fetchone()[0]
        con.commit()
    finally:
        con.close()

    digest = hash_file(SOURCE_FILE)
    prov.register(
        prov.Artefact(
            digest, "SOURCE", "v1seed:participant_oi", PRODUCED_BY,
            row_count=n,
            params={"note": "F&O open interest by participant type; NOT cash "
                             "flow. sources.yml note verbatim in the module "
                             "docstring.",
                    "categories": "FII,DII,Pro,Client,TOTAL"},
        ),
        env=env,
    )
    return n


def main() -> int:
    n = load()
    print(f"PARTICIPANT_OI: {n:,} rows loaded")
    con = duckdb.connect(str(research_db()))
    try:
        span = con.execute(
            "SELECT MIN(session_date), MAX(session_date), "
            "COUNT(DISTINCT category) FROM participant_oi"
        ).fetchone()
        print(f"  span: {span[0]} -> {span[1]}   categories: {span[2]}")
        print(f"  registered as v1seed:participant_oi, {n:,} rows")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
