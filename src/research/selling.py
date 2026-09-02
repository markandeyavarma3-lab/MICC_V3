"""selling.py — the study with the events, and the last route to a registrable result.

WHY THIS ONE MATTERS NOW. [0038](../../docs/decisions/0038-no-horizon-survives-a-participation-cap.md)
found no registrable bulk-buy horizon and [0043](../../docs/decisions/0043-consensus-is-not-registrable-either.md)
found none for consensus, the critical-path study. Two of the four are out. The
arithmetic on waiting is hopeless — reaching the bound from consensus's 1.94x
short needs 3.76x more monthly cohorts, which is 70 years of collection — so the
only lever left is a study with more events, and Selling is the one that has
them: 4,306 tradable sells against consensus's 1,064 measurable events.

WHY SELLING IS NOT JUST "BUYS WITH THE SIGN FLIPPED". [0031](../../docs/decisions/0031-consensus-is-the-critical-path-study.md)
ranked it first among the extensions for a reason that is economic rather than
statistical: **institutions buy for many reasons and sell for fewer.** A purchase
can be an inflow, an index inclusion, a rebalance or a view. A discretionary sale
of a position already held is a narrower set of motives, so the disclosure
carries more information per event even before the count is considered.

It has also never been examined — not here, not in MICCV2, not in the 2026-08-16
audit, which measured buys only.

NO EFFECT IS COMPUTED HERE, AND THAT IS A CORRECTION.

Until 2026-09-02 this module computed `mean_ab=float(cohorts.mean())` and
printed it. Decision [0035](../../docs/decisions/0035-power-may-use-the-full-universe-effects-may-not.md)
is explicit: *"Any estimate of an effect must go through the guard: means,
medians, hit rates, t-statistics ... and every one of them charges its family."*
A cohort mean on the full universe is exactly that, and it charged nothing —
`family_charge` holds 0 rows.

`measure.py`'s own docstring states the rule one file away: *"The moment this
file computes a mean return it must move behind the ConfirmationGuard and charge
a trial family."* measure.py obeys it. This module was written afterwards and
did not. Found by an external audit, not by this project's machinery.

Dispersion only now: cohort SD, serial inflation, MDE. Those describe the data's
noise and cannot distinguish a true effect from a false one, which is 0035's
dividing line.

THE EXPECTED SIGN IS NEGATIVE, AND THE BAR IS NOT. If institutional selling
predicts anything it predicts UNDERperformance, so the effect is negative while
the plausible bound is a magnitude. `power.py` works on |effect|, which is why
the same bound applies unchanged. Reporting a one-sided bar here because the
sign is known would be choosing the test after seeing the direction.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from src.common.paths import research_db, warehouse_dir
from src.research import measure, power


@dataclass(frozen=True, slots=True)
class Row:
    horizon: str
    months: float
    n_events: int
    n_cohorts: int
    cohort_sd: float
    mde: float

    @property
    def bound(self) -> float:
        return measure.BOUND_PER_MONTH * self.months

    @property
    def powered(self) -> bool:
        return self.mde <= self.bound

    def render(self) -> str:
        v = "POWERED" if self.powered else f"{self.mde / self.bound:.2f}x short"
        return (f"  {self.horizon:>11}{self.n_events:>8,}{self.n_cohorts:>6}"
                f"{self.cohort_sd:>9.2%}{self.mde:>10.4%}{self.bound:>9.2%}{v:>14}")


#: The same filters the buy side gets, applied to sells. NOT re-derived here —
#: `institutional_deals_clean` already holds the size floor, the ADV floor and
#: the participation ceiling, applied once where they can be counted. The only
#: difference from `measure.grid` is the side.
EVENT_SQL = """
    SELECT cl.trade_date AS tdate, UPPER(TRIM(raw.symbol_raw)) AS symbol
    FROM institutional_deals_clean cl
    JOIN institutional_deals_raw raw USING (raw_deal_id)
    WHERE cl.side = 'SELL'
      AND NOT cl.same_day_round_trip_flag
      AND cl.ineligibility_reason IS DISTINCT FROM 'PROP_HFT participant'
      AND cl.deal_value_to_adv20 BETWEEN 0.005 AND 0.50
      AND cl.gross_deal_value >= 1e7
      AND NOT cl.unresolved_symbol_flag
      AND NOT cl.uncovered_symbol_flag
"""


def grid(env: str | None = None) -> list[Row]:
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    con = duckdb.connect(str(research_db(env)))
    con.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false; SET threads=4;")
    out: list[Row] = []
    try:
        for label, sessions, months in measure.HORIZONS:
            con.execute(f"CREATE OR REPLACE VIEW rets AS {measure._returns_sql(spine, sessions, measure.REPRODUCIBILITY_HORIZON)}")
            con.execute("CREATE OR REPLACE VIEW mkt AS SELECT date, avg(ret) m FROM rets GROUP BY 1")
            con.execute(f"CREATE OR REPLACE VIEW ev AS {EVENT_SQL}")
            df = con.execute(
                "SELECT ev.tdate, r.ret - m.m AS ab FROM ev"
                " JOIN rets r ON r.symbol = ev.symbol AND r.date = ev.tdate"
                " JOIN mkt m ON m.date = ev.tdate"
            ).df().dropna(subset=["ab"])
            if df.empty:
                continue
            cohorts = power.cohort_collapse(df["tdate"], df["ab"], freq="M")
            lp = max(1, round(months))
            out.append(Row(
                horizon=label, months=months, n_events=len(df), n_cohorts=len(cohorts),
                cohort_sd=power.cohort_sd(cohorts),
                mde=power.mde_serial_corrected(cohorts, label_periods=lp),
            ))
    finally:
        con.close()
    return out


def main() -> int:
    print("SELLING — 34,270 events never examined anywhere (0031)")
    print("  same filters as the buy side; the only difference is the side")
    print("  expected sign is NEGATIVE; the bound is a magnitude, so it is unchanged")
    print(f"\n  {'horizon':>11}{'n':>8}{'coh':>6}{'sd':>9}{'MDE':>10}"
          f"{'bound':>9}{'verdict':>14}")
    rows = grid()
    for r in rows:
        print(r.render())
    powered = [r for r in rows if r.powered]
    print(f"\n  {len(powered)} of {len(rows)} horizons reach their bound"
          + (f": {', '.join(r.horizon for r in powered)}" if powered else ""))
    if powered:
        print()
        print("  POWERED IS NOT A RESULT. It means a study COULD be registered here")
        print("  and reach a conclusion. The mean above is exploratory and must not")
        print("  be reported as a finding — 0002 requires the spec frozen first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
