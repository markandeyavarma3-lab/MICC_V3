"""master.py — who a symbol actually was on the day it traded. Plan 1 §6.

THE PROBLEM, MEASURED. A symbol is not an identity. In the V1 masters:

    331 symbols map to MORE THAN ONE ISIN   <- the same ticker, reused
    276 ISINs  map to MORE THAN ONE symbol  <- the same company, renamed

The second is the one the split already handles: CADILAHC became ZYDUSLIFE, and
keying a partition on the symbol would put one company in two strata
(decision 0009). **The first is worse and less discussed.** When a ticker is
recycled, a naive symbol join silently attributes one company's deal to another
company's prices — and nothing in the output looks wrong.

Both are solved the same way: resolution is POINT-IN-TIME. `symbol_history`
carries a validity window per (symbol, security), and `resolve` asks who held
that ticker *on the trade date*, never who holds it today.

CONFIDENCE IS LOAD-BEARING, NOT DECORATION. Owner decision 2026-08-24 chose
best-effort resolution with a confidence grade over refusing anything ambiguous.
That is a deliberate trade: it recovers events a strict rule would discard, and
it accepts that some resolutions are guesses. The guarantee that makes it safe is
that **the grade is stored on every row**, so a study can require HIGH and a
sensitivity run can vary it — and a wrong match can never masquerade as certain.

    HIGH    exactly one security held this symbol on that date
    MEDIUM  the symbol is known, but no validity window covers the trade date —
            resolved to the nearest window
    LOW     several securities held this symbol on that date; resolved to the
            one whose window fits best
    UNRESOLVED  the symbol appears in no master
    UNCOVERED   unresolved AND absent from the price spine, so there is no
                forward return to measure regardless (decision 0032)

WHAT MEDIUM ACTUALLY MEANS HERE, AND IT IS NOT "DUBIOUS".

Measured over 236,491 rows: HIGH 37.3%, **MEDIUM 48.2%**, LOW 1.7%,
UNRESOLVED 4.1%, UNCOVERED 8.7%. Half the corpus grading MEDIUM looks alarming
until you ask why, and the answer is an artefact of how the master was built
rather than a property of the deals:

    1,470 of 3,735 symbol_history rows begin on EXACTLY 2011-07-01  (39.4%)

Two and a half thousand securities did not list on the same Friday.
`first_date` in the legacy master is a REGISTRY-CREATION date, not a listing
date. So every deal before 2011-07-01 — 60,959 of them, 25.8% of the corpus —
falls outside its symbol's window by construction, and 60,795 of the MEDIUM
grades are exactly that.

The match in those cases is very probably correct; what is missing is a window
that can *confirm* it. MEDIUM therefore reads "unconfirmable from this master",
not "likely wrong" — and the two must not be conflated when a study filters on
confidence. Recovering them needs a real listing-date source, which the seed
does not contain.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from src.common.migrate import migrate_duckdb
from src.common.paths import SEED, research_db, warehouse_dir
from src.governance import provenance as prov

PRODUCED_BY = "src.identity.master:build"

#: A security is dead if it has not traded for this long before the spine ends.
#: universe.yml `delisting.stale_sessions_to_declare_dead`.
STALE_SESSIONS = 20

#: `isin_master` IS TWO DATASETS CONCATENATED, and the date format gives it away.
#: Measured 2026-08-24: 2,528 rows carry ISO first_date AND ISO last_date, while
#: 1,207 carry DD-MON-YYYY first_date and a NULL last_date. The split is exact —
#: format predicts source perfectly — so one CAST would silently drop a third of
#: the master, and the third it drops is the CURRENTLY ACTIVE one.
#:
#: try_strptime returns NULL rather than raising, so an unparseable date becomes
#: an open window instead of an exception, and the row survives with a lower
#: confidence grade rather than vanishing.
def _date(col: str) -> str:
    return (f"COALESCE(try_strptime({col}, '%Y-%m-%d'),"
            f" try_strptime({col}, '%d-%b-%Y'))::DATE")


@dataclass
class BuildReport:
    securities: int = 0
    symbol_rows: int = 0
    reused_symbols: int = 0
    renamed_isins: int = 0

    def render(self) -> str:
        return (f"  securities       {self.securities:>7,}\n"
                f"  symbol_history   {self.symbol_rows:>7,}\n"
                f"  symbols reused across securities {self.reused_symbols:>5,}"
                f"   <- the silent-mismatch risk\n"
                f"  ISINs renamed                    {self.renamed_isins:>5,}")


def build(env: str | None = None) -> BuildReport:
    """Populate security_master and symbol_history from the V1 masters.

    `isin_master` already carries first_date/last_date per (isin, symbol), which
    IS a validity window — so point-in-time resolution needs no new data, only
    for the window to be respected instead of ignored.
    """
    db = research_db(env)
    migrate_duckdb(db)
    con = duckdb.connect(str(db))
    im = str(SEED / "isin_master.parquet")
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")

    try:
        con.execute("DELETE FROM symbol_history")
        con.execute("DELETE FROM security_master")

        # One security per ISIN. The canonical symbol is the one held LONGEST,
        # not the most recent: a company that traded 15 years as X and 6 months
        # as Y is more findable under X, and `symbol_history` carries both.
        con.execute(f"""
            INSERT INTO security_master (
                security_id, isin, canonical_symbol, company_name, listing_date,
                delisting_date, delisting_reason, status, merged_into_id, source, confidence)
            WITH m AS (
                SELECT UPPER(TRIM(isin)) AS isin, UPPER(TRIM(symbol)) AS symbol,
                       company,
                       COALESCE(try_strptime(first_date,'%Y-%m-%d'),try_strptime(first_date,'%d-%b-%Y'))::DATE AS first_date,
                       COALESCE(try_strptime(last_date,'%Y-%m-%d'),try_strptime(last_date,'%d-%b-%Y'))::DATE AS last_date,
                       COALESCE(COALESCE(try_strptime(last_date, '%Y-%m-%d'), try_strptime(last_date, '%d-%b-%Y'))::DATE, DATE '2099-12-31')
                         - COALESCE(COALESCE(try_strptime(first_date, '%Y-%m-%d'), try_strptime(first_date, '%d-%b-%Y'))::DATE, DATE '1990-01-01') AS held_days
                FROM read_parquet('{im}') WHERE isin IS NOT NULL
            ),
            ranked AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY isin ORDER BY held_days DESC, symbol) rn
                FROM m
            ),
            spine_last AS (
                SELECT UPPER(TRIM(symbol)) AS symbol, MAX(date) AS last_trade
                FROM read_parquet('{spine}') GROUP BY 1
            ),
            spine_end AS (SELECT MAX(last_trade) AS e FROM spine_last)
            SELECT
                ROW_NUMBER() OVER (ORDER BY r.isin),
                r.isin, r.symbol, COALESCE(r.company, r.symbol),
                r.first_date,
                -- Delisting is DETECTED from the last observed trade, never
                -- assumed from is_active, which is a current-state flag.
                CASE WHEN s.last_trade IS NOT NULL
                      AND s.last_trade < (SELECT e FROM spine_end)
                     THEN CAST(s.last_trade AS DATE) END,
                -- UNKNOWN beats inference (standing rule 9). Classifying a
                -- delisting as MERGER vs SUSPENSION needs corporate actions this
                -- does not yet read, so it says so rather than guessing.
                CASE WHEN s.last_trade IS NOT NULL
                      AND s.last_trade < (SELECT e FROM spine_end)
                     THEN 'UNKNOWN' END,
                CASE WHEN s.last_trade IS NULL THEN 'SUSPENDED'
                     WHEN s.last_trade < (SELECT e FROM spine_end) THEN 'DELISTED'
                     ELSE 'ACTIVE' END,
                NULL,
                'v1seed:isin_master',
                CASE WHEN r.first_date IS NOT NULL AND s.last_trade IS NOT NULL
                     THEN 'HIGH' ELSE 'MEDIUM' END
            FROM ranked r
            LEFT JOIN spine_last s ON s.symbol = r.symbol
            WHERE r.rn = 1
        """)

        # Every (symbol, security) pairing with the window it was valid for.
        # A NULL last_date means "still current" and becomes an open window —
        # NOT a closed one at the export date, which would make every current
        # symbol unresolvable for recent trades.
        con.execute(f"""
            INSERT INTO symbol_history (
                symbol_history_id, security_id, symbol, exchange, series,
                valid_from, valid_to, source)
            SELECT ROW_NUMBER() OVER (ORDER BY sm.security_id, i.symbol),
                   sm.security_id, UPPER(TRIM(i.symbol)), 'NSE', NULL,
                   COALESCE(COALESCE(try_strptime(i.first_date,'%Y-%m-%d'),try_strptime(i.first_date,'%d-%b-%Y'))::DATE, DATE '1990-01-01'),
                   COALESCE(try_strptime(i.last_date,'%Y-%m-%d'),try_strptime(i.last_date,'%d-%b-%Y'))::DATE,
                   'v1seed:isin_master'
            FROM read_parquet('{im}') i
            JOIN security_master sm ON sm.isin = UPPER(TRIM(i.isin))
        """)

        rep = BuildReport(
            securities=con.execute("SELECT COUNT(*) FROM security_master").fetchone()[0],
            symbol_rows=con.execute("SELECT COUNT(*) FROM symbol_history").fetchone()[0],
            reused_symbols=con.execute(
                "SELECT COUNT(*) FROM (SELECT symbol FROM symbol_history"
                " GROUP BY 1 HAVING COUNT(DISTINCT security_id) > 1)").fetchone()[0],
            renamed_isins=con.execute(
                "SELECT COUNT(*) FROM (SELECT security_id FROM symbol_history"
                " GROUP BY 1 HAVING COUNT(DISTINCT symbol) > 1)").fetchone()[0],
        )
    finally:
        con.close()

    # Lineage to the master it was derived from. Without this the security
    # master is a root node, and "where did this identity come from?" has no
    # answer in the graph.
    from src.common.hashing import hash_file

    src_hash = hash_file(im)
    prov.register(
        prov.Artefact(src_hash, "SOURCE", "v1seed:isin_master", PRODUCED_BY,
                      params={"note": "two datasets concatenated; date format "
                                      "predicts source (2,528 ISO / 1,207 DD-MON)"}),
        env=env,
    )
    prov.register(
        prov.Artefact(
            prov.hash_params({"securities": rep.securities, "symbols": rep.symbol_rows,
                              "source": "v1seed:isin_master"}),
            "TABLE", "warehouse:security_master", PRODUCED_BY,
            row_count=rep.securities, params={"reused_symbols": rep.reused_symbols}),
        parents=[(src_hash, "input")],
        env=env,
    )
    return rep


RESOLVE_SQL = """
CREATE OR REPLACE VIEW deal_resolution AS
WITH d AS (
    SELECT r.raw_deal_id, UPPER(TRIM(r.symbol_raw)) AS sym, r.trade_date
    FROM institutional_deals_raw r
),
-- Every candidate security that ever held this ticker, scored by how well its
-- validity window fits the trade date. Point-in-time: 0 means the window
-- actually covers the date.
cand AS (
    SELECT d.raw_deal_id, d.sym, d.trade_date, h.security_id,
           CASE WHEN d.trade_date >= h.valid_from
                 AND (h.valid_to IS NULL OR d.trade_date <= h.valid_to)
                THEN 0
                WHEN d.trade_date < h.valid_from
                THEN date_diff('day', d.trade_date, h.valid_from)
                ELSE date_diff('day', h.valid_to, d.trade_date) END AS gap_days
    FROM d JOIN symbol_history h ON h.symbol = d.sym
),
best AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY raw_deal_id ORDER BY gap_days, security_id) AS rn,
           COUNT(*) FILTER (WHERE gap_days = 0) OVER (PARTITION BY raw_deal_id) AS n_valid
    FROM cand
)
SELECT d.raw_deal_id, d.sym AS symbol_raw, d.trade_date,
       b.security_id,
       CASE
           WHEN b.security_id IS NULL THEN NULL
           WHEN b.n_valid = 1 AND b.gap_days = 0 THEN 'HIGH'
           WHEN b.n_valid > 1  AND b.gap_days = 0 THEN 'LOW'
           ELSE 'MEDIUM'
       END AS confidence,
       CASE
           WHEN b.security_id IS NOT NULL THEN NULL
           WHEN s.symbol IS NULL THEN 'UNCOVERED'
           ELSE 'UNRESOLVED'
       END AS failure
