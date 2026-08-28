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


CLEAN_VERSION = "1.1.0"   # 1.1.0 adds the TOO_LARGE participation ceiling
PRODUCED_BY = "src.mart.clean:build"


@dataclass
class CleanReport:
    rows: int = 0
    eligible: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    by_identity: dict[str, int] = field(default_factory=dict)
    by_timing: dict[str, int] = field(default_factory=dict)

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
                CASE WHEN h.participant IS NOT NULL THEN TRUE ELSE FALSE END AS is_hft
            FROM institutional_deals_raw r
            JOIN deal_source_files f USING (source_file_id)
            LEFT JOIN deal_resolution dr ON dr.raw_deal_id = r.raw_deal_id
            LEFT JOIN cal c ON c.d = r.trade_date
            LEFT JOIN adv a ON a.symbol = UPPER(TRIM(r.symbol_raw)) AND a.d = r.trade_date
            LEFT JOIN csd cs ON cs.participant = UPPER(TRIM(r.client_name_raw))
                            AND cs.symbol = UPPER(TRIM(r.symbol_raw))
                            AND cs.trade_date = r.trade_date
            LEFT JOIN hft h ON h.participant = UPPER(TRIM(r.client_name_raw))
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
            FALSE,   -- five_day_round_trip: not yet computed
            FALSE,   -- internal_transfer: needs participant identity
            FALSE,   -- promoter_related: needs SHP, Phase 3.11
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

        # Working views are dropped: they are build scaffolding, and leaving
        # them in a persistent database means a stale `cal` can outlive a spine
        # rebuild and silently answer with the old calendar.
        for v in ("cal", "adv", "csd", "hft"):
            con.execute(f"DROP VIEW IF EXISTS {v}")
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
                " ('warehouse:institutional_deals_raw','warehouse:security_master')"
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
    return CleanReport(rows, elig, by_reason, by_identity, by_timing)


def main() -> int:
    print("CLEAN MART (Phase 4) — zero silent drops")
    r = build()
    print(r.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
