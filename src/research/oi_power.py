"""oi_power.py — can exp_003 be powered? Dispersion and n only. Decision 0067.

WHAT THIS COMPUTES, AND THE ONE THING IT MUST NOT.

For each participant category (FII, DII, Pro, Client — TOTAL is the market's
sum row and is excluded) and each horizon: the number of daily observations
that carry both a dOI and a forward NIFTY 50 return, the number of monthly
cohorts, the cohort standard deviation of the forward return, the Bartlett
serial inflation with a lag covering the label overlap (0033), and the
resulting minimum detectable effect — single-arm (a cohort mean) and
two-arm (the tercile difference the registered estimator actually tests,
which is twice the single-arm MDE at equal arm sizes). The verdict compares
the two-arm MDE at each horizon with the plausible bound, which scales with
horizon (0028).

IT DOES NOT COMPUTE A MEAN RETURN, A TERCILE SPLIT, A SIGN, OR A DIRECTION.
Decision 0035: power may use the full universe because dispersion cannot
distinguish a true effect from a false one; the moment this file conditions
a return on the signal it must move behind the guard and charge the family.
The forward return series is the NIFTY's own, unconditional; the signal
columns are never read here. `tests/test_oi_power.py` parses this file's AST
for `.mean(`/`.median(` and refuses them.

THIS IS DERIVATIVES POSITIONING, NOT CASH FLOW (sources.yml, 0058, 0067).

REFUSES TO RUN UNREGISTERED. exp_003 must exist in `experiment_registry`
with status REGISTERED; the hash is printed so the report can cite it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import duckdb

from src.common.paths import SEED, governance_db, research_db
from src.research import power

EXPERIMENT_ID = "exp_003_participant_oi_category"
CATEGORIES: tuple[str, ...] = ("FII", "DII", "Pro", "Client")
HORIZONS: tuple[int, ...] = (1, 2, 3, 5, 10, 21, 63, 126, 252)
PRIMARY = 21
SESSIONS_PER_MONTH = 21.0


def _bound_per_month() -> float:
    import yaml

    from src.common.paths import CONFIGS

    return float(yaml.safe_load((CONFIGS / "research.yml").read_text())["power"]["plausible_effect_bound_monthly"])


BOUND_PER_MONTH = _bound_per_month()


@dataclass(frozen=True, slots=True)
class Row:
    category: str
    sessions: int
    n_obs: int
    n_cohorts: int
    cohort_sd: float
    inflation: float
    mde_one_arm: float
    mde_two_arm: float

    @property
    def months(self) -> float:
        return self.sessions / SESSIONS_PER_MONTH

    @property
    def bound(self) -> float:
        return BOUND_PER_MONTH * self.months

    @property
    def powered(self) -> bool:
        return self.mde_two_arm <= self.bound

    @property
    def verdict(self) -> str:
        if self.powered:
            return "POWERED-enough-to-fit"
        return f"UNDERPOWERED ({self.mde_two_arm / self.bound:.2f}x short)"


def registered_hash(env: str | None = None) -> str:
    con = sqlite3.connect(str(governance_db(env)))
    try:
        row = con.execute(
            "SELECT spec_hash, status FROM experiment_registry WHERE experiment_id = ?",
            (EXPERIMENT_ID,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        con.close()
    if not row or row[1] != "REGISTERED":
        raise RuntimeError(
            f"{EXPERIMENT_ID} is not REGISTERED (found {row}). Run "
            f"scripts/register_exp003.py first: the spec is frozen before any number."
        )
    return row[0]


def _forward_returns_sql(spine: str, sessions: int) -> str:
    """NIFTY 50 forward return: entered at the OPEN of the session after the
    signal session (the file is published after that close), exited at the
    close `sessions` sessions later. Unconditional — every session, no signal."""
    return f"""
    WITH px AS (
        SELECT CAST(date AS DATE) AS date, open, close,
               ROW_NUMBER() OVER (ORDER BY date) AS i
        FROM read_parquet('{spine}') WHERE symbol = 'NIFTY50' AND close > 0 AND open > 0
    )
    SELECT date,
           LEAD(close, {sessions + 1}) OVER (ORDER BY i) / LEAD(open, 1) OVER (ORDER BY i) - 1 AS ret
    FROM px
    """


def grid(env: str | None = None) -> tuple[str, list[Row]]:
    sh = registered_hash(env)
    spine = f"{SEED}/global_indices_daily.parquet"
    con = duckdb.connect(str(research_db(env)), read_only=True)
    out: list[Row] = []
    try:
        for sessions in HORIZONS:
            con.execute(f"CREATE OR REPLACE TEMP VIEW fwd AS {_forward_returns_sql(spine, sessions)}")
            for cat in CATEGORIES:
                # A session counts only if the category has a dOI there (a prior
                # session exists) AND the index has a forward return there.
                df = con.execute(
                    "SELECT o.session_date AS d, f.ret"
                    " FROM participant_oi o"
                    " JOIN participant_oi p ON p.category = o.category"
                    "   AND p.session_date = (SELECT MAX(session_date) FROM participant_oi q"
                    "                         WHERE q.category = o.category AND q.session_date < o.session_date)"
                    " JOIN fwd f ON f.date = o.session_date"
                    " WHERE o.category = ? AND f.ret IS NOT NULL",
                    [cat]).df()
                cohorts = power.cohort_collapse(df["d"], df["ret"], freq="M")
                lp = max(1, round(sessions / SESSIONS_PER_MONTH))
                infl, _ = power.serial_inflation(cohorts, label_periods=lp)
                one = power.mde_serial_corrected(cohorts, label_periods=lp)
                out.append(Row(cat, sessions, len(df), len(cohorts),
                               power.cohort_sd(cohorts), infl, one, 2.0 * one))
    finally:
        con.close()
    return sh, out


def render(sh: str, rows: list[Row]) -> str:
    lines = [
        "# OI_POWER — exp_003, dispersion and n only",
        "",
        f"Registered spec_hash `{sh}`. Decision 0067. **Derivatives positioning, not cash flow.**",
        "No mean return, tercile, sign or direction is computed here (0035).",
        "",
        "MDE two-arm = the tercile difference the registered estimator tests (2x the",
        "single-arm cohort-mean MDE at equal arms). Bound = 0.5%/month x horizon months (0028).",
        "Verdict is POWERED only if MDE two-arm <= bound.",
        "",
        "| category | sessions | n obs | cohorts | cohort SD | infl | MDE 1-arm | MDE 2-arm | bound | verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r.category} | {r.sessions} | {r.n_obs:,} | {r.n_cohorts} | {r.cohort_sd:.3%} | "
            f"{r.inflation:.2f} | {r.mde_one_arm:.3%} | {r.mde_two_arm:.3%} | {r.bound:.2%} | {r.verdict} |"
        )
    prim = [r for r in rows if r.sessions == PRIMARY]
    lines += ["", f"## Verdict at the primary horizon ({PRIMARY} sessions)", ""]
    for r in prim:
        lines.append(f"- **{r.category}**: {r.verdict} — MDE two-arm {r.mde_two_arm:.3%} vs bound {r.bound:.2%}, "
                     f"{r.n_cohorts} cohorts, inflation {r.inflation:.2f}")
    if not any(r.powered for r in prim):
        lines += ["", "**Every category is UNDERPOWERED at the primary horizon. No fit is run;",
                  "this is the landing (0067 kill criterion 1). The bound is not loosened.**"]
    else:
        lines += ["", "At least one category is POWERED-enough-to-fit at the primary horizon.",
                  "Fitting is a separate step behind the ConfirmationGuard and charges",
                  "TRACK_O_POSITIONING; nothing here is a result."]
    return "\n".join(lines) + "\n"


def main() -> int:
    sh, rows = grid()
    print(render(sh, rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
