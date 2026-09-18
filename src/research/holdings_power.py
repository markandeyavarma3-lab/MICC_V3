"""holdings_power.py — can exp_004 be powered? Dispersion and n only. PRELIMINARY.

WHAT THIS COMPUTES, AND THE ONE THING IT MUST NOT.

exp_004's estimator is a within-quarter decile spread: rank stocks by the
change in an institutional holding, go long the top decile and short the
bottom, hold 63 sessions, average the spread across quarters. Its standard
error is the dispersion of that spread across quarters UNDER THE NULL — which
is what a RANDOM decile split produces. So this module takes every stock with
a filing in each calendar quarter and a matured 63-session return, splits it
into deciles at random, computes the spread, and repeats. The standard
deviation of the resulting mean-across-quarters is the SE the study would
face; the MDE follows from `power.mde`'s (z_a + z_b) x SE.

NO HOLDING PERCENTAGE, HOLDER COUNT OR CATEGORY IS READ. The holdings table is
opened for three columns only — isin, quarter_end, broadcast_date — to know
WHICH stock-quarters exist and WHEN each became public. `tests/
test_holdings_power.py` parses this file's AST and refuses any reference to
the signal columns. Decision 0035: power may use the full universe because
dispersion cannot distinguish a true effect from a false one.

PRELIMINARY, AND SAYS SO ON EVERY LINE OF OUTPUT. Run 2026-09-18 at the
owner's request on the 240 companies parsed so far (8% of the universe),
BEFORE registration, to learn early whether ~20 quarters can say anything.
Three departures from the registered study, each stated in the report:
market-relative against the seed's NIFTY 50 (not CHAR_MATCHED — the
characteristic join is the registered study's work), the seed series ends
2026-07-07 so the last matured quarter is 2026-Q1, and calendar quarters only
(the owner's decision to keep off-cycle filings affects the SIGNAL's
definition, not the null dispersion of the outcome). Nothing here is frozen,
hashed or charged to a family.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np

from src.common.paths import COLLECTED, DOCS, SEED, research_db, warehouse_dir
from src.research import power
from src.research.measure import identified_px_ctes

HOLDINGS = COLLECTED / "shp" / "shp_holdings.parquet"
REPORT = DOCS / "reports" / "HOLDINGS_POWER_PRELIMINARY.md"
HORIZON = 63
#: 0028's plausible bound: 0.5%/month, so 1.5% over a 63-session quarter.
BOUND = 0.005 * 3
DRAWS = 2000
SEED_RNG = 20260918
MIN_PER_QUARTER = 20  # fewer than two names a decile is not a decile
#: z_{0.975} + z_{0.80}, the multiplier in power.mde for 5% two-sided, 80% power.
Z_SUM = 1.959964 + 0.841621
#: Winsorisation for the SECOND estimate. Not a design choice made here — a
#: registration may or may not clip — but the tails' share of the dispersion
#: is a fact about the outcome the owner should see before choosing.
WINSOR = (0.01, 0.99)


@dataclass(frozen=True)
class Result:
    n_stock_quarters: int
    n_quarters: int
    quarters: list[str]
    names_per_quarter: list[int]
    xsec_sd: float          # mean within-quarter cross-sectional SD of the outcome
    null_se: float          # SD of the mean-across-quarters random-decile spread
    mde: float              # (z_a + z_b) x null_se
    mde_analytic: float     # sqrt(2) x xsec_sd / sqrt(n/10) / sqrt(Q), as a check
    ratio: float            # mde / BOUND
    p01: float              # outcome tails, pooled
    p99: float
    mde_winsor: float       # the same MDE with the outcome clipped at WINSOR
    ratio_winsor: float


def _frame(env: str | None = None):
    """(quarter, security_id, market-relative 63-session return) per stock-quarter.

    Entry: the first spine session strictly AFTER broadcast_date, at the OPEN.
    Exit: close 63 sessions later, by row order within the security. A
    stock-quarter with no session after its broadcast, or fewer than 63 after
    entry, produces no row — it is not yet matured, not a zero.
    """
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    nifty = f"{SEED}/global_indices_daily.parquet"
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        sql = f"""
        WITH {identified_px_ctes(spine)},
        ordered AS (
            SELECT security_id, date, open, close,
                   ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY date) AS rn
            FROM sec
        ),
        filings AS (
            SELECT DISTINCT h.isin, h.quarter_end, h.broadcast_date, s.security_id
            FROM read_parquet('{HOLDINGS}') h
            JOIN security_master s ON s.isin = h.isin
            WHERE h.broadcast_date <> '' AND h.is_calendar_quarter
        ),
        entry AS (
            SELECT f.isin, f.quarter_end, f.security_id, o.rn AS entry_rn, o.open AS entry_open, o.date AS entry_date
            FROM filings f
            JOIN ordered o ON o.security_id = f.security_id AND CAST(o.date AS DATE) > CAST(f.broadcast_date AS DATE)
            QUALIFY ROW_NUMBER() OVER (PARTITION BY f.isin, f.quarter_end ORDER BY o.date) = 1
        ),
        matured AS (
            SELECT e.*, x.close AS exit_close, x.date AS exit_date
            FROM entry e
            JOIN ordered x ON x.security_id = e.security_id AND x.rn = e.entry_rn + {HORIZON}
        ),
        mkt AS (
            SELECT date, close FROM read_parquet('{nifty}') WHERE symbol = 'NIFTY50'
        )
        SELECT m.quarter_end, m.security_id,
               (m.exit_close / m.entry_open - 1.0)
             - (mx.close / me.close - 1.0) AS rel
        FROM matured m
        JOIN mkt me ON CAST(me.date AS DATE) = CAST(m.entry_date AS DATE)
        JOIN mkt mx ON CAST(mx.date AS DATE) = CAST(m.exit_date AS DATE)
        """
        return con.execute(sql).df()
    finally:
        con.close()


def _null_se(groups: dict, quarters: list[str], draws: int, rng) -> float:
    """SD across draws of the mean-over-quarters RANDOM-decile spread.
    No column but the outcome is touched."""
    means = np.empty(draws)
    for b in range(draws):
        spreads = []
        for q in quarters:
            r = groups[q]
            perm = rng.permutation(len(r))
            k = max(2, len(r) // 10)
            spreads.append(r[perm[:k]].mean() - r[perm[-k:]].mean())
        means[b] = float(np.mean(spreads))
    return float(means.std(ddof=1))


def assess(df, draws: int = DRAWS, seed: int = SEED_RNG) -> Result:
    rng = np.random.default_rng(seed)
    groups = {q: g["rel"].to_numpy() for q, g in df.groupby("quarter_end") if len(g) >= MIN_PER_QUARTER}
    quarters = sorted(groups)
    if len(quarters) < 2:
        raise RuntimeError(f"only {len(quarters)} quarter(s) with >= {MIN_PER_QUARTER} matured names")
    ns = [len(groups[q]) for q in quarters]
    xsec_sd = float(np.mean([groups[q].std(ddof=1) for q in quarters]))
    pooled = np.concatenate([groups[q] for q in quarters])
    p01, p99 = (float(x) for x in np.quantile(pooled, WINSOR))

    null_se = _null_se(groups, quarters, draws, rng)
    clipped = {q: np.clip(groups[q], p01, p99) for q in quarters}
    null_se_w = _null_se(clipped, quarters, draws, np.random.default_rng(seed + 1))
    # `power.mde(sd, n)` = (z_a + z_b) * sd / sqrt(n). Here the permutation has
    # already produced the SE OF THE MEAN, so n is 1 — which power.mde refuses
    # (it guards n < 2 for cohort inputs). Same formula, applied directly.
    mde = Z_SUM * null_se
    # analytic cross-check: sqrt(2) * sigma / sqrt(n/10), averaged, / sqrt(Q)
    per_q = [np.sqrt(2.0) * groups[q].std(ddof=1) / np.sqrt(max(2, len(groups[q]) // 10)) for q in quarters]
    mde_an = power.mde(float(np.sqrt(np.mean(np.square(per_q)))), len(quarters))
    mde_w = Z_SUM * null_se_w
    return Result(int(len(df)), len(quarters), quarters, ns, xsec_sd, null_se, mde, mde_an, mde / BOUND,
                  p01, p99, mde_w, mde_w / BOUND)


def render(r: Result, n_isins: int) -> str:
    verdict = ("UNDERPOWERED" if r.mde > BOUND else "POWERED") + " at the plausible bound"
    lines = [
        "# HOLDINGS_POWER_PRELIMINARY.md — exp_004 dispersion, BEFORE registration",
        "",
        "**PRELIMINARY. NOT REGISTERED. NOT FROZEN. NOTHING IS CHARGED TO A FAMILY.**",
        "Generated by `python -m src.research.holdings_power` at the owner's request",
        "on the companies parsed so far. No holding percentage, holder count or",
        "category was read; the deciles are RANDOM. Departures from the registered",
        "study: market-relative (seed NIFTY 50, ends 2026-07-07) not CHAR_MATCHED;",
        "calendar quarters only; a partial universe.",
        "",
        f"## Landing: **{verdict}** — MDE {r.mde:.2%} per quarter against a bound of {BOUND:.2%} ({r.ratio:.2f}x)",
        "",
        f"- stock-quarters with a matured 63-session return: **{r.n_stock_quarters:,}** across "
        f"**{n_isins} companies** (of 2,886 in the universe)",
        f"- quarters with >= {MIN_PER_QUARTER} names: **{r.n_quarters}** "
        f"({r.quarters[0]} -> {r.quarters[-1]}); names per quarter: "
        f"min {min(r.names_per_quarter)}, median {int(np.median(r.names_per_quarter))}, max {max(r.names_per_quarter)}",
        f"- mean within-quarter cross-sectional SD of the outcome: **{r.xsec_sd:.2%}**",
        f"- SE of the mean random-decile spread across quarters (permutation, {DRAWS:,} draws): **{r.null_se:.2%}**",
        f"- MDE (two-sided 5%, 80% power): **{r.mde:.2%}**; analytic cross-check {r.mde_analytic:.2%}",
        f"- outcome tails, pooled: 1st percentile {r.p01:+.1%}, 99th {r.p99:+.1%}",
        f"- the same MDE with the outcome winsorised at those tails: **{r.mde_winsor:.2%}** ({r.ratio_winsor:.2f}x the bound) — "
        "reported so the share of the dispersion that is a handful of extreme quarters-for-one-stock is visible; whether to clip is a registration decision",
        "",
        "## How to read it",
        "",
        "The MDE scales as 1/sqrt(names per decile) within a quarter and 1/sqrt(quarters)",
        "across them. The full universe has ~10x the names of this sample, which cuts the",
        f"within-quarter term by ~sqrt(10) = 3.2x IF the cross-section is independent — it",
        "is not; stocks move together within a quarter, and that common component does",
        "not shrink with names. The honest projection for the full panel is therefore",
        "BETWEEN this number and this number / 3.2, and only the full run says where.",
        "",
        f"Reaching the bound from here needs ({r.ratio:.2f})^2 = {r.ratio**2:.1f}x the effective",
        "observations. Four more quarters arrive per year.",
        "",
        "| quarter | names | note |", "|---|---|---|",
    ]
    for q, n in zip(r.quarters, r.names_per_quarter):
        lines.append(f"| {q} | {n} | |")
    return "\n".join(lines) + "\n"


def main() -> int:
    df = _frame()
    n_isins = int(df["security_id"].nunique())
    r = assess(df)
    text = render(r, n_isins)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text)
    print(text)
    print(f"wrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
