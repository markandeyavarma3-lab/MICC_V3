"""clean.py — institutional_deals_clean. Phase 4, and the end of the dead end.

WHAT THIS FINALLY CONNECTS. Until now the pipeline ran

    archive -> parse -> land -> X

with nothing reading the landed rows, while `eligibility.py` read the seed
parquet directly and bypassed the archive, the identity layer and the provenance
DAG. Every research number produced that way — including the twelve-month result
decision 0034 rests on — skipped its own governance.

This is the join that ends it: landed rows + point-in-time identity + the
observed trading calendar + the eligibility rules, into one table that studies
read instead of the parquet.

ZERO SILENT DROPS, which is Phase 4's gate verbatim: *"every clean deal either
resolves to a security or carries an explicit failure status."* So **every one of
the 236,491 raw rows produces a clean row.** Ineligible ones carry
`eligible_for_research = false` and a written `ineligibility_reason`. Nothing is
filtered away by a WHERE clause, because a row that vanishes cannot be counted,
and an exclusion nobody can count is an exclusion nobody can audit.

AVAILABLE_FROM, AND WHY IT HAS TWO CONFIDENCE GRADES. Owner decision 2026-08-24:
the conservative bound is the next session's open, at LOW confidence where
publication was never observed.

  - **Live-collected rows** (parser 1.0.0) were seen in the archive on the
    evening of T, earliest confirmed 20:48 IST, which is after that session's
    close and before the next session's 09:15 open. Availability by T+1 open is
    therefore OBSERVED, and those rows carry HIGH.
  - **Seed rows** (parser v1seed) have no observation and none can be obtained.
    They carry LOW, and any study whose claim depends on timing must report how
    much of its sample is LOW.

CONFIDENCE ON IDENTITY IS SEPARATE AND ALSO KEPT. Owner decision 2026-08-24 chose
to accept HIGH, MEDIUM and LOW resolutions rather than only provable ones. The
1.7% graded LOW are the recycled-ticker cases — several securities held that
symbol on that date — which is precisely where a wrong match would attribute one
company's deal to another company's prices. They are included as instructed and
the grade is stored per row, so a study can require better and a sensitivity run
can measure what the choice cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import duckdb
import yaml

from src.common.paths import CONFIGS, research_db, warehouse_dir
from src.governance import provenance as prov
from src.identity.master import RESOLVE_SQL
from src.mart.eligibility import Thresholds, spec


def participation_ceiling() -> float:
    """The largest position buildable, as a multiple of ADV20.

    Plan 2 §4.4: participation is capped at a fraction of ADV per session, and an
    order that cannot be built inside `max_sessions_to_build` is marked TOO_LARGE
    and excluded with the reason recorded. costs.yml sets 10% per session over at
    most 5 sessions, so 50% of ADV20 is the ceiling.

    THIS WAS MISSING UNTIL 2026-08-26 and it mattered: the mart had a size FLOOR
    (0.5% of ADV20, so a threshold-scraper is not an event) and NO CEILING, so
    14,747 of 20,489 eligible events — 72% — were positions nobody could
    actually build. One traced row was 204x ADV. An event that cannot be
    established is not a tradable signal, and including it inflates the sample
    with the most extreme returns in the corpus.

    Derived from config rather than hard-coded, so the 3x3 sensitivity the cost
    model already demands can move it.
    """
    c = yaml.safe_load((CONFIGS / "costs.yml").read_text())["participation"]
    return float(c["base_cap_pct_adv"]) * int(c["max_sessions_to_build"])


CLEAN_VERSION = "1.2.0"   # 1.1.0 the TOO_LARGE ceiling; 1.2.0 the promoter flags
PRODUCED_BY = "src.mart.clean:build"


#: Plan 1 §6.6 / §7.1. Three facts per resolved deal, against the point-in-time
#: promoter list (`src/identity/promoters.py`):
#:   promoter_related   the participant is a promoter of THIS security on the
#:                      trade date, by exact normalised name
#:   internal_transfer  a promoter-related deal with a DIFFERENT promoter of
#:                      the same security on the opposite side that session —
#:                      the owner moving shares between its own hands
#:   list_in_force      the security had any promoter list valid on that date,
#:                      i.e. the question could be asked at all
#: The flags do NOT change eligibility. Whether a study excludes promoter deals
#: is a registration decision, and moving 1,435 sells out of the eligible set
#: from inside the mart would change every study's sample without one.
PROMOTER_FLAGS_SQL = """
CREATE OR REPLACE TEMP TABLE pflag AS
WITH d AS (
    SELECT r.raw_deal_id, r.trade_date, dr.security_id, n.norm,
           CASE WHEN UPPER(r.side_raw) LIKE 'B%' THEN 'BUY'
                WHEN UPPER(r.side_raw) LIKE 'S%' THEN 'SELL' END AS side
    FROM institutional_deals_raw r
    JOIN deal_resolution dr ON dr.raw_deal_id = r.raw_deal_id
    LEFT JOIN pnorm n ON n.raw = r.client_name_raw
    WHERE dr.security_id IS NOT NULL
),
valid AS (
    SELECT d.raw_deal_id, d.security_id, d.trade_date, d.side, d.norm,
           pe.normalized_name AS promoter
    FROM d JOIN promoter_entities pe
      ON pe.security_id = d.security_id
     AND d.trade_date >= pe.valid_from
     AND (pe.valid_to IS NULL OR d.trade_date < pe.valid_to)
),
known AS (SELECT DISTINCT raw_deal_id FROM valid),
prom AS (SELECT DISTINCT raw_deal_id, security_id, trade_date, side, norm
         FROM valid WHERE norm = promoter),
