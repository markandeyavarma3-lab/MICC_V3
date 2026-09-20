"""outcomes.py — deal_forward_outcomes. Plan 3 step 6.3.

WHAT THIS CLOSES. `deal_forward_outcomes` and `outcome_benchmark_returns` have
existed as empty tables since the schema landed. Every study so far — 0038,
0043, 0044, 0046, 0050, 0051, 0052 — recomputed forward returns inline in its
own SQL, so nine horizons and six benchmarks were specified and one horizon
against one implicit benchmark was ever measured. This writes the table those
studies were supposed to read.

THE FOURTH EXIT REASON FINALLY HAS A DETECTOR.

Plan 2 §3.4 names four cases. 0052 built two of them (HORIZON, DELISTED),
declared MERGED undetectable, and had no way to find SUSPENDED at all. It turns
out the project has been *silently including* suspensions the whole time.

`measure._returns_sql` takes the exit as `LEAD(close, 252)` over a row index.
That is 252 TRADED ROWS, not 252 sessions. A name that stops trading for five
years and relists supplies its 252nd row years later, and the result is labelled
a twelve-month return. Measured on the EXPLORE sell population:

  * 37 of 1,145 events (3.2%) span more than 500 calendar days
  * 2 span more than 1,000; the worst is ATLASCYCLE at 3,506 days — 9.6 years
    carried as a twelve-month outcome, at -117.8% abnormal
  * those 37 average -51.4% against -29.6% for the other 1,108

So the published -30.30% is -29.59% once suspensions are excluded, a 0.71pp
distortion. That does NOT change any verdict — the effect is ~5x its bound
either way and 0050 already found no population powered — but a twelve-month
label on a 9.6-year holding period is wrong regardless of whether the wrongness
is convenient.

Here a window whose calendar span exceeds `_max_span_days` is `SUSPENDED`,
marked at the last price before the gap and excluded from the headline, exactly
as Plan 2 §3.4 specifies.

WHAT IS STILL NOT DETECTABLE. `MERGED`. `security_master.delisting_reason` is
UNKNOWN on every row because Plan 1 step 3.3 needs corporate actions that are
not collected, so a merger is priced as a delisting and overstates the effect.
Unchanged from 0052 and declared again here rather than assumed known.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb
import yaml

from src.common.paths import CONFIGS, research_db, warehouse_dir
from src.research import charmatch, costs

CALCULATION_VERSION = "6.3.0"

#: Plan 2 §3.4. Only DELISTED and SUSPENDED consume one; a HORIZON exit realises
#: a real price and carries NULL.
RECOVERY_FACTORS: tuple[float, ...] = (0.0, 0.25, 0.50)

#: Trading sessions per calendar year, used only to convert a session horizon
#: into the calendar span it OUGHT to occupy.
SESSIONS_PER_YEAR = 252.0


def research_spec() -> dict:
    return yaml.safe_load((CONFIGS / "research.yml").read_text())


def horizons() -> list[tuple[int, int | None]]:
    """The nine horizons, as (sessions, months). Read from research.yml.

    Plan 3 step 6.3 says "9 horizons". research.yml carries six session horizons
    and three month horizons, and `sessions_per_month` converts the second set —
    so the nine are derived here rather than restated as a literal that could
    disagree with the config it came from.
    """
    spec = research_spec()
    per_month = int(spec["power"]["sessions_per_month"]) if "power" in spec \
        else int(spec["sessions_per_month"])
    out: list[tuple[int, int | None]] = [(int(s), None)
                                         for s in spec["horizons_sessions"]]
    out += [(int(m) * per_month, int(m)) for m in spec["horizons_months"]]
    return out


def _max_span_days(sessions: int) -> float:
    """Delegates to `measure.max_span_days`.

    THE THRESHOLD LIVES IN ONE PLACE. This module defined its own copy of the
    arithmetic until 2026-09-05, while `measure._returns_sql` — the engine six
    study modules share — had no span check at all. Two definitions of the same
    rule is two rules, and the one that mattered more was the one that did not
    exist.
    """
    from src.research import measure

    return measure.max_span_days(sessions)


@dataclass
class BuildResult:
    horizon_rows: dict[str, int] = field(default_factory=dict)
    reasons: dict[str, int] = field(default_factory=dict)
    censored: int = 0
    outcomes: int = 0
    benchmarks: dict[str, int] = field(default_factory=dict)

    def render(self) -> str:
        out = [f"  wrote {self.outcomes:,} outcome row(s)"]
        for r, n in sorted(self.reasons.items(), key=lambda kv: -kv[1]):
            out.append(f"    {r:<10} {n:>7,}")
        out.append(f"    {'(censored)':<10} {self.censored:>7,}  no row written — "
                   f"the horizon runs past the data (0052)")
        return "\n".join(out)


def _events_sql() -> str:
    """The mart's own eligibility, applied once where it can be counted.

    Not re-derived here. `eligible_for_research` already encodes the size floor,
    the ADV fraction, the round-trip exclusion and the PROP_HFT exclusion, and a
    second implementation of any of those would be a second answer.
    """
    return """
        SELECT cl.deal_id, cl.trade_date, cl.gross_deal_value, cl.quantity,
               cl.adv20, cl.exchange,
               UPPER(TRIM(r.symbol_raw)) AS symbol
        FROM institutional_deals_clean cl
        JOIN institutional_deals_raw r USING (raw_deal_id)
        WHERE cl.eligible_for_research
    """


def _outcome_sql(spine: str, sessions: int, cutoff: str) -> str:
    """One horizon's outcomes, with the exit reason decided in SQL.

    ENTRY IS THE NEXT SESSION'S OPEN, never the event session's close — the
    disclosure publishes after that close (`research.yml` timing.no_same_day_close).
    Exit is the close `sessions` rows later, when that row is both present and
    close enough in calendar time to be the session it claims to be.
    """
    return f"""
    WITH px AS (
        SELECT symbol, CAST(date AS DATE) AS d, open, high, low, close,
               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date) AS i
        FROM read_parquet('{spine}')
        WHERE close > 0 AND open > 0 AND date <= '{cutoff}'
    ),
    lastrow AS (
        SELECT symbol, MAX(i) AS n, MAX(d) AS last_d FROM px GROUP BY 1
    ),
    lastpx AS (
        SELECT p.symbol, p.close AS last_close, p.d AS last_close_d
        FROM px p JOIN lastrow l ON l.symbol = p.symbol AND l.n = p.i
    ),
    spine_end AS (SELECT MAX(d) AS e FROM px),
    -- Leads over the FULL series, before any join to events. Joining first and
    -- windowing after partitions over event rows, which silently returns the
    -- next EVENT rather than the next session (0052).
    f AS (
        SELECT symbol, d, i,
               LEAD(open, 1) OVER w AS entry_px,
               LEAD(d, 1) OVER w AS entry_d,
               LEAD(close, {sessions}) OVER w AS exit_px,
               LEAD(d, {sessions}) OVER w AS exit_d,
               MAX(high) OVER (PARTITION BY symbol ORDER BY i
                   ROWS BETWEEN 1 FOLLOWING AND {sessions} FOLLOWING) AS win_high,
               MIN(low) OVER (PARTITION BY symbol ORDER BY i
                   ROWS BETWEEN 1 FOLLOWING AND {sessions} FOLLOWING) AS win_low
        FROM px WINDOW w AS (PARTITION BY symbol ORDER BY i)
    )
    SELECT e.deal_id, e.symbol, e.trade_date, e.gross_deal_value, e.quantity,
           e.adv20, e.exchange,
           f.entry_px, f.entry_d, f.exit_px, f.exit_d,
           f.win_high, f.win_low,
           lp.last_close, lp.last_close_d,
           CASE
             -- The window completed AND it took about as long as it should have.
             WHEN f.exit_d IS NOT NULL
                  AND date_diff('day', f.d, f.exit_d) <= {_max_span_days(sessions)}
               THEN 'HORIZON'
             -- The window completed on paper but spans a trading suspension.
             WHEN f.exit_d IS NOT NULL THEN 'SUSPENDED'
             -- No exit row, and the name is still trading: the horizon simply
             -- runs past the data. No outcome exists yet.
             WHEN lr.last_d >= (SELECT e FROM spine_end) - 10 THEN 'CENSORED'
             ELSE 'DELISTED'
           END AS exit_reason
    FROM ({_events_sql()}) e
    JOIN f  ON f.symbol = e.symbol AND f.d = e.trade_date
    JOIN lastrow lr ON lr.symbol = e.symbol
    JOIN lastpx  lp ON lp.symbol = e.symbol
    WHERE f.entry_px > 0
    """


def _cost_bps(con) -> dict[int, float]:
    """Round-trip cost in bps per deal, from the Plan 2 §4 model.

    Computed once per DEAL rather than once per outcome row: the statutory cost
    depends on the turnover and the date the trade happened, neither of which
    varies with the horizon. 5,937 deals rather than 53,433 rows.
    """
    rows = con.execute(
        f"SELECT deal_id, gross_deal_value, trade_date, exchange "
        f"FROM ({_events_sql()})").fetchall()
    out: dict[int, float] = {}
    for deal_id, turnover, on, exchange in rows:
        try:
            out[deal_id] = costs.round_trip_bps(
                float(turnover), on, exchange=exchange or "NSE")
        except Exception:
            # A fee schedule that does not cover the date is a real gap, not a
            # reason to invent a number. The row is written with a NULL net
            # return and outcome_complete_flag False.
            continue
    return out


def build(env: str | None = None, cutoff: str | None = None) -> BuildResult:
    from src.research import measure

    cutoff = cutoff or measure.REPRODUCIBILITY_HORIZON
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    con = duckdb.connect(str(research_db(env)))
    con.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false;")
    res = BuildResult()
    try:
        costs.load_fee_schedule(env)
        bps = _cost_bps(con)

        # IDEMPOTENT BY CALCULATION VERSION. Re-running must replace this
        # version's rows, not accumulate a second copy beside them — the UNIQUE
        # constraint carries recovery_factor, which is NULL on HORIZON rows, and
        # DuckDB treats NULLs as distinct so duplicates would NOT be rejected.
        con.execute("DELETE FROM outcome_benchmark_returns WHERE outcome_id IN "
                    "(SELECT outcome_id FROM deal_forward_outcomes "
                    " WHERE calculation_version = ?)", [CALCULATION_VERSION])
        con.execute("DELETE FROM deal_forward_outcomes WHERE calculation_version = ?",
                    [CALCULATION_VERSION])

        next_id = (con.execute("SELECT COALESCE(MAX(outcome_id), 0) "
                               "FROM deal_forward_outcomes").fetchone()[0]) + 1

        for sessions, months in horizons():
            label = f"{sessions}s" + (f" ({months}m)" if months else "")
            con.execute(f"CREATE OR REPLACE TEMP VIEW o AS "
                        f"{_outcome_sql(spine, sessions, cutoff)}")
            rows = con.execute("""
                SELECT deal_id, symbol, trade_date, entry_px, entry_d, exit_px,
                       exit_d, win_high, win_low, last_close, last_close_d,
                       exit_reason
                FROM o""").fetchall()

            out: list[tuple] = []
            for (deal_id, _sym, _td, entry, entry_d, exit_px, exit_d,
                 win_high, win_low, last_close, last_close_d, reason) in rows:
                res.reasons[reason] = res.reasons.get(reason, 0) + 1
                if reason == "CENSORED":
                    res.censored += 1
                    continue

                # DELISTED and SUSPENDED both mark at the last real price, and
                # both take the three recovery factors. The difference is that a
                # suspension's last price is the one BEFORE the gap, which is
                # what `exit_px` would have been had the window not jumped it.
                if reason == "HORIZON":
                    variants = [(None, exit_px, exit_d)]
                else:
                    variants = [(f, last_close * f, last_close_d)
                                for f in RECOVERY_FACTORS]

                for rf, px, xd in variants:
                    if px is None or entry is None or entry <= 0:
                        continue
                    stock_ret = px / entry - 1.0
                    cost = bps.get(deal_id)
                    net = stock_ret - cost / 1e4 if cost is not None else None
                    mae = (win_low / entry - 1.0) if win_low else None
                    mfe = (win_high / entry - 1.0) if win_high else None
                    out.append((
                        next_id, deal_id, None, sessions, months,
                        entry_d, entry, xd, px, reason, rf,
                        stock_ret, net if net is not None else stock_ret,
                        mae, mfe, None, "INTRADAY",
                        reason == "HORIZON" and cost is not None,
                        CALCULATION_VERSION,
                    ))
                    next_id += 1

            if out:
                con.executemany(
                    "INSERT INTO deal_forward_outcomes VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", out)
            res.horizon_rows[label] = len(out)
            res.outcomes += len(out)

        res.benchmarks = _write_benchmarks(con, env, spine, cutoff,
                                           charmatch.min_names_per_cell())
        return res
    finally:
        con.close()


# --- benchmarks --------------------------------------------------------------
#
# Every outcome carries a return against every benchmark that COVERS it.
# "Covers" is doing real work: the index sources stop at 2026-07-08 and
# 2026-06-25 while the spine reaches 2026-09-02, and NIFTY50 does not start
# until 2007-09-17. A benchmark row is written where the benchmark actually has
# prices on both the entry and exit dates, and omitted where it does not —
# rather than carried forward from a stale last observation, which would report
# a zero benchmark return for a window the benchmark never saw.


#: The ladder, the cell minimum and the self-exclusion are DEFINED ONCE, in
#: `charmatch.py`, and consumed here and in `holdings.py` (2026-09-20). Two
#: copies kept equal by hand is how a registered study drifts from the table
#: it claims to reproduce.
MATCH_LEVELS = charmatch.MATCH_LEVELS


def _peer_returns_sql(spine: str, sessions: int, cutoff: str) -> str:
    """Forward return for EVERY name, on the same entry/exit convention as the
    outcomes themselves. This is the pool a characteristic match draws from."""
    return f"""
    WITH px AS (
        SELECT symbol, CAST(date AS DATE) AS d, open, close,
               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date) AS i
        FROM read_parquet('{spine}')
        WHERE close > 0 AND open > 0 AND date <= '{cutoff}'
    )
    SELECT symbol, d,
           LEAD(close, {sessions}) OVER w / LEAD(open, 1) OVER w - 1 AS ret,
           LEAD(d, {sessions}) OVER w AS exit_d
    FROM px WINDOW w AS (PARTITION BY symbol ORDER BY i)
    """


def _write_benchmarks(con, env, spine: str, cutoff: str,
                      min_cell: int) -> dict[str, int]:
    """Fill outcome_benchmark_returns for every horizon already written."""
    panel = str(warehouse_dir(env) / "benchmark_daily" / "**" / "*.parquet")
    charp = str(warehouse_dir(env) / "char_panel" / "**" / "*.parquet")
    written: dict[str, int] = {}

    con.execute(f"CREATE OR REPLACE TEMP VIEW bpanel AS "
                f"SELECT benchmark_id, date, close FROM read_parquet('{panel}')")

    # PEERS ARE ONLY EVER NEEDED ON EVENT DATES. The first version built a cell
    # assignment for all 5.3M symbol-days with a correlated LATERAL lookup, once
    # per horizon, once per degradation level — 27 passes over the whole spine.
    # It ran past ten minutes and was killed. A characteristic match only ever
    # compares an event to its peers ON THAT EVENT'S DATE, so the peer pool is
    # the few thousand dates that carry an eligible deal.
    con.execute(f"""CREATE OR REPLACE TEMP TABLE evdates AS
        SELECT DISTINCT trade_date AS d FROM ({_events_sql()})""")
    # ASOF, not LATERAL: one merge over sorted inputs rather than a lookup per
    # row. Each name carries the characteristics of the most recent rebalance
    # at or before the date, which is what point-in-time means here.
    con.execute("CREATE OR REPLACE TEMP TABLE cellmap AS " + charmatch.cellmap_sql(
        f"""SELECT DISTINCT symbol, CAST(date AS DATE) AS d
            FROM read_parquet('{spine}')
            WHERE CAST(date AS DATE) IN (SELECT d FROM evdates)""", charp))

    horizon_list = con.execute(
        "SELECT DISTINCT horizon_sessions FROM deal_forward_outcomes "
        "WHERE calculation_version = ? ORDER BY 1", [CALCULATION_VERSION]).fetchall()

    for (sessions,) in horizon_list:
        # Values inlined: DuckDB cannot PREPARE a CREATE VIEW, and both of
        # these are module constants or loop variables, never user input.
        con.execute(f"""CREATE OR REPLACE TEMP VIEW o AS
            SELECT o.outcome_id, o.entry_date, o.exit_date, o.stock_return,
                   d.trade_date, UPPER(TRIM(r.symbol_raw)) AS symbol
            FROM deal_forward_outcomes o
            JOIN institutional_deals_clean d USING (deal_id)
            JOIN institutional_deals_raw r USING (raw_deal_id)
            WHERE o.calculation_version = '{CALCULATION_VERSION}'
              AND o.horizon_sessions = {int(sessions)}""")

        # -- the four daily series ------------------------------------------
        # An exact date match on BOTH ends, deliberately. An as-of join would
        # silently substitute the nearest earlier close, which for an event
        # after the panel ends means comparing a 2026-08 window against a
        # 2026-07-07 price — a zero benchmark return invented from staleness.
        n = con.execute("""
            INSERT INTO outcome_benchmark_returns
            SELECT o.outcome_id, b1.benchmark_id,
                   b2.close / b1.close - 1 AS benchmark_return,
                   o.stock_return - (b2.close / b1.close - 1) AS relative_return,
                   NULL
            FROM o
            JOIN bpanel b1 ON b1.date = o.entry_date
            JOIN bpanel b2 ON b2.benchmark_id = b1.benchmark_id
                          AND b2.date = o.exit_date
            WHERE b1.close > 0
            RETURNING 1""").fetchall()
        written["daily"] = written.get("daily", 0) + len(n)

        # -- CHAR_MATCHED ----------------------------------------------------
        con.execute(f"""CREATE OR REPLACE TEMP TABLE cells AS
            SELECT p.symbol, p.d, p.ret, c.size_q, c.mom_q, c.vol_q
            FROM ({_peer_returns_sql(spine, sessions, cutoff)}) p
            JOIN cellmap c ON c.symbol = p.symbol AND c.d = p.d
            WHERE p.ret IS NOT NULL""")
        for level, keys in MATCH_LEVELS:
            con.execute(f"CREATE OR REPLACE TEMP TABLE cm_{level} AS "
                        + charmatch.cell_means_sql(level, keys))

        # The ladder — one pass, finest level first, self-excluded, `>=` the
        # config's minimum — is charmatch.ladder(); its docstring carries the
        # reasons. This consumer only splices the fragments in.
        lad = charmatch.ladder(min_cell, event="ec", own="own")
        rows = con.execute(f"""
            INSERT INTO outcome_benchmark_returns
            SELECT o.outcome_id, 'CHAR_MATCHED', {lad.bench},
                   o.stock_return - ({lad.bench}),
                   {lad.match_level}
            FROM o
            -- CELLMAP, NOT CELLS. `cells` carries only names with a non-null
            -- forward return, so joining events to it excluded EVERY delisted
            -- outcome and half the suspended ones from the benchmark
            -- benchmarks.yml calls primary — 14,315 of 52,365 rows, and
            -- precisely the events 0052 found load-bearing for the liquidity
            -- gradient. A name's characteristics exist whether or not it
            -- survived the window.
            JOIN cellmap ec ON ec.symbol = o.symbol AND ec.d = o.trade_date
            LEFT JOIN cells own ON own.symbol = o.symbol AND own.d = o.trade_date
            {lad.joins}
            WHERE ({lad.bench}) IS NOT NULL
            RETURNING 1""").fetchall()
        written["CHAR_MATCHED"] = written.get("CHAR_MATCHED", 0) + len(rows)
    return written


def main() -> int:
    print(f"DEAL FORWARD OUTCOMES — Plan 3 step 6.3, version {CALCULATION_VERSION}")
    hs = horizons()
    print(f"  {len(hs)} horizons: "
          + ", ".join(f"{s}s" + (f"({m}m)" if m else "") for s, m in hs))
    print()
    res = build()
    for label, n in res.horizon_rows.items():
        print(f"    {label:<12} {n:>7,} row(s)")
    print()
    print(res.render())
    print()
    print("  SUSPENDED rows are marked at the last price BEFORE the gap and are")
    print("  excluded from the headline (Plan 2 §3.4). They were previously")
    print("  counted as ordinary HORIZON exits — see the module docstring.")
    print("  MERGED remains undetectable: delisting_reason is UNKNOWN on every")
    print("  row of security_master (Plan 1 step 3.3).")
    print()
    print("  benchmark rows")
    for k, n in res.benchmarks.items():
        print(f"    {k:<14} {n:>8,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
