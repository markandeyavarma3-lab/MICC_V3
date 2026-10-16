"""resignation_study.py — exp_007's event set, its power, and its EXPLORE look.

THE PLAN: docs/plan/EXP007_RESIGNATIONS_AND_INDUSTRY_PLAN.md. Nothing here is
registered. Three things, in the order the plan fixes:

  events    governance resignations (resignations.GOVERNANCE) classified from
            every archived announcement, one per company per 21 sessions,
            identified by the filing's ISIN
  power     dispersion only (0035), per population and benchmark, on EXPLORE
            and on the full sample — never a mean
  explore   means, on EXPLORE (filings before 2019-01-01) ONLY. `explore()`
            refuses a frame holding any later event: CONFIRM (2019 on) stays
            unread until a registered spec reads it once

THREE BENCHMARKS, ONE RETURN. Every abnormal return starts from the shared
`measure._returns_sql` (entered at the open after the filing date, sessions
counted as sessions, suspensions excluded):
  MKT            minus the same-session equal-weighted mean of all names
  CHAR_MATCHED   minus the size x momentum x volatility cell, the ladder of
                 outcomes.py exactly (charmatch.ladder, self-excluded, >= floor)
  CHAR_MATCHED_IND  minus the sector x size tercile cell, else sector, else the
                 CHAR_MATCHED ladder (charmatch.IND_LEVELS)

    RESEARCH_ENV=prod .venv/bin/python -m src.research.resignation_study power
    RESEARCH_ENV=prod .venv/bin/python -m src.research.resignation_study explore
"""

from __future__ import annotations

import sys
from datetime import date

import duckdb
import pandas as pd

from src.common.paths import DOCS, warehouse_dir
from src.research import charmatch, measure, power, resignations

EXPLORE_END = "2019-01-01"           # first CONFIRM filing date; the SEBI auditor circular is Oct 2019
HORIZONS = ((21, 1.0), (63, 3.0))
POWER_REPORT = DOCS / "reports" / "EXP007_POWER.md"
EXPLORE_REPORT = DOCS / "reports" / "EXP007_EXPLORE.md"
BENCHES = ("MKT", "CHAR_MATCHED", "CHAR_MATCHED_IND")


class ConfirmDataError(RuntimeError):
    """A frame holding CONFIRM events reached a function that reads means."""


def governance_events(rows: list[dict], sessions: list[str]) -> list[resignations.Event]:
    evs = [e for e in resignations.events(rows) if e.role in resignations.GOVERNANCE]
    return resignations.first_in_window(evs, sessions)


