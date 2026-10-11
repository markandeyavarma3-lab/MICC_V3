"""pit_universe.py — the point-in-time top-500 universe, extended past the seed.

WHY (2026-10-11). The scan panel, the constructed small-cap benchmark and the
draft forward test exp_006 all take membership from the seed's
`pit_universe.parquet`, which ends at its 2026-06-25 rebalance. Nothing
extended it: every session since was scored on June's membership, carried
forward, and exp_006 would have scored five forward years on it — new large
companies never entering, fallen ones never leaving.

THE SEED'S RULE, RECOVERED AND MATCHED. No document states it; it was
recovered from the seed and reproduced from this project's own price spine
(raw, unadjusted), 2026-10-11:

  rebalance   the last session of each calendar month
  turnover    the median of close x volume over the trailing 63 sessions,
              counting every session the symbol has a row
  listed      n_days >= 30 of those 63
  rank        adv_rank by that median, descending; top100/250/500 flags
  liquid      median turnover >= Rs 1 crore

On the 2026-04-30 and 2026-05-29 rebalances the median and n_days match the
seed on every one of 2,286 and 2,307 names, to the rupee. (tests/
test_pit_universe.py pins the rule; the 2026-06-25 rebalance differs on 3
names whose prints decision 0088 corrected.)

ONE DELIBERATE DIFFERENCE. The seed keeps some ETFs (GOLD1, TATSILV, ...) and
drops others (SILVERBEES, NIFTYBEES); there is no rule in that. This
extension follows the project's declared one, decision 0040: only company
equity, ISIN beginning INE. Measured: about 6 of the 500 differ at the
boundary of the seed's last rebalances.

WHAT IT NEVER CHANGES. The first extended rebalance is the first month-end
AFTER 2026-10-01, the CONFIRM grid's last session. Every session up to it
keeps exactly the membership it had, so exp_005's grid (whose manifest hashes
the universe array) and every registered result reproduce unchanged.

A month's rebalance is written only once a session of a LATER month exists:
"the last session of September" is not known on 29 September.

    RESEARCH_ENV=prod .venv/bin/python -m src.warehouse.pit_universe
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import SEED, research_db, warehouse_dir  # noqa: E402

SEED_FILE = SEED / "pit_universe.parquet"
#: The CONFIRM grid's last session (exp_005, exp_006 training). Rebalances on or
#: before it come from the seed only.
EXTEND_AFTER = date(2026, 10, 1)
WINDOW, MIN_DAYS, LIQUID_RS = 63, 30, 1e7
COLS = ["rebal_date", "symbol", "n_days", "med_turnover", "adv_rank", "top100", "top250", "top500", "liquid"]


def out_path(env: str | None = None) -> Path:
    return warehouse_dir(env) / "pit_universe_ext.parquet"


def month_ends(sessions: list[date], after: date = EXTEND_AFTER) -> list[date]:
    """The last session of each calendar month that is over — a later month's
    session exists — and falls after `after`. Pure, so the rule is testable."""
    out = []
    for a, b in zip(sessions, sessions[1:], strict=False):
        if (a.year, a.month) != (b.year, b.month) and a > after:
            out.append(a)
    return out


def rebalance_sql(spine_glob: str, window_from: date, rebal: date, equity_symbols_sql: str) -> str:
    """One rebalance, in the seed's columns."""
    return f"""
        WITH m AS (
            SELECT UPPER(TRIM(symbol)) AS symbol, count(*) AS n_days, median(close * volume) AS med_turnover
            FROM read_parquet('{spine_glob}', hive_partitioning=true)
            WHERE CAST(date AS DATE) BETWEEN DATE '{window_from}' AND DATE '{rebal}'
              AND UPPER(TRIM(symbol)) IN ({equity_symbols_sql})
            GROUP BY 1),
        r AS (SELECT *, row_number() OVER (ORDER BY med_turnover DESC, symbol) AS adv_rank
              FROM m WHERE n_days >= {MIN_DAYS} AND med_turnover IS NOT NULL)
        SELECT DATE '{rebal}' AS rebal_date, symbol, n_days, med_turnover, adv_rank,
               CAST(adv_rank <= 100 AS INTEGER) AS top100, CAST(adv_rank <= 250 AS INTEGER) AS top250,
               CAST(adv_rank <= 500 AS INTEGER) AS top500, CAST(med_turnover >= {LIQUID_RS} AS INTEGER) AS liquid
        FROM r"""


#: Company equity only (0040): a symbol whose security carries an INE ISIN.
EQUITY_SYMBOLS = """
    SELECT UPPER(TRIM(h.symbol)) FROM symbol_history h JOIN security_master s USING (security_id)
    WHERE s.isin LIKE 'INE%'
    UNION SELECT UPPER(TRIM(canonical_symbol)) FROM security_master WHERE isin LIKE 'INE%'"""


@dataclass
class Result:
    rebalances: list[date]
    rows: int

    def render(self) -> str:
        if not self.rebalances:
            return f"PIT UNIVERSE: no rebalance after {EXTEND_AFTER} yet; the seed's last carries forward"
        return (f"PIT UNIVERSE: {len(self.rebalances)} extended rebalance(s) "
                f"{self.rebalances[0]} .. {self.rebalances[-1]}, {self.rows:,} rows")


def build(env: str | None = None) -> Result:
    import duckdb

    spine = str(warehouse_dir(env) / "price_spine" / "**" / "*.parquet")
    out = out_path(env)
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        sessions = [r[0] for r in con.execute(
            f"SELECT DISTINCT CAST(date AS DATE) FROM read_parquet('{spine}', hive_partitioning=true) ORDER BY 1"
        ).fetchall()]
        rebs = month_ends(sessions)
        parts = []
        for r in rebs:
            win = [d for d in sessions if d <= r][-WINDOW:]
            parts.append(rebalance_sql(spine, win[0], r, EQUITY_SYMBOLS))
        if not parts:
            if out.exists():
                out.unlink()
            return Result([], 0)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".parquet.partial")
        con.execute(f"COPY ({' UNION ALL '.join(parts)} ORDER BY rebal_date, adv_rank) TO '{tmp}' (FORMAT PARQUET)")
        tmp.replace(out)
        n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    finally:
        con.close()
    return Result(rebs, n)


def source_sql(env: str | None = None) -> str:
    """The universe every forward-running reader takes: the seed's rebalances
    up to EXTEND_AFTER, then this extension's. One relation, the seed's columns."""
    cols = ", ".join(["CAST(rebal_date AS DATE) AS rebal_date", *COLS[1:]])
    seed = f"SELECT {cols} FROM read_parquet('{SEED_FILE}')"
    ext = out_path(env)
    if not ext.exists():
        return seed
    return (f"{seed} WHERE CAST(rebal_date AS DATE) <= DATE '{EXTEND_AFTER}' "
            f"UNION ALL SELECT {cols} FROM read_parquet('{ext}')")


def main() -> int:
    print(" ", build().render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
