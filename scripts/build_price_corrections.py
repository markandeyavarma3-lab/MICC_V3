"""Freeze the price-spine corrections and the suspect-day register (decision 0088).

The Kite audit (0087) found the adjusted spine carries splits and bonuses its
seed never recorded: one-day moves of exactly 1/2, 1/5, 1/10 that a second
vendor shows as flat. This turns the evidence into two reviewable files:

  configs/price_corrections.csv   symbol, ex_date, factor, tier, evidence
      APPLIED by src/warehouse/spine.py to the whole series, back-adjusting
      every price before ex_date by `factor` (volume by 1/factor). Only where
      a second, independent source confirms an action:
        T1  NSE's own corporate-action record has a SPLIT/BONUS that day
        T2  Kite is flat that day (|ln move| < 0.2) and ours moved by a
            strict split/bonus ratio
      The factor is the strict ratio nearest the observed move — the action,
      not the day's market move on top of it.

  configs/price_suspect_days.csv  symbol, date, move, class
      Every OTHER one-day move > 35% in the adjusted series: real moves Kite
      confirms, and those no source can explain. Never changed; listed, so a
      study can exclude windows that touch them and a NEW unexplained move
      stops the build (spine.py's full-history guard).

Reads the CURRENT adjusted spine, which must be the uncorrected one: run once,
before the first corrected build. It refuses to overwrite existing files, so
the corrections are frozen and reviewed like code; Kite's data is held for one
month and the evidence must outlive it. --force rebuilds on purpose.

    RESEARCH_ENV=prod .venv/bin/python scripts/build_price_corrections.py
"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb  # noqa: E402

from src.common.paths import COLLECTED, CONFIGS, warehouse_dir  # noqa: E402
from src.research import price_audit as pa  # noqa: E402

CORRECTIONS = CONFIGS / "price_corrections.csv"
SUSPECTS = CONFIGS / "price_suspect_days.csv"
JUMP = 0.35
#: Ratios a split, bonus or consolidation actually produces: 1:1 bonus 1/2,
#: 2:1 bonus 1/3, 3:1 1/4, 4:1 or Rs10->2 split 1/5, 5:1 1/6, 1/8, Rs10->1
#: 1/10, 1/20, Rs5->2 2/5, 2:3 bonus 3/5, 1:2 bonus 2/3 — and their inverses.
_BASE = (1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 6, 1 / 8, 1 / 10, 1 / 20, 2 / 5, 3 / 5, 2 / 3)
STRICT = tuple(sorted(set(_BASE) | {1 / q for q in _BASE}))
STRICT_TOL = 0.015       # "on a strict ratio": within 1.5%
ACTION_TOL = 0.10        # an NSE-recorded action day may carry a 10% market move on top
KITE_FLAT = 0.2          # |ln(Kite's move)| below this: Kite saw no action
SAME_MOVE = 0.05         # |ln(ours) - ln(Kite's)| below this: a real move both saw
PERSIST = 5              # an action is a LEVEL shift: the next 5 sessions' median close ...
PERSIST_TOL = 0.15       # ... stays within 15% (log) of the shifted level. A bad print reverts.


def nearest(r: float) -> tuple[float, float]:
    """(strict ratio nearest r, relative distance)."""
    q = min(STRICT, key=lambda s: abs(math.log(r / s)))
    return q, abs(r / q - 1)


def classify(r: float, rk: float | None, nse_factor: float | None,
             held: float | None = None) -> tuple[str, float | None, str]:
    """(class, factor or None, evidence). Pure; the whole rule is here.

    `held` is the next PERSIST sessions' median close over the previous
    close. A correction requires it to sit at the shifted level: a split is
    permanent, a bad print (13.99 -> 11,985 -> 13.98) is not, and
    "correcting" a print would rescale the whole history before it."""
    q, d = nearest(r)
    persists = held is not None and abs(math.log(held) - math.log(r)) < PERSIST_TOL
    if held is not None and not persists:
        return "REVERTED", None, f"moved {r:.4f}, next {PERSIST} sessions at {held:.4f}: a print, not a level"
    if nse_factor is not None and abs(r / nse_factor - 1) < ACTION_TOL:
        return "T1", nse_factor, f"NSE records SPLIT/BONUS factor {nse_factor:.4g}; ours moved {r:.4f}"
    if nse_factor is not None and d < ACTION_TOL:
        # NSE's day carries several actions, some already adjusted in the seed
        # (ONGC 2011: split AND bonus, factor 0.25; ours moved 0.47 — the split
        # was applied, the bonus was not). The residual is the strict ratio.
        return "T1", q, f"NSE records SPLIT/BONUS factor {nse_factor:.4g}, partly applied; ours moved {r:.4f}"
    if rk is not None and abs(math.log(rk)) < KITE_FLAT and d < STRICT_TOL:
        return "T2", q, f"Kite moved {rk:.4f}; ours {r:.4f}"
    if rk is not None and abs(math.log(r) - math.log(rk)) < SAME_MOVE:
        return "REAL", None, "Kite shows the same move"
    if rk is not None and abs(math.log(rk)) < KITE_FLAT:
        return "UNEXPLAINED_KITE_FLAT", None, f"Kite moved {rk:.4f}; not a split ratio"
    if rk is not None:
        return "UNEXPLAINED_BOTH_MOVE", None, f"Kite moved {rk:.4f}"
    if d < STRICT_TOL:
        return "UNCONFIRMED_RATIO", None, "on a split ratio; no second source"
    return "UNEXPLAINED", None, "no second source"


def jumps(env: str | None = None) -> list[tuple]:
    adj = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    ca = str(COLLECTED / "corporate_actions" / "*.parquet")
    c = duckdb.connect()
    try:
        return c.execute(f"""
            WITH o AS (SELECT symbol, date, close, LAG(close) OVER w prev,
                              median(close) OVER (PARTITION BY symbol ORDER BY date
                                  ROWS BETWEEN 1 FOLLOWING AND {PERSIST} FOLLOWING) nxt
                       FROM read_parquet('{adj}', hive_partitioning=true)
                       WINDOW w AS (PARTITION BY symbol ORDER BY date)),
            j AS (SELECT symbol, date, close / prev r, nxt / prev held FROM o
                  WHERE prev > 0 AND close > 0 AND abs(close / prev - 1) > {JUMP}),
            k AS (SELECT symbol, date, close / LAG(close) OVER w rk FROM read_parquet('{pa.OUT}')
                  WINDOW w AS (PARTITION BY symbol ORDER BY date)),
            a AS (SELECT symbol, CAST(date AS VARCHAR) date, exp(sum(ln(factor))) f
                  FROM read_parquet('{ca}')
                  WHERE factor IS NOT NULL AND action_type IN ('SPLIT', 'BONUS', 'CONSOLIDATION')
                  GROUP BY 1, 2)
            SELECT j.symbol, j.date, j.r, k.rk, a.f, j.held
            FROM j LEFT JOIN k USING (symbol, date) LEFT JOIN a USING (symbol, date)
            ORDER BY j.symbol, j.date""").fetchall()
    finally:
        c.close()


def main() -> int:
    if (CORRECTIONS.exists() or SUSPECTS.exists()) and "--force" not in sys.argv:
        print(f"  REFUSED: {CORRECTIONS.name} / {SUSPECTS.name} exist and are frozen; --force rebuilds")
        return 1
    rows = jumps()
    fixes, suspects = [], []
    for sym, d, r, rk, f, held in rows:
        cls, factor, why = classify(r, rk, f, held)
        if factor is not None:
            fixes.append((sym, d, f"{factor:.6f}", cls, why))
        else:
            suspects.append((sym, d, f"{r:.4f}", cls))
    with CORRECTIONS.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "ex_date", "factor", "tier", "evidence"])
        w.writerows(fixes)
    with SUSPECTS.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "date", "move", "class"])
        w.writerows(suspects)
    from collections import Counter
    print(f"  {len(rows):,} one-day moves > {JUMP:.0%}")
    print(f"  corrections {len(fixes):,}: {dict(Counter(x[3] for x in fixes))}")
    print(f"  suspects    {len(suspects):,}: {dict(Counter(x[3] for x in suspects))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
