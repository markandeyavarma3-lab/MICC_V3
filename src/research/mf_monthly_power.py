"""mf_monthly_power.py — could MONTHLY scheme portfolios power the mutual-fund
holding-change question sooner? Dispersion and n only. PRELIMINARY.

WHY (2026-10-15). Decision 0086 scheduled the mutual-fund holding-change
series (exp_004's d_mf, 1.12x short at 63 sessions on QUARTERLY shareholding
filings) for re-measurement in 2027-10, reaching its bound about 2028. Since
2026-10-10 the project holds every covered scheme's MONTHLY portfolio
(src/ingest/mf_portfolios.py), ABSL, PPFAS and Motilal back to 2015-12. Monthly
cohorts are three times as many per year; this asks whether they buy the bound
years earlier — before anyone designs a monthly study.

WHAT THIS COMPUTES, AND THE ONE THING IT MUST NOT. Exactly holdings_power.py's
method. A stock is in month M's cohort if a covered scheme held it at the end
of M and of M-1 (so a month-on-month change could be defined); its outcome is
the market-relative return from the first session after the 10th of M+1 (SEBI's
publication deadline) over 21 and 63 sessions. Each cohort is split into
deciles AT RANDOM and the spread taken; the SD of the mean-across-months spread
over 2,000 draws is the SE a study would face; MDE = (z_a + z_b) x SE.

NO QUANTITY, VALUE OR PERCENTAGE IS READ. The portfolio table is opened for
isin and as_of only — which stock-months exist. tests/test_mf_monthly_power.py
parses this file and refuses any reference to the holding columns. Decision
0035: power may use the full panel because dispersion cannot tell a true effect
from a false one. Nothing here is frozen, hashed or charged.

KNOWN DEPARTURES, stated in the report: coverage is the 17 houses the site
reads, and before 2019 only ABSL, PPFAS and Motilal — a different panel from
"all mutual funds"; cohorts are equity ISINs held by those schemes, not the
whole market.

    RESEARCH_ENV=prod .venv/bin/python -m src.research.mf_monthly_power
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
import numpy as np

from src.common.paths import DOCS, research_db, warehouse_dir

#: The MARKET LEG ONLY, as holdings_power.py takes it.
from src.research.holdings import market_tri_sql
from src.research.measure import identified_px_ctes

REPORT = DOCS / "reports" / "MF_MONTHLY_POWER_PRELIMINARY.md"
HORIZONS = (21, 63)
#: 0028's plausible bound, 0.5% a month, scaled to the horizon.
BOUND_PER_MONTH = 0.005
DRAWS = 2000
SEED_RNG = 20261015
MIN_PER_MONTH = 100              # ten names a decile, as exp_004's floor
PUBLICATION_DAY = 10             # SEBI: monthly portfolios within ten days of month-end
Z_SUM = 1.959964 + 0.841621
#: exp_004's quarterly figures, for the comparison the report exists to make
#: (docs/reports/HOLDINGS_POWER_PRELIMINARY.md, decision 0086).
QUARTERLY = {"horizon": 63, "shortfall": 1.12, "reaches_bound": "about 2028"}


def _mf_path():
    from src.ingest import mf_portfolios
    return mf_portfolios.OUT


def _frame(horizon: int, env: str | None = None):
    """(month, security_id, market-relative return over `horizon`) per stock-month."""
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    mf = _mf_path()
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        sql = f"""
        WITH {identified_px_ctes(spine)},
        ordered AS (
            SELECT security_id, date, open, close,
                   ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY date) AS rn
            FROM sec),
        held AS (
            SELECT DISTINCT isin, CAST(as_of AS DATE) AS m
            FROM read_parquet('{mf}')
            WHERE as_of IS NOT NULL AND isin LIKE 'INE%' AND substr(isin, 8, 2) = '01'),
        monthly AS (                                  -- month-ends: day-of-month varies by house
            SELECT DISTINCT isin, last_day(m) AS m FROM held),
        paired AS (                                   -- held at M and at M-1: a change is defined
            SELECT a.isin, a.m FROM monthly a JOIN monthly b
              ON b.isin = a.isin AND b.m = last_day(a.m - INTERVAL 1 MONTH)),
        cohort AS (
            SELECT b.m, s.security_id,
                   CAST(b.m + INTERVAL 1 DAY + INTERVAL {PUBLICATION_DAY - 1} DAY AS DATE) AS public_by
            FROM paired b JOIN security_master s ON s.isin = b.isin),
        entry AS (
            SELECT c.m, c.security_id, o.rn AS entry_rn, o.open AS entry_open, o.date AS entry_date
            FROM cohort c JOIN ordered o ON o.security_id = c.security_id AND CAST(o.date AS DATE) > c.public_by
            QUALIFY ROW_NUMBER() OVER (PARTITION BY c.m, c.security_id ORDER BY o.date) = 1),
        matured AS (
            SELECT e.*, x.close AS exit_close, x.date AS exit_date
            FROM entry e JOIN ordered x ON x.security_id = e.security_id AND x.rn = e.entry_rn + {horizon}),
        mkt AS ({market_tri_sql()})
        SELECT CAST(m.m AS VARCHAR) AS month, m.security_id,
               (m.exit_close / m.entry_open - 1.0) - (mx.close / me.close - 1.0) AS rel
        FROM matured m
        JOIN mkt me ON me.d = CAST(m.entry_date AS DATE)
        JOIN mkt mx ON mx.d = CAST(m.exit_date AS DATE)
        WHERE m.entry_open > 0"""
        return con.execute(sql).df()
    finally:
        con.close()


def null_se(groups: dict, months: list[str], draws: int, rng) -> float:
    """SD across draws of the mean-over-months RANDOM-decile spread. Only the
    outcome is touched."""
    means = np.empty(draws)
    for b in range(draws):
        sp = []
        for q in months:
            r = groups[q]
            perm = rng.permutation(len(r))
            k = max(2, len(r) // 10)
            sp.append(r[perm[:k]].mean() - r[perm[-k:]].mean())
        means[b] = float(np.mean(sp))
    return float(means.std(ddof=1))


@dataclass(frozen=True)
class Result:
    horizon: int
    months: int
    first: str
    last: str
    names_median: int
    names_min: int
    null_se: float
    mde: float
    bound: float
    ratio: float
    overlap_inflation: float
    ratio_overlap: float
    months_needed: float


def assess(df, horizon: int, draws: int = DRAWS, seed: int = SEED_RNG) -> Result:
    groups = {q: g["rel"].to_numpy() for q, g in df.groupby("month") if len(g) >= MIN_PER_MONTH}
    months = sorted(groups)
    if len(months) < 3:
        raise RuntimeError(f"only {len(months)} month(s) with >= {MIN_PER_MONTH} matured names")
    rng = np.random.default_rng(seed)
    se = null_se(groups, months, draws, rng)
    mde = Z_SUM * se
    bound = BOUND_PER_MONTH * horizon / 21
    # A 63-session outcome on monthly cohorts overlaps its two neighbours; a
    # holding-change signal is persistent, so a study's deciles would share names
    # month to month and its cohort means would be serially dependent. A random
    # split cannot show that dependence, so the correction is the conservative
    # one: horizon/21 cohorts carry one cohort's information.
    infl = max(1.0, horizon / 21)
    ratio = mde / bound
    ratio_o = mde * np.sqrt(infl) / bound
    needed = len(months) * ratio_o ** 2
    ns = [len(groups[q]) for q in months]
    return Result(horizon, len(months), months[0], months[-1], int(np.median(ns)), int(min(ns)), se, mde,
                  bound, ratio, infl, ratio_o, needed)


def render(rs: list[Result], cover: list[tuple]) -> str:
    out = ["# Mutual-fund holding change on MONTHLY portfolios — power, PRELIMINARY", "",
           f"Generated by `src/research/mf_monthly_power.py`, {date.today()}. Dispersion and n only (0035): no "
           "holding quantity, value or percentage was read. Nothing frozen, hashed or charged.", "",
           "**The question:** decision 0086 scheduled the mutual-fund holding-change series for 2027-10, "
           f"{QUARTERLY['shortfall']}x short at {QUARTERLY['horizon']} sessions on QUARTERLY filings and reaching "
           f"its bound {QUARTERLY['reaches_bound']}. Would MONTHLY scheme portfolios get there sooner?", "",
           "| horizon | months | span | names/month (median, min) | null SE | MDE | bound | MDE / bound | "
           "serial inflation | MDE / bound, corrected | months needed |",
           "|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rs:
        out.append(f"| {r.horizon} | {r.months} | {r.first} .. {r.last} | {r.names_median}, {r.names_min} | "
                   f"{r.null_se:.4f} | {r.mde:.2%} | {r.bound:.2%} | {r.ratio:.2f}x | {r.overlap_inflation:.2f} | "
                   f"**{r.ratio_overlap:.2f}x** | {r.months_needed:.0f} |")
    out += ["", "Months needed = months held x (corrected ratio)^2, the cohort count at which the MDE "
            "reaches the bound if the dispersion stays as measured.", "",
            "## Coverage behind the cohorts", "", "| fund house | first month | last month | months |",
            "|---|---|---|---:|"]
    out += [f"| {a} | {f} | {lst} | {n} |" for a, f, lst, n in cover]
    out += ["", "## Read this with", "",
            "- **A different panel from exp_004's.** exp_004's d_mf is the change in ALL mutual funds' share, "
            "from each company's shareholding filing. Here a stock-month exists only if one of the covered "
            "schemes held it — before 2019 that is ABSL, PPFAS and Motilal alone. A monthly study would ask a "
            "narrower question: what these houses' schemes did.",
            "- **The entry date is SEBI's deadline**, the 10th of the next month, not each file's own "
            "publication time; a study would have to use the archived fetch time for months it collected live.",
            "- **Power is not a result.** It says only whether the design could see 0.5% a month; it says "
            "nothing about whether that effect exists."]
    return "\n".join(out) + "\n"


def coverage() -> list[tuple]:
    con = duckdb.connect()
    try:
        return con.execute(f"SELECT amc, min(as_of), max(as_of), count(DISTINCT as_of) FROM read_parquet('{_mf_path()}')"
                           " WHERE as_of IS NOT NULL GROUP BY 1 ORDER BY 2, 1").fetchall()
    finally:
        con.close()


def main() -> int:
    rs = [assess(_frame(h), h) for h in HORIZONS]
    REPORT.write_text(render(rs, coverage()))
    for r in rs:
        print(f"  {r.horizon:>2} sessions: {r.months} months, MDE {r.mde:.2%} vs bound {r.bound:.2%} -> "
              f"{r.ratio_overlap:.2f}x short (serial-corrected); ~{r.months_needed:.0f} months needed")
    print(f"  -> {REPORT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
