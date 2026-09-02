"""consensus.py — the critical-path study's events, and whether it can be powered.

WHY THIS IS THE ONE THAT MATTERS. [0031](../../docs/decisions/0031-consensus-is-the-critical-path-study.md)
put consensus on the critical path for a reason that survives 0038: *a pooled
convergence event requires no individual institution to be smart.* Single
participant skill is unmeasurable here — SBI Mutual Fund has 80 buys in twenty
years — so consensus is the only one of the four studies whose power does not
rest on any one participant being good.

[0038](../../docs/decisions/0038-no-horizon-survives-a-participation-cap.md)
established that no Track D horizon is registrable for BULK BUYS once Plan 2
§4.4's participation ceiling is applied. That does not settle consensus, and
assuming it does either way would be guessing at the project's central question.

THE MODELLING DECISION THIS FILE REFUSES TO MAKE SILENTLY.

For a bulk buy, the event IS the trade, so a deal too large to build is not a
tradable event — that is 0038's whole argument. For consensus the event is
*"three institutions converged"* and the trade is a NEW position of MY choosing
in that stock. Its size is limited by the stock's liquidity, not by how large
the institutions' own deals were.

So the ceiling could reasonably be applied in two places, and they give different
answers:

    STRICT      only deals that are themselves tradable count toward consensus.
                Conservative, and consistent with 0038's treatment.
    PERMISSIVE  any directional buy counts as evidence of conviction; the
                ceiling applies to the position I would take, not to theirs.

Both are computed and reported. Choosing one here, unstated, would be exactly
the kind of buried assumption that made the twelve-month result look POWERED
for a week.

WHAT A CONSENSUS EVENT IS, PRECISELY. `participants.yml`: 3+ distinct
participant names buying the same symbol within a trailing 21-session window.
An event fires on the session the count CROSSES the threshold, and does not
re-fire until the count falls back below it — otherwise a heavily-bought stock
emits an event every session for a month and the "events" are one story counted
thirty times.

PARTICIPANT IDENTITY IS THE RAW NAME, and that is a known weakness rather than
a choice. `participant_id` is NULL on all 237,340 rows because Phase 3.6 is not
built, so "SBI MUTUAL FUND" and "SBI MUTUAL FUND A/C" are two institutions here.
`participants.yml` flags the same concern from the other direction — SBI Mutual
Fund and SBI Life are genuinely two names of one house — and calls for a
parent-grouped robustness run. Both errors inflate apparent consensus, so every
count below is an UPPER bound on real convergence.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from src.common.paths import research_db, warehouse_dir
from src.research import measure, power

#: participants.yml `consensus:`. Alternates are declared there and are run as
#: robustness, never as a search for the threshold that produces a result.
THRESHOLD = 3
WINDOW_SESSIONS = 21


@dataclass(frozen=True, slots=True)
class Verdict:
    basis: str
    horizon: str
    months: float
    n_events: int
    n_cohorts: int
    cohort_sd: float
    mde: float

    @property
    def bound(self) -> float:
        # Same rule as measure.Row: the bound scales with horizon (0028).
        return measure.BOUND_PER_MONTH * self.months

    @property
    def powered(self) -> bool:
        return self.mde <= self.bound

    def render(self) -> str:
        gap = self.mde / self.bound if self.bound else float("inf")
        verdict = "POWERED" if self.powered else f"{gap:.2f}x short"
        return (f"  {self.basis:<11}{self.horizon:>6}{self.n_events:>8,}"
                f"{self.n_cohorts:>6}{self.cohort_sd:>9.2%}{self.mde:>10.4%}"
                f"{self.bound:>9.2%}{verdict:>15}")


def _events_sql(strict: bool) -> str:
    """Consensus events under one basis. Returns (symbol, date).

    The window is 21 TRADING SESSIONS, not 21 days: a calendar window would
    silently widen across holidays, and `common/calendar.py` exists because the
    observed calendar has three Saturday sessions no generated one would hold.
    """
    eligibility = (
        "cl.eligible_for_research"
        if strict else
        # PERMISSIVE still removes the two things that are not conviction at all:
        # a same-day round trip is a market maker's inventory, and a PROP_HFT
        # participant is 100% round-trip by measurement (Plan 1 Finding A).
        "cl.side = 'BUY' AND NOT cl.same_day_round_trip_flag"
        " AND cl.ineligibility_reason IS DISTINCT FROM 'PROP_HFT participant'"
    )
    return f"""
    WITH cal AS (
        SELECT date, ROW_NUMBER() OVER (ORDER BY date) AS i
        FROM (SELECT DISTINCT date FROM px)
    ),
    buys AS (
        SELECT DISTINCT
            UPPER(TRIM(raw.symbol_raw))      AS symbol,
            cl.trade_date                    AS date,
            UPPER(TRIM(raw.client_name_raw)) AS participant
        FROM institutional_deals_clean cl
        JOIN institutional_deals_raw raw USING (raw_deal_id)
        WHERE {eligibility}
          AND raw.client_name_raw IS NOT NULL
    ),
    idx AS (SELECT b.symbol, b.participant, c.i FROM buys b JOIN cal c USING (date)),
    -- Distinct participants in the trailing window, evaluated on every session a
    -- buy occurs. A stock with no buys cannot cross a threshold, so sessions
    -- without one are not evaluated.
    counted AS (
        SELECT s.symbol, s.i,
               (SELECT COUNT(DISTINCT t.participant) FROM idx t
                WHERE t.symbol = s.symbol AND t.i BETWEEN s.i - {WINDOW_SESSIONS - 1} AND s.i)
               AS n_inst
        FROM (SELECT DISTINCT symbol, i FROM idx) s
    ),
    -- The crossing, not the state. LAG over the symbol's own evaluated sessions:
    -- an event fires when the count reaches the threshold having been below it,
    -- so one convergence is one event rather than one per session it persists.
    crossings AS (
        SELECT symbol, i, n_inst,
               LAG(n_inst) OVER (PARTITION BY symbol ORDER BY i) AS prev
        FROM counted
    )
    SELECT c.symbol, cal.date
    FROM crossings c JOIN cal ON cal.i = c.i
    WHERE c.n_inst >= {THRESHOLD} AND (c.prev IS NULL OR c.prev < {THRESHOLD})
    """


def measure_basis(con, spine: str, strict: bool) -> list[Verdict]:
    basis = "STRICT" if strict else "PERMISSIVE"
    out: list[Verdict] = []
    for label, sessions, months in measure.HORIZONS:
        con.execute(f"CREATE OR REPLACE VIEW px AS SELECT * FROM read_parquet('{spine}')")
        con.execute(f"CREATE OR REPLACE VIEW rets AS {measure._returns_sql(spine, sessions, measure.REPRODUCIBILITY_HORIZON)}")
        con.execute("CREATE OR REPLACE VIEW mkt AS SELECT date, avg(ret) m FROM rets GROUP BY 1")
        con.execute(f"CREATE OR REPLACE VIEW ev AS {_events_sql(strict)}")
        df = con.execute(
            "SELECT ev.date AS tdate, r.ret - m.m AS ab"
            " FROM ev JOIN rets r ON r.symbol = ev.symbol AND r.date = ev.date"
            "         JOIN mkt m ON m.date = ev.date"
        ).df().dropna(subset=["ab"])
        if df.empty:
            continue
        cohorts = power.cohort_collapse(df["tdate"], df["ab"], freq="M")
        lp = max(1, round(months))
        out.append(Verdict(
            basis=basis, horizon=label, months=months,
            n_events=len(df), n_cohorts=len(cohorts),
            cohort_sd=power.cohort_sd(cohorts),
            mde=power.mde_serial_corrected(cohorts, label_periods=lp),
        ))
    return out


def grid(env: str | None = None) -> list[Verdict]:
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    con = duckdb.connect(str(research_db(env)))
    con.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false; SET threads=4;")
    try:
        return measure_basis(con, spine, True) + measure_basis(con, spine, False)
    finally:
        con.close()


def main() -> int:
    print("CONSENSUS — the critical-path study (0031)")
    print(f"  {THRESHOLD}+ distinct participants buying one symbol within "
          f"{WINDOW_SESSIONS} sessions; the CROSSING, not the state")
    print("  STRICT     = only tradable deals count toward consensus (0038's treatment)")
    print("  PERMISSIVE = any directional buy is evidence; the cap applies to MY position")
    print(f"\n  {'basis':<11}{'hor':>6}{'n':>8}{'coh':>6}{'sd':>9}"
          f"{'MDE':>10}{'bound':>9}{'verdict':>15}")
    rows = grid()
    for r in rows:
        print(r.render())
    powered = [r for r in rows if r.powered]
    print(f"\n  {len(powered)} of {len(rows)} (basis, horizon) pairs reach their bound"
          + (f": {', '.join(f'{r.basis}/{r.horizon}' for r in powered)}" if powered else ""))
    if not powered:
        print("  No consensus horizon is registrable on either basis.")
        print()
        print("  THIS IS NOT A KILL, AND SAYING SO WOULD BE WRONG. 0010 abandons the")
        print("  thesis when 3 of 4 studies FAIL their portfolio gate, or when none has")
        print("  PASSED one by 2027-02-28. An underpowered study has not failed a gate —")
        print("  it cannot be registered to face one. Nothing here has failed.")
        print("  What it does bear on is the deadline clause: two of the four studies")
        print("  now have no registrable horizon, so the routes to a pass by")
        print("  2027-02-28 are Selling and Blocks, both untested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