def abnormal(env: str | None, evs: list[resignations.Event], sessions_h: int) -> pd.DataFrame:
    """(tdate, isin, role, symbol, ret, ab_MKT, ab_CHAR_MATCHED, ab_CHAR_MATCHED_IND,
    level_CHAR_MATCHED, level_CHAR_MATCHED_IND) for one horizon."""
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    charp = str(warehouse_dir(env) / "char_panel" / "**" / "*.parquet")
    secp = str(warehouse_dir(env) / "sector_panel" / "**" / "*.parquet")
    min_cell = charmatch.min_names_per_cell()
    con = duckdb.connect(str(measure.research_db(env)), read_only=True)
    con.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false; SET threads=4;")
    try:
        con.execute("CREATE TEMP TABLE ev0 (tdate VARCHAR, isin VARCHAR, role VARCHAR)")
        con.executemany("INSERT INTO ev0 VALUES (?,?,?)", [(e.date, e.isin, e.role) for e in evs])
        con.execute(f"CREATE TEMP TABLE rets AS "
                    f"{measure._returns_sql(spine, sessions_h, measure.REPRODUCIBILITY_HORIZON)}")
        con.execute("CREATE TEMP TABLE mkt AS SELECT date, avg(ret) m FROM rets GROUP BY 1")
        # An event on a non-session day (a Saturday filing) is entered at the
        # next session: its 'trade date' is the first session on or after it.
        con.execute("""CREATE TEMP TABLE ev AS
            SELECT e.tdate, e.isin, e.role, m.security_id,
                   (SELECT min(r.date) FROM rets r WHERE r.security_id = m.security_id
                      AND CAST(r.date AS VARCHAR) >= e.tdate) AS d
            FROM ev0 e JOIN security_master m ON m.isin = e.isin""")
        con.execute("""CREATE TEMP TABLE o AS
            SELECT ev.tdate, ev.isin, ev.role, r.symbol, CAST(r.date AS DATE) AS d, r.ret, r.ret - k.m AS ab_mkt
            FROM ev JOIN rets r ON r.security_id = ev.security_id AND r.date = ev.d
            JOIN mkt k ON k.date = r.date""")
        names = "SELECT DISTINCT symbol, CAST(date AS DATE) AS d FROM rets WHERE CAST(date AS DATE) IN (SELECT d FROM o)"
        con.execute("CREATE TEMP TABLE cellmap AS " + charmatch.ind_cellmap_sql(names, charp, secp))
        con.execute("""CREATE TEMP TABLE cells AS
            SELECT c.*, r.ret FROM cellmap c JOIN rets r ON r.symbol = c.symbol AND CAST(r.date AS DATE) = c.d
            WHERE r.ret IS NOT NULL""")
        for level, keys in charmatch.IND_LEVELS:
            con.execute(f"CREATE TEMP TABLE cm_{level} AS " + charmatch.cell_means_sql(level, keys))
        cm = charmatch.ladder(min_cell, event="ec", own="own")
        ind = charmatch.ladder(min_cell, event="ec", own="own", rungs=charmatch.IND_LEVELS)
        df = con.execute(f"""
            SELECT o.tdate, o.isin, o.role, o.symbol, o.ret, o.ab_mkt AS ab_MKT,
                   o.ret - ({cm.bench}) AS ab_CHAR_MATCHED, {cm.match_level} AS level_CHAR_MATCHED,
                   o.ret - ({ind.bench}) AS ab_CHAR_MATCHED_IND, {ind.match_level} AS level_CHAR_MATCHED_IND
            FROM o JOIN cellmap ec ON ec.symbol = o.symbol AND ec.d = o.d
            LEFT JOIN cells own ON own.symbol = o.symbol AND own.d = o.d
            {ind.joins}""").df()
    finally:
        con.close()
    return df


def mde_rows(df: pd.DataFrame, months: float, label: str) -> list[dict]:
    """Dispersion only: cohort SD and serial-corrected MDE per benchmark."""
    out = []
    for b in BENCHES:
        x = df.dropna(subset=[f"ab_{b}"])
        if len(x) < 30:
            continue
        coh = power.cohort_collapse(x["tdate"], x[f"ab_{b}"], freq="M")
        if len(coh) < 6:
            continue
        mde = power.mde_serial_corrected(coh, label_periods=max(1, round(months)))
        out.append({"population": label, "bench": b, "events": len(x), "cohorts": len(coh),
                    "sd": power.cohort_sd(coh), "mde": mde, "bound": measure.BOUND_PER_MONTH * months})
    return out


def explore(df: pd.DataFrame) -> pd.DataFrame:
    """Means by role and benchmark — EXPLORE events only, or nothing."""
    if (df["tdate"] >= EXPLORE_END).any():
        raise ConfirmDataError(f"{int((df['tdate'] >= EXPLORE_END).sum())} event(s) on or after {EXPLORE_END} "
                               "reached explore(); CONFIRM stays unread until the registered read")
    rows = []
    for role, g in [("GOVERNANCE (pooled)", df), *sorted(df.groupby("role"))]:
        for b in BENCHES:
            x = g[f"ab_{b}"].dropna()
            if len(x) < 10:
                continue
            coh = power.cohort_collapse(g.loc[x.index, "tdate"], x, freq="M")
            rows.append({"population": role, "bench": b, "events": len(x), "cohorts": len(coh),
                         "mean_event": x.mean(), "mean_cohort": coh.mean(),
                         "t_cohort": coh.mean() / (coh.std(ddof=1) / len(coh) ** 0.5) if len(coh) > 2 else float("nan")})
    return pd.DataFrame(rows)


