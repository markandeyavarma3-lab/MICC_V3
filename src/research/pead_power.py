"""pead_power.py — post-earnings drift: is there enough data to test it? DISPERSION ONLY.

PRELIMINARY, NOT REGISTERED, NOTHING CHARGED (0035). The study this previews:
after a quarterly result, do the most positively surprising companies out-drift
the most negatively surprising over the next 21 / 63 sessions?

WHAT IS READ, AND WHAT IS NOT. Every quarterly result NSE holds
(collected/results, one row per company-quarter) is an event, entered at the
first session AFTER the filing date — filings land during market hours, so the
filing day itself would trade on news before it was public. Abnormal returns
are exp_007's (resignation_study.abnormal: MKT, CHAR_MATCHED, CHAR_MATCHED_IND).
The top and bottom fifths are drawn AT RANDOM within each monthly cohort, so no
surprise ever meets a return: the spread's dispersion is measured, its sign and
size never. Surprise is computed only to count which events a seasonal-random-
walk SUE could rank (profit at the quarter and four quarters before, and at
least four earlier seasonal differences to scale it).

    RESEARCH_ENV=prod .venv/bin/python -m src.research.pead_power
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import COLLECTED, DOCS  # noqa: E402
from src.research import measure, power, resignations  # noqa: E402
from src.research import resignation_study as S  # noqa: E402

RESULTS = COLLECTED / "results" / "results_quarterly.parquet"
REPORT = DOCS / "reports" / "PEAD_POWER_PRELIMINARY.md"
HORIZONS = ((21, 1.0), (63, 3.0))
SHARE = 0.2                    # top and bottom fifths
DRAWS = 200
MIN_PRIOR_DIFFS = 4            # seasonal differences before the quarter that scale its SUE


def eligible(res: pd.DataFrame) -> pd.Series:
    """True where a seasonal-random-walk SUE is computable: profit at the
    quarter and four quarters before, and >= MIN_PRIOR_DIFFS earlier seasonal
    differences. Pure; reads profits, never returns."""
    qe = pd.to_datetime(res["qe"])
    keys = list(zip(res["symbol"], (qe.dt.year * 4 + (qe.dt.month - 1) // 3).tolist(), strict=True))
    pat = {k: v for k, v in zip(keys, res["pat"].tolist(), strict=True) if v is not None and not pd.isna(v)}
    has_diff = {(s, k) for (s, k) in pat if (s, k - 4) in pat}
    return pd.Series([key in has_diff and sum((key[0], key[1] - j) in has_diff for j in range(1, 9))
                      >= MIN_PRIOR_DIFFS for key in keys], index=res.index)


def events(env: str | None = None) -> tuple[list[resignations.Event], pd.DataFrame]:
    """One event per company-quarter, ISIN as of the filing date, dated the day
    after the filing (abnormal() enters at the first session on or after it)."""
    # A result without a filing date has no safe entry day (100 of 49,204 on 2026-10-24): left out, and counted.
    res = duckdb.sql(f"SELECT symbol, qe, filed, pat FROM read_parquet('{RESULTS}') "
                     f"WHERE TRY_CAST(filed AS DATE) IS NOT NULL").df()
    res["eligible"] = eligible(res)
    con = duckdb.connect(str(measure.research_db(env)), read_only=True)
    try:
        con.register("res", res)
        # Identity by the identity layer's own rule (src/identity/master.py
        # RESOLVE_SQL, as measure.identified_px_ctes): the window covering the
        # filing date, else the nearest window, ties to the lowest security_id.
        # Strict windows lost 26,882 of 49,104 results: the seed closes 1,668
        # windows on 2019-12-02 with no successor (20MICRONS, still trading).
        m = con.execute("""
            SELECT r.symbol, r.qe, r.filed, r.eligible, s.isin
            FROM res r JOIN symbol_history h ON h.symbol = r.symbol
            JOIN security_master s ON s.security_id = h.security_id
            QUALIFY ROW_NUMBER() OVER (PARTITION BY r.symbol, r.qe ORDER BY
                CASE WHEN CAST(r.filed AS DATE) >= h.valid_from
                      AND (h.valid_to IS NULL OR CAST(r.filed AS DATE) <= h.valid_to) THEN 0
                     WHEN CAST(r.filed AS DATE) < h.valid_from THEN date_diff('day', CAST(r.filed AS DATE), h.valid_from)
                     ELSE date_diff('day', h.valid_to, CAST(r.filed AS DATE)) END, h.security_id) = 1""").df()
    finally:
        con.close()
    m["tdate"] = [(date.fromisoformat(f) + timedelta(days=1)).isoformat() for f in m["filed"]]
    evs = [resignations.Event(t, i, "RESULT") for t, i in zip(m["tdate"], m["isin"], strict=True)]
    return evs, res.merge(m[["symbol", "qe", "isin", "tdate"]], on=["symbol", "qe"], how="left")


def _undated() -> int:
    return duckdb.sql(f"SELECT count(*) FROM read_parquet('{RESULTS}') "
                      f"WHERE TRY_CAST(filed AS DATE) IS NULL").fetchone()[0]


def random_spread_mde(df: pd.DataFrame, col: str, months: float, draws: int = DRAWS, seed: int = 0) -> dict:
    """Serial-corrected MDE of a top-minus-bottom-fifth spread whose members are
    drawn at random within each monthly cohort. The median over draws."""
    x = df.dropna(subset=[col])[["tdate", col]].copy()
    x["m"] = pd.to_datetime(x["tdate"]).dt.to_period("M")
    groups = [g[col].to_numpy() for _, g in x.groupby("m") if len(g) >= 10]
    months_idx = [m for m, g in x.groupby("m") if len(g) >= 10]
    rng = np.random.default_rng(seed)
    mdes, sds = [], []
    for _ in range(draws):
        spreads = []
        for v in groups:
            k = max(1, int(len(v) * SHARE))
            p = rng.permutation(len(v))
            spreads.append(v[p[:k]].mean() - v[p[-k:]].mean())
        coh = pd.Series(spreads, index=pd.PeriodIndex(months_idx))
        mdes.append(power.mde_serial_corrected(coh, label_periods=max(1, round(months))))
        sds.append(float(coh.std(ddof=1)))
    return {"events": len(x), "cohorts": len(groups), "sd": float(np.median(sds)), "mde": float(np.median(mdes)),
            "bound": measure.BOUND_PER_MONTH * months}


def main() -> int:
    evs, res = events()
    lines = ["# PEAD_POWER_PRELIMINARY.md — post-earnings drift, dispersion only", "",
             "**PRELIMINARY. NOT REGISTERED. NOT FROZEN. NOTHING IS CHARGED TO A FAMILY.** "
             "The top and bottom fifths are drawn AT RANDOM within each monthly cohort: no "
             "surprise was set against any return. Generated by `python -m src.research.pead_power`.", "",
             "## Events", "",
             f"- company-quarters with a filing date: **{len(res):,}** ({res['qe'].min()} .. {res['qe'].max()}); "
             f"{_undated():,} without one are left out (no safe entry day)",
             f"- with an NSE symbol matched to an ISIN on the filing date: **{res['isin'].notna().sum():,}**",
             f"- where a seasonal-random-walk SUE is computable (profit now and a year before, "
             f">= {MIN_PRIOR_DIFFS} earlier seasonal differences): **{int(res['eligible'].sum()):,}**", "",
             "| year | quarters | SUE-eligible |", "|---|---:|---:|"]
    by = res.assign(y=res["qe"].str[:4]).groupby("y").agg(n=("qe", "size"), e=("eligible", "sum"))
    lines += [f"| {y} | {int(r.n):,} | {int(r.e):,} |" for y, r in by.iterrows()]
    lines += ["", "## Power of a top-minus-bottom-fifth spread (random members)", "",
              "| sample | horizon | benchmark | events | monthly cohorts | spread SD | MDE | bound | MDE / bound |",
              "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    elig = res.loc[res["eligible"] & res["isin"].notna(), ["isin", "tdate"]]
    summary = []
    for h, months in HORIZONS:
        df = S.abnormal(None, evs, h)
        for label, d in (("all results", df), ("SUE-eligible", df.merge(elig, on=["isin", "tdate"]))):
            for b in S.BENCHES:
                r = random_spread_mde(d, f"ab_{b}", months)
                lines.append(f"| {label} | {h}s | {b} | {r['events']:,} | {r['cohorts']} | {r['sd']:.2%} | "
                             f"{r['mde']:.2%} | {r['bound']:.2%} | {r['mde'] / r['bound']:.2f}x |")
                summary.append((label, h, b, r))
    lines += ["", "## How to read it", "",
              "The MDE is the smallest true spread this sample could detect at 5% two-sided with 80% power, "
              "after the serial correction for overlapping horizons (0033). Below 1.00x the design is powered "
              "at the bound; a registration would still freeze the SUE definition, the fifths, the horizon and "
              "the benchmark before any spread is read. Events end at the reproducibility horizon "
              f"({measure.REPRODUCIBILITY_HORIZON})."]
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
