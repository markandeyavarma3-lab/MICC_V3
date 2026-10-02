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
from src.common.paths import COLLECTED, SEED, research_db, warehouse_dir
from src.governance import provenance as prov

PRODUCED_BY = "src.identity.master:build"

#: A security is dead if it has not traded for this long before the spine ends.
#: universe.yml `delisting.stale_sessions_to_declare_dead`.
STALE_SESSIONS = 20

#: The full-bhavcopy listing history (src/ingest/listing_history.py).
LISTING = COLLECTED / "listing" / "series_presence.parquet"

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
        # READ BEFORE DESTROYING. A failed rebuild must leave the previous
        # state intact.
        #
        # On 2026-09-02 the INSERT below died on a corrupt spine partition
        # AFTER these two DELETEs had run. DuckDB autocommits, so the deletes
        # stood: security_master went to 0 rows, symbol_history to 0, and
        # institutional_deals_clean followed to 0 on the next mart build. A
        # transient read error in one upstream file emptied three tables.
        #
        # NOT a transaction: security_master and symbol_history are joined by a
        # foreign key, and DuckDB refuses the delete inside one. So the spine is
        # read into a temp table FIRST. If a partition is unreadable this raises
        # here, with both tables still populated, which is the property that
        # matters. See decision 0049.
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE _spine_symbols AS"
            f" SELECT DISTINCT symbol FROM read_parquet('{spine}')"
        )
        # The exit classification reads the spine, the listing history and
        # the two reason lists — all BEFORE the deletes, for the same reason.
        exit_inputs(con)
        con.execute(EXIT_SQL.format(im=im, spine=spine, listing=_listing_src(),
                                    stale=STALE_SESSIONS - 1,
                                    first_date=_date("first_date"),
                                    last_date=_date("last_date")))
        clear_for_rebuild(con)

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
            ids AS (SELECT isin, ROW_NUMBER() OVER (ORDER BY isin) AS id FROM ranked WHERE rn = 1)
            SELECT
                i.id,
                r.isin, r.symbol, COALESCE(r.company, r.symbol),
                r.first_date,
                -- Delisting is DETECTED from the last observed trade under any of
                -- the ISIN's symbols, never assumed from is_active, and only once
                -- it is STALE_SESSIONS old (universe.yml). See EXIT_SQL.
                CASE WHEN x.stopped THEN x.eq_last END,
                x.reason,
                CASE WHEN x.eq_last IS NULL THEN 'SUSPENDED'
                     WHEN x.reason = 'ISIN_CHANGE' THEN 'MERGED'
                     WHEN x.stopped THEN 'DELISTED'
                     ELSE 'ACTIVE' END,
                (SELECT s.id FROM ids s WHERE s.isin = x.successor_isin),
                'v1seed:isin_master',
                CASE WHEN r.first_date IS NOT NULL AND x.eq_last IS NOT NULL
                     THEN 'HIGH' ELSE 'MEDIUM' END
            FROM ranked r
            JOIN ids i ON i.isin = r.isin
            LEFT JOIN _exit x ON x.isin = r.isin
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