internal AS (
    SELECT DISTINCT a.raw_deal_id FROM prom a JOIN prom b
      ON a.security_id = b.security_id AND a.trade_date = b.trade_date
     AND a.side <> b.side AND a.norm <> b.norm
)
SELECT d.raw_deal_id,
       p.raw_deal_id IS NOT NULL AS promoter_related,
       i.raw_deal_id IS NOT NULL AS internal_transfer,
       k.raw_deal_id IS NOT NULL AS list_in_force
FROM d
LEFT JOIN (SELECT DISTINCT raw_deal_id FROM prom) p ON p.raw_deal_id = d.raw_deal_id
LEFT JOIN internal i ON i.raw_deal_id = d.raw_deal_id
LEFT JOIN known k ON k.raw_deal_id = d.raw_deal_id
"""


#: Plan 1 §7.1, owner decision Q23: a round trip completed within five
#: SESSIONS, alongside the same-day one. A participant-stock-day leg is
#: flagged when the same participant traded the opposite side of the same
#: stock on a DIFFERENT session no more than this many sessions away, either
#: direction. Same participant key and symbol key as the same-day flag
#: (`csd`), so the two flags describe one notion at two horizons.
#:
#: HALF OF THIS IS HINDSIGHT, SO IT IS A FLAG AND NEVER AN ELIGIBILITY RULE.
#: A buy on Monday sold back on Thursday is flagged on MONDAY's row, from a
#: deal published on Thursday. Excluding Monday's buy from a study because of
#: it removes events using information nobody had at entry — a look-ahead that
#: flatters any "institutional buys predict returns" result by deleting the
#: buys that were quickly undone. A study may use this flag to describe its
#: sample or run a labelled sensitivity, not to choose it. The same-day flag
#: does not have the problem: both legs are disclosed the same evening.
ROUND_TRIP_SESSIONS = 5

FIVE_DAY_SQL = """
CREATE OR REPLACE TEMP TABLE rt5 AS
WITH sess AS (SELECT d, ROW_NUMBER() OVER (ORDER BY d) AS i FROM (SELECT DISTINCT d FROM cal)),
legs AS (
    SELECT c.participant, c.symbol, c.trade_date, c.bought, c.sold, s.i
    FROM csd c JOIN sess s ON s.d = c.trade_date
),
pairs AS (
    SELECT a.participant, a.symbol, a.trade_date,
           a.bought = 1 AND b.sold = 1 AS buy_undone,
           a.sold = 1 AND b.bought = 1 AS sell_undone
    FROM legs a JOIN legs b
      ON b.participant = a.participant AND b.symbol = a.symbol
     AND b.i <> a.i AND abs(b.i - a.i) <= {n}
)
-- One row per (leg, side): a day with buys AND sells can be undone both ways,
-- and the per-row join in build() reads only its own side.
SELECT DISTINCT participant, symbol, trade_date, 'BUY' AS side FROM pairs WHERE buy_undone
UNION
SELECT DISTINCT participant, symbol, trade_date, 'SELL' AS side FROM pairs WHERE sell_undone
"""


def five_day_flags(con: duckdb.DuckDBPyConnection, n: int = ROUND_TRIP_SESSIONS) -> None:
    """Build temp table `rt5` (participant, symbol, trade_date, side) from the
    `csd` and `cal` views: every leg with an opposite leg <= n sessions away."""
    con.execute(FIVE_DAY_SQL.format(n=int(n)))


def promoter_flags(con: duckdb.DuckDBPyConnection) -> None:
    """Build temp table `pflag` (raw_deal_id -> the three facts above).

    Participant names are normalised in Python with the one shared rule
    (`entity_names.normalize`) — a second SQL copy of it would drift — once
    per DISTINCT name, not per row.
    """
    from src.research.entity_names import normalize

    names = [r[0] for r in con.execute(
        "SELECT DISTINCT client_name_raw FROM institutional_deals_raw"
        " WHERE client_name_raw IS NOT NULL").fetchall()]
    con.execute("CREATE OR REPLACE TEMP TABLE pnorm (raw VARCHAR, norm VARCHAR)")
    con.executemany("INSERT INTO pnorm VALUES (?, ?)", [(n, normalize(n)) for n in names])
    con.execute(PROMOTER_FLAGS_SQL)


@dataclass
class CleanReport:
    rows: int = 0
    eligible: int = 0
    #: Outcome rows a rebuild invalidated. Reported, never silent — see build().
    derived_invalidated: int = 0

    by_reason: dict[str, int] = field(default_factory=dict)
    by_identity: dict[str, int] = field(default_factory=dict)
    by_timing: dict[str, int] = field(default_factory=dict)
    #: Plan 1 §7.1 promoter flags; see PROMOTER_FLAGS_SQL.
    promoter_related: int = 0
    promoter_related_eligible: int = 0
    internal_transfer: int = 0
    list_in_force: int = 0
    promoter_entities: int = 0
    #: Plan 1 §7.1 / Q23; see ROUND_TRIP_SESSIONS. A flag, never a filter.
    five_day: int = 0
    five_day_eligible: int = 0

    def render(self) -> str:
        out = [f"  clean rows        {self.rows:>8,}",
               f"  eligible          {self.eligible:>8,}  "
               f"({self.eligible / self.rows:.2%} of the corpus)" if self.rows else ""]
        out.append("\n  ineligible, by reason (nothing is silently dropped):")
        for k, v in sorted(self.by_reason.items(), key=lambda x: -x[1]):
            out.append(f"    {k:<34} {v:>8,}")
        out.append("\n  identity confidence, eligible rows only:")
        for k, v in sorted(self.by_identity.items(), key=lambda x: -x[1]):
            out.append(f"    {k:<34} {v:>8,}")
        out.append("\n  available_from confidence:")
        for k, v in sorted(self.by_timing.items(), key=lambda x: -x[1]):
            out.append(f"    {k:<34} {v:>8,}")
        out.append("\n  five-session round trips (Q23; hindsight, so a flag and not a filter):")
        out += [f"    {'five_day_round_trip':<34} {self.five_day:>8,}",
                f"    {'  of which eligible':<34} {self.five_day_eligible:>8,}"]
        out.append("\n  promoter flags (Plan 1 §6.6; they do not change eligibility):")
        if not self.promoter_entities:
            # FALSE BY ABSENCE IS NOT FALSE BY MEASUREMENT. If the promoters
            # stage failed, every flag reads FALSE and looks like a finding.
            out.append("    promoter_entities HOLDS 0 ROWS — every flag below is FALSE for"
                       " want of a list, not because it was checked."
                       " Run: python -m src.identity.promoters")
        out += [f"    {'a promoter list was in force':<34} {self.list_in_force:>8,}"
                + (f"  ({self.list_in_force / self.rows:.1%} of rows)" if self.rows else ""),
                f"    {'promoter_related':<34} {self.promoter_related:>8,}",
                f"    {'  of which eligible':<34} {self.promoter_related_eligible:>8,}",
                f"    {'internal_transfer':<34} {self.internal_transfer:>8,}"]
        if self.derived_invalidated:
            out.append(
                f"\n  INVALIDATED {self.derived_invalidated:,} deal_forward_outcomes row(s): "
                f"a rebuilt mart makes every derived outcome stale.\n"
                f"  Rebuild with:  python -m src.research.outcomes")
        return "\n".join(out)


def build(env: str | None = None, t: Thresholds | None = None) -> CleanReport:
    t = t or Thresholds.default()
    e = spec()["eligibility"]
    min_value = float(e["min_deal_value_inr"])
    min_adv = float(e["min_deal_value_to_adv20"])
    max_adv = participation_ceiling()

    db = research_db(env)
    con = duckdb.connect(str(db))
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    now = datetime.now(UTC).replace(tzinfo=None)

    try:
        con.execute(RESOLVE_SQL.format(spine=spine))

        # The observed trading calendar, as a table, so "next session" is a join
        # rather than 236,491 Python round-trips.
        con.execute(f"""
            CREATE OR REPLACE VIEW cal AS
            SELECT d, LEAD(d) OVER (ORDER BY d) AS next_d FROM (
                SELECT DISTINCT CAST(date AS DATE) d FROM read_parquet('{spine}'))
        """)
        con.execute(f"""
            CREATE OR REPLACE VIEW adv AS
            SELECT UPPER(TRIM(symbol)) AS symbol, CAST(date AS DATE) AS d,
                   median(close * volume) OVER (
                       PARTITION BY symbol ORDER BY date
                       ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS adv20
            FROM read_parquet('{spine}')
        """)

        # Round trips are a property of the PARTICIPANT-STOCK-DAY, not of a row:
        # a client that both bought and sold one name in one session ended flat,
        # whatever the row count. 54.8% of bulk client-stock-days are these.
        con.execute("""
            CREATE OR REPLACE VIEW csd AS
            SELECT UPPER(TRIM(client_name_raw)) AS participant,
                   UPPER(TRIM(symbol_raw)) AS symbol, trade_date,
                   MAX(CASE WHEN UPPER(side_raw) LIKE 'B%' THEN 1 ELSE 0 END) AS bought,
                   MAX(CASE WHEN UPPER(side_raw) LIKE 'S%' THEN 1 ELSE 0 END) AS sold
            FROM institutional_deals_raw GROUP BY 1,2,3
        """)
        con.execute(f"""
            CREATE OR REPLACE VIEW hft AS
            SELECT participant FROM (
                SELECT participant, COUNT(*) AS days,
                       SUM(CASE WHEN bought=1 AND sold=1 THEN 1 ELSE 0 END)*1.0/COUNT(*) AS ratio
                FROM csd GROUP BY 1)
            WHERE days >= {t.min_client_stock_days} AND ratio >= {t.roundtrip_ratio}
        """)
        five_day_flags(con)
        promoter_flags(con)

        # DERIVED OUTCOMES ARE INVALIDATED BY A REBUILD, AND THE FK ENFORCES IT.
        #
        # `deal_forward_outcomes` references institutional_deals_clean(deal_id).
        # While that table was empty the DELETE below succeeded; the moment step
        # 6.3 populated it on 2026-09-05, EVERY scheduled mart rebuild failed
        # with a foreign-key violation and the mart froze. The collector
        # reported mart=1 three times a day for five days and 767 collected
        # deals never reached the mart — the failure was loud and nothing acted
        # on it, which is this project's standing pattern wearing a new hat.
        #
        # Cascading is the correct treatment rather than a workaround: an
        # outcome is a forward return computed FROM a mart row, so a rebuilt
        # mart makes every one of them stale by construction. They are deleted
        # in FK order and the count is reported, because silently emptying a
        # 52,000-row table would be worse than the breakage it replaces.
        derived = con.execute(
            "SELECT COUNT(*) FROM deal_forward_outcomes").fetchone()[0]
        if derived:
            con.execute("DELETE FROM outcome_benchmark_returns")
            con.execute("DELETE FROM deal_forward_outcomes")

        con.execute("DELETE FROM institutional_deals_clean")
        con.execute(f"""
        INSERT INTO institutional_deals_clean
        WITH base AS (
            SELECT
                r.raw_deal_id, r.exchange, r.deal_type, r.trade_date,
                UPPER(TRIM(r.symbol_raw)) AS sym,
                UPPER(TRIM(r.client_name_raw)) AS participant,
                CASE WHEN UPPER(r.side_raw) LIKE 'B%' THEN 'BUY'
                     WHEN UPPER(r.side_raw) LIKE 'S%' THEN 'SELL' END AS side,
                TRY_CAST(r.quantity_raw AS DOUBLE) AS qty,
                TRY_CAST(r.deal_price_raw AS DOUBLE) AS price,
                f.parser_version,
                dr.security_id, dr.confidence AS id_conf, dr.failure,
                c.next_d AS entry_date,
                a.adv20,
                cs.bought, cs.sold,
                CASE WHEN h.participant IS NOT NULL THEN TRUE ELSE FALSE END AS is_hft,
                COALESCE(pf.promoter_related, FALSE) AS promoter_related,
                COALESCE(pf.internal_transfer, FALSE) AS internal_transfer,
                r5.participant IS NOT NULL AS five_day
            FROM institutional_deals_raw r
            JOIN deal_source_files f USING (source_file_id)
            LEFT JOIN deal_resolution dr ON dr.raw_deal_id = r.raw_deal_id
            LEFT JOIN cal c ON c.d = r.trade_date
            LEFT JOIN adv a ON a.symbol = UPPER(TRIM(r.symbol_raw)) AND a.d = r.trade_date
            LEFT JOIN csd cs ON cs.participant = UPPER(TRIM(r.client_name_raw))
                            AND cs.symbol = UPPER(TRIM(r.symbol_raw))
                            AND cs.trade_date = r.trade_date
            LEFT JOIN hft h ON h.participant = UPPER(TRIM(r.client_name_raw))
            LEFT JOIN pflag pf ON pf.raw_deal_id = r.raw_deal_id
            LEFT JOIN rt5 r5 ON r5.participant = UPPER(TRIM(r.client_name_raw))
                            AND r5.symbol = UPPER(TRIM(r.symbol_raw))
                            AND r5.trade_date = r.trade_date
                            AND r5.side = CASE WHEN UPPER(r.side_raw) LIKE 'B%' THEN 'BUY'
                                               WHEN UPPER(r.side_raw) LIKE 'S%' THEN 'SELL' END
        ),
        flagged AS (
            SELECT *,
                (bought = 1 AND sold = 1) AS round_trip,
                qty * price AS value_inr,
                CASE WHEN adv20 > 0 THEN (qty * price) / adv20 END AS v2adv,
                -- ONE reason per row, in priority order. A row excluded for three
                -- reasons is reported under the first that applies, so the
                -- exclusion table sums to the exclusion count.
                CASE
                    WHEN side IS NULL THEN 'unparseable side'
                    WHEN qty IS NULL OR price IS NULL THEN 'unparseable quantity or price'
                    WHEN failure = 'UNCOVERED' THEN 'uncovered symbol (0032)'
                    WHEN failure = 'UNRESOLVED' THEN 'unresolved symbol'
                    WHEN entry_date IS NULL THEN 'no next session in the data'
                    WHEN bought = 1 AND sold = 1 THEN 'same-day round trip'
                    WHEN is_hft THEN 'PROP_HFT participant'
                    WHEN side <> 'BUY' THEN 'not a buy (sells not yet studied)'
                    WHEN qty * price < {min_value} THEN 'below the value floor'
                    WHEN v2adv IS NULL OR v2adv < {min_adv} THEN 'below the ADV20 floor'
                    -- Plan 2 §4.4. A position needing more than
                    -- max_sessions_to_build at the participation cap cannot be
                    -- established, so it is not a tradable event however real
                    -- the disclosure was.
                    WHEN v2adv > {max_adv} THEN 'TOO_LARGE to build (Plan 2 §4.4)'
                END AS reason
            FROM base
        )
        SELECT
            ROW_NUMBER() OVER (ORDER BY raw_deal_id),
            raw_deal_id, security_id, NULL,
            trade_date,
            -- Public before the next session opens. That is OBSERVED for
            -- live-collected rows and ASSUMED for seed rows, and the confidence
            -- column is the only place that difference survives.
            CAST(COALESCE(entry_date, trade_date) AS TIMESTAMP),
            CASE WHEN parser_version LIKE 'v1seed%' THEN 'LOW' ELSE 'HIGH' END,
            COALESCE(entry_date, trade_date),
            exchange, deal_type, COALESCE(side, 'BUY'),
            CAST(COALESCE(qty, 0) AS BIGINT), COALESCE(price, 0.0),
            COALESCE(value_inr, 0.0), adv20, v2adv,
            NULL,
            COALESCE(round_trip, FALSE),
            -- Flag only: half of it is hindsight (see ROUND_TRIP_SESSIONS).
            five_day,
            internal_transfer,
            promoter_related,
            FALSE,
            COALESCE(failure = 'UNRESOLVED', FALSE),
            COALESCE(failure = 'UNCOVERED', FALSE),
            reason IS NULL,
            reason,
            '{CLEAN_VERSION}', '{now}'
        FROM flagged
        """)

        rows = con.execute("SELECT COUNT(*) FROM institutional_deals_clean").fetchone()[0]
        elig = con.execute(
            "SELECT COUNT(*) FROM institutional_deals_clean WHERE eligible_for_research"
        ).fetchone()[0]
        by_reason = dict(con.execute(
            "SELECT ineligibility_reason, COUNT(*) FROM institutional_deals_clean"
            " WHERE NOT eligible_for_research GROUP BY 1"
        ).fetchall())
        by_identity = dict(con.execute(
            "SELECT COALESCE(dr.confidence,'(none)'), COUNT(*)"
            " FROM institutional_deals_clean c"
            " JOIN deal_resolution dr ON dr.raw_deal_id = c.raw_deal_id"
            " WHERE c.eligible_for_research GROUP BY 1"
        ).fetchall())
        by_timing = dict(con.execute(
            "SELECT available_from_confidence, COUNT(*) FROM institutional_deals_clean"
            " GROUP BY 1"
        ).fetchall())
        prom = con.execute("""
            SELECT COUNT(*) FILTER (WHERE promoter_related_flag),
                   COUNT(*) FILTER (WHERE promoter_related_flag AND eligible_for_research),
                   COUNT(*) FILTER (WHERE internal_transfer_flag),
                   COUNT(*) FILTER (WHERE five_day_round_trip_flag),
                   COUNT(*) FILTER (WHERE five_day_round_trip_flag AND eligible_for_research)
            FROM institutional_deals_clean""").fetchone()
        in_force = con.execute("SELECT COUNT(*) FROM pflag WHERE list_in_force").fetchone()[0]
        n_entities = con.execute("SELECT COUNT(*) FROM promoter_entities").fetchone()[0]

        # Working views are dropped: they are build scaffolding, and leaving
        # them in a persistent database means a stale `cal` can outlive a spine
        # rebuild and silently answer with the old calendar.
        for v in ("cal", "adv", "csd", "hft"):
            con.execute(f"DROP VIEW IF EXISTS {v}")
        for t in ("pflag", "pnorm", "rt5"):
            con.execute(f"DROP TABLE IF EXISTS {t}")
    finally:
        con.close()

    import sqlite3

    from src.common.paths import governance_db

    # The inputs this mart was built from, so lineage can be walked. Found
    # 2026-08-26: institutional_deals_clean and security_master were both
    # registered with ZERO parent edges — the same dead end fixed for the landed
    # tables and then reintroduced in the two modules written after it.
    g = sqlite3.connect(governance_db(env))
    try:
        parents = [
            (r[0], "input")
            for r in g.execute(
                "SELECT artefact_hash FROM artefact WHERE logical_name IN"
                " ('warehouse:institutional_deals_raw','warehouse:security_master',"
                "  'warehouse:promoter_entities')"
            ).fetchall()
        ]
    finally:
        g.close()
    prov.register(
        prov.Artefact(
            prov.hash_params({"rows": rows, "eligible": elig, "version": CLEAN_VERSION,
                              "ceiling": participation_ceiling()}),
            "TABLE", "warehouse:institutional_deals_clean", PRODUCED_BY,
            row_count=rows,
            params={"clean_version": CLEAN_VERSION, "eligible": elig,
                    "participation_ceiling": participation_ceiling()}),
        parents=parents,
        env=env,
    )
    return CleanReport(rows, elig, derived, by_reason, by_identity, by_timing,
                       promoter_related=prom[0], promoter_related_eligible=prom[1],
                       internal_transfer=prom[2], list_in_force=in_force,
                       promoter_entities=n_entities,
                       five_day=prom[3], five_day_eligible=prom[4])


def main() -> int:
    print("CLEAN MART (Phase 4) — zero silent drops")
    r = build()
    print(r.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
