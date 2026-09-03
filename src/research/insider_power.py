"""insider_power.py — power only, on the insider-filing populations 0046 measured ad-hoc.

WHY THIS EXISTS. Decision 0046 reported promoter buys at 1.51x short and
promoter sells at 1.25x short of their bound. Neither number was ever committed
as code — they were run once in a shell heredoc and typed into the decision
record. That is exactly the defect PLAN_3 §6R records about exp_001 ("the
analysis code was never committed"), reproduced in the same project that exists
to catch it. This module makes those two figures reproducible and adds the
three pledge categories the owner asked about, which had never been measured at
all.

POWER ONLY, NO EFFECT. Decision 0035: dispersion may use the full universe
because it cannot distinguish a true effect from a false one; any effect
estimate must go through the ConfirmationGuard and charge a trial family. This
file computes cohort SD and MDE and stops.

WHY PLEDGES ARE THREE SEPARATE POPULATIONS, NOT ONE. `Pledge`, `Pledge Revoke`
and `Pledge Invoke` are not three phrasings of the same event:

    Pledge         a promoter posts shares as loan collateral — a financing
                   choice, ambiguous sign a priori.
    Pledge Revoke  the pledge is released — could mean the loan was repaid
                   (improving) or the shares were sold to repay it (already
                   counted as Sell elsewhere).
    Pledge Invoke  the LENDER forecloses and sells the pledged shares. This is
                   forced selling by someone who is not the promoter, on a
                   promoter who could not meet a margin call. Economically the
                   closest thing in this dataset to genuine distress.

Pooling them would average three different economic stories into a number that
means nothing. `sources.yml`'s discipline about not calling F&O positioning
"flow" applies here too: three names is three questions.

QUANTITY IS UNRELIABLE FOR PLEDGES, VALUE IS NOT. Measured on the seed: of
14,148 Pledge rows only 128 have quantity > 0, but 13,698 have value > 0. The
same defect 0046 found on ordinary Sell rows (119,112 of 120,765 have
quantity = 0). Filtering on `value > 0` is therefore the only way to get a
usable event set; filtering on quantity would nearly empty the table.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from src.common.paths import SEED, warehouse_dir
from src.research import measure, power

INSIDER_SEED = SEED / "insider_trading.parquet"

#: PROMOTER, not every category. Decision 0046 measured promoter buys/sells
#: specifically because promoters are the class with plausible informational
#: access; pooling in employees and directors would answer a different, weaker
#: question under the same label.
PROMOTER_CATEGORIES = ("Promoters", "Promoter Group")


@dataclass(frozen=True, slots=True)
class Row:
    population: str
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
        return (f"  {self.population:<16}{self.horizon:>11}{self.n_events:>8,}"
                f"{self.n_cohorts:>6}{self.cohort_sd:>9.2%}{self.mde:>10.4%}"
                f"{self.bound:>9.2%}{v:>14}")


#: (label, transaction_type filter). Buy/Sell reproduce 0046; the three pledge
#: types are new.
POPULATIONS: tuple[tuple[str, str], ...] = (
    ("promoter buy", "transaction_type = 'Buy'"),
    ("promoter sell", "transaction_type = 'Sell'"),
    ("pledge", "transaction_type = 'Pledge'"),
    ("pledge revoke", "transaction_type = 'Pledge Revoke'"),
    ("pledge invoke", "transaction_type = 'Pledge Invoke'"),
)


def _events_sql(txn_filter: str) -> str:
    cats = ", ".join(f"'{c}'" for c in PROMOTER_CATEGORIES)
    return f"""
    SELECT CAST(filing_date AS VARCHAR) AS tdate,
           UPPER(TRIM(symbol)) AS symbol
    FROM read_parquet('{INSIDER_SEED}')
    WHERE category IN ({cats})
      AND {txn_filter}
      AND value > 0
      AND CAST(filing_date AS VARCHAR) <= '{measure.REPRODUCIBILITY_HORIZON}'
    """


def grid(env: str | None = None) -> list[Row]:
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    con = duckdb.connect(str(measure.research_db(env)), read_only=True)
    con.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false; SET threads=4;")
    out: list[Row] = []
    try:
        for label, txn_filter in POPULATIONS:
            for hlabel, sessions, months in measure.HORIZONS:
                con.execute(
                    f"CREATE OR REPLACE TEMP VIEW rets AS "
                    f"{measure._returns_sql(spine, sessions, measure.REPRODUCIBILITY_HORIZON)}"
                )
                con.execute("CREATE OR REPLACE TEMP VIEW mkt AS "
                           "SELECT date, avg(ret) m FROM rets GROUP BY 1")
                con.execute(f"CREATE OR REPLACE TEMP VIEW ev AS {_events_sql(txn_filter)}")
                df = con.execute(
                    "SELECT ev.tdate, r.ret - m.m AS ab FROM ev"
                    " JOIN rets r ON r.symbol = ev.symbol AND CAST(r.date AS VARCHAR) = ev.tdate"
                    " JOIN mkt m ON m.date = r.date"
                ).df().dropna(subset=["ab"])
                if len(df) < 30:
                    continue
                cohorts = power.cohort_collapse(df["tdate"], df["ab"], freq="M")
                lp = max(1, round(months))
                out.append(Row(
                    population=label, horizon=hlabel, months=months,
                    n_events=len(df), n_cohorts=len(cohorts),
                    cohort_sd=power.cohort_sd(cohorts),
                    mde=power.mde_serial_corrected(cohorts, label_periods=lp),
                ))
    finally:
        con.close()
    return out


def main() -> int:
    print("INSIDER POWER — promoter buy/sell (reproduces 0046) + three pledge populations")
    print(f"  fixed horizon {measure.REPRODUCIBILITY_HORIZON}; value>0 filter "
          f"(quantity is unreliable — 128 of 14,148 Pledge rows have qty>0)")
    print("  power only, no effect estimate (0035)")
    print(f"\n  {'population':<16}{'horizon':>11}{'n':>8}{'coh':>6}{'sd':>9}"
          f"{'MDE':>10}{'bound':>9}{'verdict':>14}")
    rows = grid()
    for r in rows:
        print(r.render())
    powered = [r for r in rows if r.powered]
    print(f"\n  {len(powered)} of {len(rows)} (population, horizon) pairs reach their bound"
          + (f": {', '.join(f'{r.population}/{r.horizon}' for r in powered)}" if powered else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
