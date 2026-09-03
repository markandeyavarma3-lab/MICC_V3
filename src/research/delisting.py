"""delisting.py — Plan 3 step 6.4: price the events that stop trading.

WHY THIS FILE EXISTS. `measure._returns_sql` computes the forward return as
`LEAD(close, N) / LEAD(open, 1) - 1`. When a name stops trading before the
horizon, that LEAD is NULL, the row survives the join, and `avg(ab)` skips it.
The event is not excluded — it is *dropped without being counted*, which is the
one failure mode Plan 2 §3.4 singles out:

    "MICCV2's silent drop of these events was worth roughly the whole measured
     effect."

`confounds.py` inherited the same drop on 2026-09-03. It reported n=1,255 while
computing the effect over 1,145 rows, because COUNT(*) counts NULLs and avg()
does not. That discrepancy is corrected here and in confounds.py.

THE THREE CAUSES ARE NOT ONE CAUSE. Of the 110 EXPLORE sell events with no
252-session exit, the dropping was uniform and the reasons were not:

  * CENSORED  — the name is still trading; the horizon simply runs past the
    data cutoff. There is no outcome yet. Pricing these at a recovery factor
    would invent a delisting that never happened.
  * STOPPED   — the name's last observed trade precedes the spine end. This is
    the population step 6.4 is about.

Only STOPPED gets a recovery factor. Conflating the two would have priced 76
live companies as dead, and the direction of that error is not conservative.

WHICH WAY THE BIAS RUNS, STATED PLAINLY. A sell followed by a delisting priced
at 0.0 is a -100% return, so including these makes the sell effect LARGER, not
smaller. The current silent drop therefore *understates* the effect. Decision
0051 framed 6.4 as a test the effect might fail; on the arithmetic it is a test
the effect will pass, and the informative output is not the headline number but
where the newly-priced events land across liquidity tiers.

WHAT THIS CANNOT DO. Plan 2 §3.4 wants four cases: HORIZON, MERGED, DELISTED,
SUSPENDED. `security_master.delisting_reason` is UNKNOWN on every row (Plan 1
step 3.3 is BUILT, not finished — MERGER vs SUSPENSION needs corporate actions
that are not collected). So MERGED and SUSPENDED cannot be separated from
DELISTED, and every STOPPED event is priced as DELISTED. That is the wrong
treatment for a merger, whose holder receives acquirer shares rather than zero,
and it inflates the effect. It is declared, not hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from src.common.paths import SEED, research_db, warehouse_dir
from src.research import confounds, measure, split

PIT_UNIVERSE = SEED / "pit_universe.parquet"

#: Plan 2 §3.4. The headline is 0.0 — total loss — because it is the assumption
#: that cannot flatter the result by accident. The other two are reported
#: alongside it in every table, per the owner decision recorded there.
RECOVERY_FACTORS: tuple[float, ...] = (0.0, 0.25, 0.50)

#: How close a name's last trade must be to the spine's own end before we call
#: it "still trading" rather than dead. Ten sessions, not zero: a live name can
#: miss the final session for reasons that are not delisting (a halt, a missing
#: bhavcopy row) and a zero tolerance would price it as a total loss.
STILL_TRADING_SESSIONS = 10


@dataclass(frozen=True, slots=True)
class Tier:
    name: str
    n_priced: int
    n_base: int
    #: Rows actually contributing to the recovery-factor means. Must equal
    #: n_base + n_priced; if it exceeds them, CENSORED events have leaked into
    #: the mean and live companies are being priced as delistings.
    n_rf: int
    effect_base: float
    effects: dict[float, float]      # recovery factor -> effect including STOPPED

    def render(self) -> str:
        cells = "  ".join(f"rf={f:.2f} {self.effects[f]:+.2%}" for f in RECOVERY_FACTORS)
        return (f"  {self.name:<14} base n={self.n_base:>5,} {self.effect_base:+.2%}"
                f"   +{self.n_priced:>3} priced   {cells}")


def _classify_sql(spine: str, sessions: int, cutoff: str) -> str:
    """Every EXPLORE sell event, with its exit reason and both exit prices.

    `sessions_after` is the count of tradable sessions strictly following the
    event's own session. `LEAD(close, N)` needs row i+N to exist, so an exit
    lands exactly when `sessions_after >= N` — the off-by-one here is the
    difference between 1,144 and 1,145 events and was worth checking against
    the pre-existing count rather than reasoning about.
    """
    return f"""
    WITH px AS (
        SELECT symbol, date, open, close,
               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date) AS i
        FROM read_parquet('{spine}')
        WHERE close > 0 AND open > 0 AND date <= '{cutoff}'
    ),
    last AS (SELECT symbol, MAX(date) AS last_date, MAX(i) AS n FROM px GROUP BY 1),
    -- The last price the name ever printed, which is what a delisted holder
    -- marks against. Taken from px so it obeys the same close>0 filter.
    lastpx AS (
        SELECT p.symbol, p.close AS last_close
        FROM px p JOIN last l ON l.symbol = p.symbol AND l.n = p.i
    ),
    spine_end AS (SELECT MAX(date) AS e FROM px),
    -- THE LEADS ARE COMPUTED OVER THE WHOLE PRICE SERIES, BEFORE ANY JOIN TO
    -- EVENTS. Joining first and windowing after partitions over event rows
    -- only, so LEAD(open,1) returns the next EVENT's open rather than the next
    -- session's. That drew 984 events out of 1,255 on the first run, which is
    -- how it was caught; measure.py has always had this ordering right.
    f AS (
        SELECT symbol, date,
               LEAD(open, 1) OVER w AS entry,
               LEAD(close, {sessions}) OVER w AS exit_px,
               i
        FROM px WINDOW w AS (PARTITION BY symbol ORDER BY i)
    ),
    ev AS (SELECT e.* FROM ({confounds.SELL_EVENTS}) e JOIN ex_syms u USING (symbol))
    SELECT ev.tdate, ev.symbol, f.entry, f.exit_px,
           l.n - f.i AS sessions_after, lp.last_close,
           CASE
             WHEN l.n - f.i >= {sessions} THEN 'HORIZON'
             WHEN CAST(l.last_date AS DATE)
                  >= CAST((SELECT e FROM spine_end) AS DATE) - {STILL_TRADING_SESSIONS}
               THEN 'CENSORED'
             ELSE 'STOPPED'
           END AS exit_reason
    FROM ev
    JOIN f ON f.symbol = ev.symbol AND CAST(f.date AS VARCHAR) = ev.tdate
    JOIN last l ON l.symbol = ev.symbol
    JOIN lastpx lp ON lp.symbol = ev.symbol
    WHERE f.entry > 0
    """


def run(env: str | None = None, sessions: int = 252) -> tuple[dict, list[Tier]]:
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    con = duckdb.connect(str(research_db(env)), read_only=True)
    con.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false;")
    try:
        cutoff = measure.REPRODUCIBILITY_HORIZON
        con.execute(f"CREATE OR REPLACE TEMP VIEW rets AS "
                    f"{measure._returns_sql(spine, sessions, cutoff)}")
        con.execute("CREATE OR REPLACE TEMP VIEW mkt AS "
                    "SELECT date, avg(ret) m FROM rets GROUP BY 1")
        explore = confounds._explore_symbols(con)
        con.execute("CREATE OR REPLACE TEMP TABLE ex_syms (symbol VARCHAR)")
        con.executemany("INSERT INTO ex_syms VALUES (?)", [(s,) for s in explore])
        con.execute(f"CREATE OR REPLACE TEMP VIEW cls AS "
                    f"{_classify_sql(spine, sessions, cutoff)}")

        # THE MARKET LEG CAN BE MISSING, AND THAT IS A FOURTH CATEGORY.
        # `mkt` is the cross-sectional mean of 252-session forward returns, so
        # it is NULL for every date inside 252 sessions of the cutoff — no name
        # has a completed window there. A STOPPED event on such a date has a
        # stock return but nothing to measure it against.
        #
        # Three events land here, and they were being dropped exactly the way
        # the 110 were: the LEFT JOIN kept the row, avg() skipped it, and the
        # count did not move. Caught by asserting the recovery mean is taken
        # over precisely n_base + n_priced rows. Declaring it as a reason is the
        # only treatment that leaves it visible.
        con.execute("""CREATE OR REPLACE TEMP VIEW classified AS
            SELECT c.*, m.m,
                   CASE WHEN c.exit_reason = 'CENSORED' THEN 'CENSORED'
                        WHEN m.m IS NULL THEN 'NO_BENCHMARK'
                        ELSE c.exit_reason END AS reason
            FROM cls c LEFT JOIN mkt m ON CAST(m.date AS VARCHAR) = c.tdate""")
        census = {r[0]: r[1] for r in con.execute(
            "SELECT reason, COUNT(*) FROM classified GROUP BY 1").fetchall()}

        # The abnormal return under each recovery factor. HORIZON events use the
        # real exit; STOPPED events mark at last close x rf; CENSORED events are
        # excluded outright, because "no outcome yet" is not an outcome of zero.
        #
        # The market leg is the same-session cross-sectional mean the rest of the
        # project uses (decision 0021). It is measured on completed windows only,
        # which is correct: a delisted name's counterfactual is what the market
        # did over that window, not what the market's dead names did.
        rf_cols = ", ".join(
            f"""CASE WHEN c.exit_reason = 'HORIZON' THEN c.exit_px / c.entry - 1
                     ELSE c.last_close * {f} / c.entry - 1 END - c.m AS ab_{i}"""
            for i, f in enumerate(RECOVERY_FACTORS))
        con.execute(f"""CREATE OR REPLACE TEMP VIEW priced AS
            SELECT c.tdate, c.symbol, c.reason AS exit_reason,
                   CASE WHEN c.exit_reason = 'HORIZON'
                        THEN c.exit_px / c.entry - 1 END - c.m AS ab_base,
                   {rf_cols}
            FROM classified c
            WHERE c.reason IN ('HORIZON', 'STOPPED')""")

        tiers = _by_tier(con)
        return census, tiers
    finally:
        con.close()


def _by_tier(con) -> list[Tier]:
    """Overall, then the three PIT liquidity tiers. The tiers are the point.

    0051 found the effect strongest in off-500 names and weakest in top-100 —
    backwards from what a tradable signal looks like. Delisting concentrates in
    exactly the names that gradient already implicates, so pricing it should
    widen the gradient rather than close it. If the top-100 tier is where the
    newly-priced events are, that reading is wrong and worth knowing.
    """
    tier_expr = f"""
        (SELECT CASE WHEN top100 = 1 THEN 'top100'
                     WHEN top500 = 1 THEN 'top500_ex100' ELSE 'off500' END
         FROM read_parquet('{PIT_UNIVERSE}') pu
         WHERE pu.symbol = p.symbol AND CAST(pu.rebal_date AS VARCHAR) <= p.tdate
         ORDER BY pu.rebal_date DESC LIMIT 1)
    """ if PIT_UNIVERSE.exists() else "'unknown'"
    con.execute(f"CREATE OR REPLACE TEMP VIEW tiered AS "
                f"SELECT p.*, {tier_expr} AS tier FROM priced p")

    sel = ", ".join(f"avg(ab_{i})" for i in range(len(RECOVERY_FACTORS)))
    out: list[Tier] = []
    for name, where in [("ALL", "1=1")] + [
            (t, f"tier = '{t}'") for t in ("top100", "top500_ex100", "off500")]:
        row = con.execute(f"""
            SELECT COUNT(*) FILTER (WHERE exit_reason = 'STOPPED'),
                   COUNT(ab_base), COUNT(ab_0), avg(ab_base), {sel}
            FROM tiered WHERE {where}""").fetchone()
        n_priced, n_base, n_rf, base = row[0], row[1], row[2], row[3]
        if not n_base:
            continue
        out.append(Tier(name, n_priced, n_base, n_rf, base,
                        {f: row[4 + i] for i, f in enumerate(RECOVERY_FACTORS)}))
    return out


def main() -> int:
    from src.research import families

    print("DELISTING TREATMENT — Plan 3 step 6.4, EXPLORE sell events, 12-month horizon")
    print("  headline recovery factor 0.0 (Plan 2 §3.4); 0.25 and 0.50 as sensitivity")
    print("  0035: pricing an event changes an effect estimate, so this charges a family")
    print()

    census, tiers = run()
    total = sum(census.values())
    print("  exit reason census")
    for reason in ("HORIZON", "STOPPED", "CENSORED", "NO_BENCHMARK"):
        n = census.get(reason, 0)
        print(f"    {reason:<13} {n:>6,}  {n / total:6.1%}")
    print(f"    {'total':<13} {total:>6,}")
    print()
    print("  CENSORED events are EXCLUDED, not priced — the horizon runs past the")
    print("  data, so there is no outcome to recover. Pricing them at any factor")
    print("  would invent a delisting. NO_BENCHMARK events are excluded too: the")
    print("  market leg is undefined inside 252 sessions of the cutoff, so there")
    print("  is nothing to measure the stock against.")
    print()
    for t in tiers:
        print(t.render())

    print()
    print("  Every STOPPED event is priced as DELISTED. security_master carries")
    print("  delisting_reason=UNKNOWN on every row (Plan 1 step 3.3), so MERGED")
    print("  and SUSPENDED cannot be separated. A merger priced at 0.0 is a real")
    print("  overstatement of the effect and this is the declaration of it.")

    charge = families.commit_charge(
        "TRACK_D_DEALS", trials_added=len(tiers),
        description=f"step 6.4 delisting recovery on EXPLORE sell events, "
                    f"{len(tiers)} strata x {len(RECOVERY_FACTORS)} factors",
    )
    print(f"\n  charged TRACK_D_DEALS: +{len(tiers)} trials -> {charge.trials_after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