FROM d
LEFT JOIN best b ON b.raw_deal_id = d.raw_deal_id AND b.rn = 1
LEFT JOIN (SELECT DISTINCT UPPER(TRIM(symbol)) AS symbol FROM read_parquet('{spine}')) s
       ON s.symbol = d.sym
"""


def resolve_all(env: str | None = None) -> dict:
    """Resolve every raw deal row and report the rates the Phase 3 gate needs."""
    con = duckdb.connect(str(research_db(env)))
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    try:
        con.execute(RESOLVE_SQL.format(spine=spine))
        total = con.execute("SELECT COUNT(*) FROM deal_resolution").fetchone()[0]
        rows = con.execute(
            "SELECT COALESCE(confidence, failure) AS k, COUNT(*) FROM deal_resolution"
            " GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    finally:
        con.close()
    return {"total": total, "breakdown": dict(rows)}


def main() -> int:
    print("IDENTITY LAYER (Plan 1 §6)")
    rep = build()
    print(rep.render())
    print("\nRESOLUTION over institutional_deals_raw")
    r = resolve_all()
    total = r["total"]
    for k, n in r["breakdown"].items():
        print(f"  {str(k):<12} {n:>8,}  {n / total:>6.2%}")
    unresolved = r["breakdown"].get("UNRESOLVED", 0)
    uncovered = r["breakdown"].get("UNCOVERED", 0)
    print(f"\n  Phase 3 gate: unresolved rate < 5%")
    print(f"    unresolved (a symbol we simply cannot place) {unresolved / total:>7.2%}")
    print(f"    uncovered  (no price series either, 0032)    {uncovered / total:>7.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
