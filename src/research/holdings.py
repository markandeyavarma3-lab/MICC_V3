"""holdings.py — exp_004: quarterly institutional holding change, cross-sectional.

THE STUDY, BUILT BEFORE THE DATA IS COMPLETE AND BEHIND THE REGISTRATION GUARD.

Two halves, deliberately separated by what they may touch:

  `signals()`   reads the holdings table only. Change since the previous
                filing, per ISIN, for three signals. No price, no return. It may
                run at any time — it is a parse, not a look.

  `panel()` and `run()`   join those signals to forward returns and rank them.
                That is the study, and it REFUSES TO RUN UNREGISTERED: the
                registry must hold exp_004 with status REGISTERED, and the hash
                is printed on every output so the report can cite it. The
                preliminary dispersion in `holdings_power.py` never reads a
                signal; this module never runs without a registration. Between
                them there is no path to a conditional mean before the spec is
                frozen.

THE ESTIMATOR. Within each cohort (the calendar quarter containing the
filing's period-end), rank names by the signal into deciles, long the top,
short the bottom, equal weight, hold 63 sessions from the OPEN of the first
session after `broadcast_date` (never the quarter-end — the filing is not
public until broadcast). The statistic is the mean across cohorts of the
top-minus-bottom CHAR_MATCHED abnormal return; its standard error carries the
Bartlett serial correction from `power.py`; the null is a within-cohort label
permutation; three tests share one Benjamini-Hochberg family.

THE TAIL RULE, chosen 2026-09-18 before any signal was ranked: a name is in
the universe only if the pessimistic participation cap can build the position
— 5 sessions x 5% of ADV20 >= the per-name notional of a Rs 100 crore
long-short book (Rs 50 crore a side, equal weight across the decile). The
preliminary measured an 8x-short MDE dominated by micro-caps that tripled or
collapsed inside a quarter; a spread that exists only in names the cost model
cannot trade fails kill criterion 2 anyway. Winsorisation is REPORTED as
robustness, never used for the primary.

CHAR_MATCHED here mirrors `outcomes.py`'s construction — ASOF cell at the
entry date, cell mean of peers' forward returns on the same entry convention,
self-excluded, `min_names_per_cell` from benchmarks.yml, the same degradation
ladder. It is a second copy; unifying the two is recorded as a cost, and the
test suite compares this copy's benchmark to outcomes' on shared dates.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import duckdb
import numpy as np
import pandas as pd
import yaml

from src.common.paths import COLLECTED, CONFIGS, DOCS, SEED, governance_db, research_db, warehouse_dir
from src.research import power
from src.research.measure import identified_px_ctes

EXPERIMENT_ID = "exp_004_holdings_change"
FAMILY = "TRACK_H_HOLDINGS"
HOLDINGS = COLLECTED / "shp" / "shp_holdings.parquet"
REPORT = DOCS / "reports" / "HOLDINGS_VERDICT.md"

HORIZON = 63
HORIZONS_REPORTED = (21, 63, 126, 252)
#: 0028's plausible bound, 0.5%/month, over a 63-session quarter.
BOUND = 0.005 * 3
FDR_ALPHA = 0.05
MIN_NAMES_PER_COHORT = 20
DECILE = 10

#: The three tested signals: which parsed categories sum to each.
#: FPI is one series across two taxonomies: undivided to 2024, Cat I + II from
#: 2025. They never co-occur in a filing, so the sum is the series. FOREIGN
#: (all foreign institutions) has no counterpart in the old taxonomy and
#: starts where the new one does; its shorter depth is a fact of the data,
#: reported, not patched.
SIGNALS: dict[str, tuple[str, ...]] = {
    "FPI": ("FPI_Cat1", "FPI_Cat2", "FPI_Undivided"),
    "FOREIGN": ("ForeignInst_Total",),
    "MF": ("MutualFund",),
}

#: The tail rule's one declared parameter. Rs 100 crore long-short, Rs 50 crore
#: a side. A name is tradeable if 5 sessions at the pessimistic 5% of ADV20
#: absorb its equal-weight share of a side.
NOTIONAL_INR = 100 * 1e7
CAP_SESSIONS = 5
CAP_PCT_ADV = 0.05

MATCH_LEVELS: tuple[tuple[str, str], ...] = (
    ("SIZE_MOM_VOL", "size_q, mom_q, vol_q"),
    ("SIZE_MOM", "size_q, mom_q"),
    ("SIZE", "size_q"),
)


def _min_cell() -> int:
    cfg = yaml.safe_load((CONFIGS / "benchmarks.yml").read_text())
    return int(next(b for b in cfg["benchmarks"] if b["id"] == "CHAR_MATCHED")["construction"]["min_names_per_cell"])


# --- half one: signals, from the holdings table only ---------------------------


def signals(path=HOLDINGS) -> pd.DataFrame:
    """One row per (ISIN, filing): the three signals as changes since the
    PREVIOUS filing, the interval between them, and the cohort quarter.

    Excluded here, and counted: revised filings (the original broadcast is the
    point-in-time fact), filings whose identity_total is off by more than a
    point (a bad file), and a company's first filing (no prior to difference).
    Off-cycle filings are KEPT (owner decision 2026-09-18); `interval_days`
    says how long each change spans.
    """
    con = duckdb.connect()
    # ABSENT MEANS ZERO, WITHIN THE FILING'S OWN TAXONOMY. The 2020-2022
    # taxonomy writes every category, zeros included; V1.1+ omits a category
    # whose holding is zero. Without this a fund's EXIT (2% -> 0) reads as a
    # missing signal and drops out of exactly the decile it belongs in. The
    # old taxonomy has no foreign-institutions total at all, so FOREIGN stays
    # NULL there — a category the taxonomy cannot express is unknown, not zero.
    wide = con.execute(f"""
        SELECT isin, quarter_end, broadcast_date, is_calendar_quarter, revised, identity_total,
               COALESCE(SUM(CASE WHEN category IN ('FPI_Cat1','FPI_Cat2','FPI_Undivided') THEN pct_shares END), 0) AS fpi,
               CASE WHEN BOOL_OR(category = 'Institutions_Total_OldTaxonomy') THEN NULL
                    ELSE COALESCE(SUM(CASE WHEN category = 'ForeignInst_Total' THEN pct_shares END), 0) END AS foreign,
               COALESCE(SUM(CASE WHEN category = 'MutualFund' THEN pct_shares END), 0) AS mf
        FROM read_parquet('{path}')
        WHERE broadcast_date <> ''
        GROUP BY 1,2,3,4,5,6
    """).df()
    con.close()
    counts = {"filings": len(wide)}
    ok = wide[(~wide["revised"]) & (wide["identity_total"].isna() | ((wide["identity_total"] - 100).abs() <= 1))].copy()
    counts["revised_excluded"] = int(wide["revised"].sum())
    counts["identity_excluded"] = len(wide) - len(ok) - counts["revised_excluded"]
    ok = ok.sort_values(["isin", "quarter_end"])
    prev = ok.groupby("isin").shift(1)
    ok["prev_quarter_end"] = prev["quarter_end"]
    for s in ("fpi", "foreign", "mf"):
        ok[f"d_{s}"] = ok[s] - prev[s]
    ok = ok[ok["prev_quarter_end"].notna()].copy()
    counts["first_filings_excluded"] = len(wide) - counts["revised_excluded"] - counts["identity_excluded"] - len(ok)
    ok["interval_days"] = (pd.to_datetime(ok["quarter_end"]) - pd.to_datetime(ok["prev_quarter_end"])).dt.days
    q = pd.to_datetime(ok["quarter_end"])
    ok["cohort"] = q.dt.year.astype(str) + "Q" + q.dt.quarter.astype(str)
    ok.attrs["counts"] = counts
    return ok.reset_index(drop=True)


# --- the guard ------------------------------------------------------------------


def registered_hash(env: str | None = None) -> str:
    con = sqlite3.connect(str(governance_db(env)))
    try:
        row = con.execute("SELECT spec_hash, status FROM experiment_registry WHERE experiment_id = ?",
                          (EXPERIMENT_ID,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        con.close()
    if not row or row[1] != "REGISTERED":
        raise RuntimeError(
            f"{EXPERIMENT_ID} is not REGISTERED (found {row}). This module joins signals to "
            f"forward returns and MUST NOT run before scripts/register_exp004.py has frozen the spec.")
    return row[0]


# --- half two: the panel, behind the guard ------------------------------------


def panel(env: str | None = None, sig: pd.DataFrame | None = None) -> pd.DataFrame:
    """Signals joined to entry, forward returns, CHAR_MATCHED benchmark and the
    tradeable flag. Refuses to run unregistered."""
    registered_hash(env)
    sig = sig if sig is not None else signals()
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    charp = str(warehouse_dir(env) / "char_panel" / "**" / "*.parquet")
    nifty = f"{SEED}/global_indices_daily.parquet"
    min_cell = _min_cell()
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        con.register("sig", sig[["isin", "quarter_end", "broadcast_date", "cohort", "interval_days",
                                 "is_calendar_quarter", "d_fpi", "d_foreign", "d_mf"]])
        con.execute(f"""CREATE TEMP TABLE ordered AS
            WITH {identified_px_ctes(spine)}
            SELECT security_id, symbol, CAST(date AS DATE) AS d, open, close,
                   median(close * volume) OVER (PARTITION BY security_id ORDER BY date
                                                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS adv20,
                   ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY date) AS rn
            FROM sec""")
        con.execute(f"""CREATE TEMP TABLE ev AS
            SELECT s.*, m.security_id, o.symbol, o.d AS entry_date, o.open AS entry_open, o.rn AS entry_rn, o.adv20
            FROM sig s
            JOIN security_master m ON m.isin = s.isin
            JOIN ordered o ON o.security_id = m.security_id AND o.d > CAST(s.broadcast_date AS DATE)
            QUALIFY ROW_NUMBER() OVER (PARTITION BY s.isin, s.quarter_end ORDER BY o.d) = 1""")
        con.execute(f"""CREATE TEMP TABLE fwd AS
            SELECT e.isin, e.quarter_end, x.close / e.entry_open - 1 AS ret, x.d AS exit_date
            FROM ev e JOIN ordered x ON x.security_id = e.security_id AND x.rn = e.entry_rn + {HORIZON}""")
        # CHAR_MATCHED, on outcomes.py's construction (see the module docstring).
        con.execute(f"""CREATE TEMP TABLE cellmap AS
            SELECT p.symbol, p.d, c.size_q, c.mom_q, c.vol_q
            FROM (SELECT DISTINCT symbol, d FROM ordered WHERE d IN (SELECT DISTINCT entry_date FROM ev)) p
            ASOF JOIN read_parquet('{charp}') c ON c.symbol = p.symbol AND c.rebalance_date <= p.d""")
        con.execute(f"""CREATE TEMP TABLE cells AS
            SELECT o.symbol, o.d, LEAD(o.close, {HORIZON}) OVER w / o.open - 1 AS ret, c.size_q, c.mom_q, c.vol_q
            FROM ordered o JOIN cellmap c ON c.symbol = o.symbol AND c.d = o.d
            WINDOW w AS (PARTITION BY o.security_id ORDER BY o.d)""")
        # NOTE: cells' LEAD sees only entry dates' rows — rebuild over the full spine per entry date
        con.execute(f"""CREATE OR REPLACE TEMP TABLE cells AS
            WITH f AS (SELECT symbol, d, LEAD(close, {HORIZON}) OVER (PARTITION BY security_id ORDER BY d) / open - 1 AS ret FROM ordered)
            SELECT f.symbol, f.d, f.ret, c.size_q, c.mom_q, c.vol_q FROM f JOIN cellmap c ON c.symbol = f.symbol AND c.d = f.d
            WHERE f.ret IS NOT NULL""")
        for level, keys in MATCH_LEVELS:
            con.execute(f"CREATE TEMP TABLE cm_{level} AS SELECT d, {keys}, avg(ret) AS m, COUNT(*) AS n FROM cells GROUP BY d, {keys}")
        joins, cases, levels = [], [], []
        for level, keys in MATCH_LEVELS:
            ks = [k.strip() for k in keys.split(",")]
            joins.append(f"LEFT JOIN cm_{level} {level} ON {level}.d = ec.d AND " + " AND ".join(f"{level}.{k} = ec.{k}" for k in ks))
            cases.append(f"WHEN {level}.n >= {min_cell} THEN ({level}.m * {level}.n - COALESCE(own.ret, 0)) / ({level}.n - CASE WHEN own.ret IS NULL THEN 0 ELSE 1 END)")
            levels.append(f"WHEN {level}.n >= {min_cell} THEN '{level}'")
        bench = "CASE " + " ".join(cases) + " END"
        df = con.execute(f"""
            SELECT e.isin, e.quarter_end, e.cohort, e.interval_days, e.is_calendar_quarter,
                   e.d_fpi, e.d_foreign, e.d_mf, e.entry_date, f.exit_date, e.adv20,
                   f.ret AS raw_ret,
                   f.ret - (mx.close / me.close - 1) AS mkt_rel,
                   f.ret - ({bench}) AS char_rel,
                   CASE {' '.join(levels)} END AS match_level,
                   ec.size_q, ec.mom_q, ec.vol_q
            FROM ev e
            JOIN fwd f ON f.isin = e.isin AND f.quarter_end = e.quarter_end
            LEFT JOIN (SELECT date, close FROM read_parquet('{nifty}') WHERE symbol='NIFTY50') me ON CAST(me.date AS DATE) = e.entry_date
            LEFT JOIN (SELECT date, close FROM read_parquet('{nifty}') WHERE symbol='NIFTY50') mx ON CAST(mx.date AS DATE) = f.exit_date
            LEFT JOIN cellmap ec ON ec.symbol = e.symbol AND ec.d = e.entry_date
            LEFT JOIN cells own ON own.symbol = e.symbol AND own.d = e.entry_date
            {' '.join(joins)}
        """).df()
    finally:
        con.close()
    return tradeable(df)


def tradeable(df: pd.DataFrame) -> pd.DataFrame:
    """THE TAIL RULE. Per cohort, the per-name notional is a side divided by the
    decile size; a name is tradeable if CAP_SESSIONS x CAP_PCT_ADV x ADV20 covers it.
    Decided per cohort from the names IN that cohort, so the rule does not
    depend on the full-panel size."""
    out = df.copy()
    n = out.groupby("cohort")["isin"].transform("count")
    per_name = (NOTIONAL_INR / 2) / (n // DECILE).clip(lower=2)
    out["tradeable"] = (CAP_SESSIONS * CAP_PCT_ADV * out["adv20"]) >= per_name
    return out


# --- the estimator, pure --------------------------------------------------------


@dataclass
class TestResult:
    signal: str
    outcome: str
    n_cohorts: int
    n_names: int
    spread_mean: float
    spread_se: float          # serial-corrected
    t: float
    p_perm: float
    q_fdr: float = float("nan")
    mde: float = float("nan")
    cohorts: pd.Series = field(default_factory=pd.Series, repr=False)

    @property
    def clears_bound(self) -> bool:
        return abs(self.spread_mean) > BOUND and self.mde <= BOUND


def decile_spreads(df: pd.DataFrame, signal_col: str, outcome_col: str) -> pd.Series:
    """Per cohort: mean outcome of the top decile of `signal_col` minus the bottom.
    Cohorts with fewer than MIN_NAMES_PER_COHORT names are dropped, not padded."""
    out = {}
    for cohort, g in df.dropna(subset=[signal_col, outcome_col]).groupby("cohort"):
        if len(g) < MIN_NAMES_PER_COHORT:
            continue
        g = g.sort_values(signal_col)
        k = max(2, len(g) // DECILE)
        out[cohort] = float(g[outcome_col].iloc[-k:].mean() - g[outcome_col].iloc[:k].mean())
    return pd.Series(out).sort_index()


def _test(df, signal_col, outcome_col, permutations=1000, seed=20260918) -> TestResult:
    rng = np.random.default_rng(seed)
    cohorts = decile_spreads(df, signal_col, outcome_col)
    if len(cohorts) < 2:
        raise RuntimeError(f"{signal_col}: only {len(cohorts)} cohort(s) with >= {MIN_NAMES_PER_COHORT} names")
    mean = float(cohorts.mean())
    infl, _ = power.serial_inflation(cohorts, label_periods=1)
    se = float(cohorts.std(ddof=1) / np.sqrt(len(cohorts)) * np.sqrt(infl))
    mde = power.mde_serial_corrected(cohorts, label_periods=1)
    # WITHIN-COHORT LABEL PERMUTATION: the signal is shuffled among the names
    # of each cohort, so cohort composition and outcome dispersion are kept
    # and only the ranking is destroyed.
    obs = abs(mean)
    hits = 0
    work = df.dropna(subset=[signal_col, outcome_col]).copy()
    for _ in range(permutations):
        work[signal_col + "_p"] = work.groupby("cohort")[signal_col].transform(lambda s: rng.permutation(s.to_numpy()))
        if abs(decile_spreads(work, signal_col + "_p", outcome_col).mean()) >= obs:
            hits += 1
    p_perm = (hits + 1) / (permutations + 1)
    n_names = int(work.groupby("cohort").size().loc[cohorts.index].sum())
    return TestResult(signal_col, outcome_col, len(cohorts), n_names, mean, se,
                      mean / se if se > 0 else float("nan"), p_perm, mde=mde, cohorts=cohorts)


def bh(results: list[TestResult]) -> None:
    ordered = sorted(results, key=lambda r: r.p_perm)
    m = len(ordered)
    running = 1.0
    for rank in range(m, 0, -1):
        r = ordered[rank - 1]
        running = min(running, r.p_perm * m / rank)
        r.q_fdr = min(running, 1.0)


# --- run: guarded -----------------------------------------------------------------


def run(env: str | None = None, permutations: int = 1000) -> tuple[str, list[TestResult], dict]:
    sh = registered_hash(env)
    sig = signals()
    pnl = panel(env, sig)
    prim = pnl[pnl["tradeable"] & pnl["char_rel"].notna()]
    results = [_test(prim, f"d_{s.lower()}", "char_rel", permutations) for s in SIGNALS]
    bh(results)
    robustness = {
        "raw_return (kill 3: momentum)": [_test(prim, f"d_{s.lower()}", "raw_ret", 200) for s in SIGNALS],
        "untradeable names only (kill 2: liquidity)": [
            _test(pnl[(~pnl["tradeable"]) & pnl["char_rel"].notna()], f"d_{s.lower()}", "char_rel", 200) for s in SIGNALS],
        "calendar filings only": [
            _test(prim[prim["is_calendar_quarter"]], f"d_{s.lower()}", "char_rel", 200) for s in SIGNALS],
    }
    counts = {**sig.attrs["counts"], "panel_rows": len(pnl), "tradeable": int(pnl["tradeable"].sum()),
              "with_char_match": int(pnl["char_rel"].notna().sum())}
    return sh, results, {"robustness": robustness, "counts": counts}