#: Plan 1 step 3.3 and universe.yml `delisting`. Why each security that left the
#: EQ price universe left it. Built into temp table `_exit` (isin, eq_last,
#: any_last, reason) BEFORE security_master is inserted, so status and reason
#: are written once, never updated under the foreign keys.
#:
#:   eq_last   the last EQ-spine session under ANY of the ISIN's symbols. The
#:             first version joined only the canonical (longest-held) symbol,
#:             so a renamed company was DELISTED on its rename date: 106 of
#:             1,041 DELISTED rows on 2026-10-01 were still trading.
#:   any_last  the last session in ANY series (`collected:listing`, the full
#:             bhavcopy 2005 -> now), matched by ISIN, and also by symbol where
#:             the symbol was never held by another ISIN — which is what finds
#:             a fund unit whose ISIN changed at a split (GOLDBEES).
#:
#: A recycled ticker is the trap in both joins: the old company must not borrow
#: the new one's trades. So a symbol held by more than one ISIN is counted only
#: up to that ISIN's own last_date for it (+5 days), while a symbol held by one
#: ISIN is counted throughout — its isin_master last_date is often the export
#: date, and windowing on it would kill every active company.
#:
#: reason, first match wins:
#:   ISIN_CHANGE    the same symbol continued under a new ISIN (a face-value
#:                  split, usually): status MERGED, merged_into_id the new one.
#:   LEFT_UNIVERSE  still trading on NSE in some series within the last 30 days
#:                  — moved to BE/BZ surveillance, or a fund unit (0040). Not a
#:                  delisting at all; the research universe is EQ only (0045).
#:   ACQUISITION / SUSPENSION   NSE's delisted.csv (src/archive/delisted.py),
#:                  any of the ISIN's symbols, delisted within 400 days of the
#:                  exit — a reused ticker's old delisting must not match.
#:   SUSPENSION     BSE's scrip master says Suspended for the ISIN.
#:   UNKNOWN        nothing says. MERGER is never assigned: universe.yml
#:                  requires a merged_into_id link, and no source names the
#:                  acquirer of a company absorbed by another.
#:
#: STATUS describes the EQ price universe the research reads (DELISTED = no
#: longer in it); REASON says what happened at the exchange. LEFT_UNIVERSE is
#: DELISTED from the universe while still listed on NSE.
EXIT_SQL = """
CREATE OR REPLACE TEMP TABLE _exit AS
WITH syms AS (
    SELECT UPPER(TRIM(isin)) AS isin, UPPER(TRIM(symbol)) AS symbol,
           MIN({first_date}) AS vf, MAX({last_date}) AS vt
    FROM read_parquet('{im}') WHERE isin IS NOT NULL AND symbol IS NOT NULL
    GROUP BY 1, 2
),
-- Only a holder that a LATER holder replaced is capped at its own last date;
-- the current holder of a reused ticker keeps every trade since.
capped AS (
    SELECT a.isin, a.symbol, a.vt FROM syms a
    WHERE a.vt IS NOT NULL AND EXISTS (
        SELECT 1 FROM syms b WHERE b.symbol = a.symbol AND b.isin <> a.isin
          AND b.vf > COALESCE(a.vf, DATE '1990-01-01'))
),
reused AS (SELECT symbol FROM syms GROUP BY 1 HAVING COUNT(DISTINCT isin) > 1),
eq AS (
    SELECT UPPER(TRIM(symbol)) AS symbol, MAX(CAST(date AS DATE)) AS last_d
    FROM read_parquet('{spine}') GROUP BY 1
),
eq_dates AS (
    SELECT UPPER(TRIM(symbol)) AS symbol, CAST(date AS DATE) AS d
    FROM read_parquet('{spine}')
    WHERE UPPER(TRIM(symbol)) IN (SELECT symbol FROM reused)
),
eq_last AS (
    SELECT s.isin, MAX(e.last_d) AS eq_last
    FROM syms s JOIN eq e ON e.symbol = s.symbol
    WHERE s.symbol NOT IN (SELECT symbol FROM reused)
    GROUP BY 1
    UNION ALL
    SELECT s.isin, MAX(d.d)
    FROM syms s JOIN eq_dates d ON d.symbol = s.symbol
    LEFT JOIN capped c ON c.isin = s.isin AND c.symbol = s.symbol
    WHERE c.vt IS NULL OR d.d <= c.vt + INTERVAL 5 DAY
    GROUP BY 1
),
listing AS ({listing}),
any_last AS (
    SELECT isin, MAX(last_date) AS any_last FROM listing WHERE isin <> '' GROUP BY 1
    UNION ALL
    SELECT s.isin, MAX(l.last_date)
    FROM syms s JOIN listing l ON l.symbol = s.symbol
    WHERE s.symbol NOT IN (SELECT symbol FROM reused)
    GROUP BY 1
),
per AS (
    SELECT s.isin,
           (SELECT MAX(eq_last) FROM eq_last x WHERE x.isin = s.isin) AS eq_last,
           (SELECT MAX(any_last) FROM any_last a WHERE a.isin = s.isin) AS any_last
    FROM (SELECT DISTINCT isin FROM syms) s
),
sessions AS (SELECT DISTINCT CAST(date AS DATE) AS d FROM read_parquet('{spine}')),
dead_line AS (SELECT d FROM sessions ORDER BY d DESC LIMIT 1 OFFSET {stale}),
listing_end AS (SELECT MAX(last_date) AS e FROM listing),
nse AS (
    SELECT DISTINCT s.isin, n.reason, n.delisted_on
    FROM syms s JOIN _nse_delisted n ON n.symbol = s.symbol
),
-- The same symbol carried on, without a break, under a NEW ISIN that starts
-- within 60 days of this one's last trade and outlived it: a face-value split
-- or similar.
-- GSFC 2012, FEDERALBNK 2013, INDNIPPON 2018 — 214 on 2026-10-01.
successor AS (
    SELECT a.isin, MIN(b.isin) AS successor_isin
    FROM syms a JOIN syms b ON b.symbol = a.symbol AND b.isin <> a.isin
    JOIN per pa ON pa.isin = a.isin
    JOIN per pb ON pb.isin = b.isin
    WHERE pb.eq_last > pa.eq_last
      AND b.vf BETWEEN pa.eq_last - INTERVAL 60 DAY AND pa.eq_last + INTERVAL 60 DAY
      -- AND THE SYMBOL NEVER STOPPED. isin_master's first_date is not
      -- day-accurate (real splits show 23-56 days), so the window above
      -- cannot tell a split from a recycled ticker taken up a month later.
      -- Continuity can: across a split the symbol trades again within days.
      AND EXISTS (SELECT 1 FROM eq_dates d WHERE d.symbol = a.symbol
                  AND d.d > pa.eq_last AND d.d <= pa.eq_last + INTERVAL 10 DAY)
    GROUP BY 1
)
SELECT p.isin, p.eq_last, p.any_last, sc.successor_isin,
       p.eq_last IS NOT NULL AND p.eq_last < (SELECT d FROM dead_line) AS stopped,
       CASE
         WHEN p.eq_last IS NULL OR p.eq_last >= (SELECT d FROM dead_line) THEN NULL
         WHEN sc.successor_isin IS NOT NULL THEN 'ISIN_CHANGE'
         WHEN p.any_last >= (SELECT e FROM listing_end) - INTERVAL 30 DAY THEN 'LEFT_UNIVERSE'
         WHEN (SELECT MIN(reason) FROM nse n WHERE n.isin = p.isin AND n.reason IS NOT NULL
                 AND abs(date_diff('day', n.delisted_on,
                                   GREATEST(p.eq_last, COALESCE(p.any_last, p.eq_last)))) <= 400)
              IS NOT NULL
           THEN (SELECT MIN(reason) FROM nse n WHERE n.isin = p.isin AND n.reason IS NOT NULL
                   AND abs(date_diff('day', n.delisted_on,
                                     GREATEST(p.eq_last, COALESCE(p.any_last, p.eq_last)))) <= 400)
         WHEN EXISTS (SELECT 1 FROM _bse b WHERE b.isin = p.isin AND b.listing_status = 'Suspended')
           THEN 'SUSPENSION'
         ELSE 'UNKNOWN'
       END AS reason
FROM per p
LEFT JOIN successor sc ON sc.isin = p.isin
"""