def _load() -> tuple[list[dict], list[str]]:
    from src.site.export import _archive_rows
    rows = _archive_rows("ANNOUNCE")
    con = duckdb.connect()
    try:
        spine = str(warehouse_dir() / "price_spine_adj" / "**" / "*.parquet")
        sessions = [r[0] for r in con.execute(
            f"SELECT DISTINCT CAST(CAST(date AS DATE) AS VARCHAR) FROM read_parquet('{spine}', hive_partitioning=true) ORDER BY 1").fetchall()]
    finally:
        con.close()
    return rows, sessions


def run_power() -> str:
    rows, sessions = _load()
    evs = governance_events(rows, sessions)
    table = resignations.table(evs)
    lines = ["# exp_007 — governance resignations: events and power", "",
             f"Generated by `src/research/resignation_study.py power`, {date.today()}. Dispersion only (0035): "
             "no mean was read. Returns end at the reproducibility horizon "
             f"({measure.REPRODUCIBILITY_HORIZON}).", "", "## Events by role and year (after de-clustering)", "",
             "| role | " + " | ".join(str(y) for y in range(2014, 2027)) + " | total |",
             "|---|" + "---:|" * 14]
    for role in sorted(table):
        c = table[role]
        lines.append(f"| {role} | " + " | ".join(str(c.get(str(y), 0)) for y in range(2014, 2027)) + f" | {sum(c.values())} |")
    lines += ["", "## Power", "", "| period | population | horizon | benchmark | events | cohorts | cohort SD | MDE | bound | MDE / bound |",
              "|---|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for sessions_h, months in HORIZONS:
        df = abnormal(None, evs, sessions_h)
        for period, sub in (("EXPLORE 2014-2018", df[df["tdate"] < EXPLORE_END]),
                            ("CONFIRM 2019-2026", df[df["tdate"] >= EXPLORE_END]), ("FULL 2014-2026", df)):
            for label, g in [("GOVERNANCE (pooled)", sub), *sorted(sub.groupby("role"))]:
                for r in mde_rows(g, months, label):
                    lines.append(f"| {period} | {r['population']} | {sessions_h}s | {r['bench']} | {r['events']:,} | "
                                 f"{r['cohorts']} | {r['sd']:.2%} | {r['mde']:.2%} | {r['bound']:.2%} | "
                                 f"{r['mde'] / r['bound']:.2f}x |")
        lv = df["level_CHAR_MATCHED_IND"].value_counts(normalize=True)
        lines.append(f"\nCHAR_MATCHED_IND rungs at {sessions_h}s: " + ", ".join(f"{k} {v:.0%}" for k, v in lv.items()))
    text = "\n".join(lines) + "\n"
    POWER_REPORT.write_text(text)
    return text


def run_explore() -> str:
    rows, sessions = _load()
    evs = [e for e in governance_events(rows, sessions) if e.date < EXPLORE_END]
    lines = ["# exp_007 — EXPLORE (filings before 2019-01-01)", "",
             f"Generated by `src/research/resignation_study.py explore`, {date.today()}. Means are allowed here "
             "and reported in full; CONFIRM (2019 on) is not read by this code.", ""]
    for sessions_h, _months in HORIZONS:
        df = abnormal(None, evs, sessions_h)
        res = explore(df)
        lines += [f"## {sessions_h} sessions", "", "| population | benchmark | events | cohorts | mean (events) | "
                  "mean (cohorts) | t (cohorts) |", "|---|---|---:|---:|---:|---:|---:|"]
        for _, r in res.iterrows():
            lines.append(f"| {r['population']} | {r['bench']} | {r['events']:,} | {r['cohorts']} | "
                         f"{r['mean_event']:+.2%} | {r['mean_cohort']:+.2%} | {r['t_cohort']:+.2f} |")
        lines.append("")
    text = "\n".join(lines) + "\n"
    EXPLORE_REPORT.write_text(text)
    return text


def main() -> int:
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what == "power":
        print(run_power())
    elif what == "explore":
        print(run_explore())
    else:
        print("  usage: power | explore")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