def _listing_src() -> str:
    """The listing history, or an empty relation of its shape. Without it every
    stopped security falls through to the list-based reasons or UNKNOWN —
    worse, but never a failed identity stage."""
    if LISTING.exists():
        return f"SELECT * FROM read_parquet('{LISTING}')"
    return ("SELECT NULL::VARCHAR AS symbol, NULL::VARCHAR AS series, NULL::VARCHAR AS isin,"
            " NULL::DATE AS first_date, NULL::DATE AS last_date, NULL::INTEGER AS sessions"
            " WHERE FALSE")


def exit_inputs(con: duckdb.DuckDBPyConnection) -> None:
    """Load the two small reason sources into temp tables `_nse_delisted`
    (symbol, reason, delisted_on) and `_bse` (isin, listing_status). Missing
    sources load empty: a reason that cannot be looked up is UNKNOWN, never
    an error that stops the identity stage."""
    from src.archive import delisted

    con.execute("CREATE OR REPLACE TEMP TABLE _nse_delisted"
                " (symbol VARCHAR, reason VARCHAR, delisted_on DATE)")
    rows = [(r["symbol"], r["reason"], r["delisted_on"] or None) for r in delisted.latest()]
    if rows:
        con.executemany("INSERT INTO _nse_delisted VALUES (?, ?, CAST(? AS DATE))", rows)
    bse = SEED / "bse_scrip_master.parquet"
    if bse.exists():
        con.execute(f"CREATE OR REPLACE TEMP TABLE _bse AS SELECT UPPER(TRIM(isin)) AS isin,"
                    f" listing_status FROM read_parquet('{bse}')")
    else:
        con.execute("CREATE OR REPLACE TEMP TABLE _bse (isin VARCHAR, listing_status VARCHAR)")


def clear_for_rebuild(con: duckdb.DuckDBPyConnection) -> None:
    """Empty security_master and everything that references it, children first.

    DuckDB enforces the foreign keys, so deleting a master row that a child
    still points at is refused — and a refused rebuild here fails the identity
    stage every night and freezes the mart behind it, which is how
    deal_forward_outcomes froze the mart for five days (0055).
    `promoter_entities` is derived from security_master by
    `src/identity/promoters.py`, which runs straight after this stage and
    rebuilds it whole, so emptying it here loses nothing.
    """
    con.execute("DELETE FROM promoter_entities")
    con.execute("DELETE FROM symbol_history")
    con.execute("DELETE FROM security_master")


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
    print("\n  Phase 3 gate: unresolved rate < 5%")
    print(f"    unresolved (a symbol we simply cannot place) {unresolved / total:>7.2%}")
    print(f"    uncovered  (no price series either, 0032)    {uncovered / total:>7.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
