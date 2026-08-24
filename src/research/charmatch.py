"""charmatch.py — the characteristic-matched benchmark. Plan 2 §5.3.

WHY THIS MOVED TO THE FRONT OF THE QUEUE.

It is specified as one of six benchmarks in Phase 5. Decision 0028 promoted it to
a **precondition**: the plausible effect bound now scales with horizon, every
horizon in the primary grid is UNDERPOWERED against it, and `design.py` refuses a
study whose horizons are all blind. So no Track D study can be registered at all
until the detection floor comes down, and matching is the largest available lever
on it — a crude size-quintile match alone cut cohort SD 8.55% -> 5.91% and the
floor 1.52% -> 1.05%, a 31% power gain from one dimension.

WHY IT IS ALSO THE RIGHT COMPARISON, INDEPENDENT OF POWER.

Index-relative returns credit an institution with beta it did not create. The
0.5%-of-volume disclosure threshold is easiest to cross in thin, volatile names,
so this event set is skewed toward small and volatile by construction; comparing
it to a cap-weighted index measures the skew. DGTW matching compares each event
stock to stocks that look like it.

And matching made the 2026-08-16 result WORSE, not better: the 1-month estimate
moved from -0.54% to -1.02%. A control that only ever flatters the hypothesis is
not a control.

THE MISSING DIMENSION, DECLARED RATHER THAN SKIPPED.

`benchmarks.yml` specifies size x momentum x volatility x **industry**, with
industry sourced from `sector_history` — which is Phase 3 work and does not
exist. The config's own `degrade_order` drops industry first, so this builds the
three dimensions that are computable today and records `industry` as UNAVAILABLE
on every match rather than quietly producing a 3-way match labelled as a 4-way
one. A silently degraded match is worse than a declared one.

BOOK-TO-MARKET is absent for a different and permanent reason: coverage begins at
28 symbols in 2021 and ~2,200 from 2022, so for sixteen of twenty years there is
no stock-level book value. It is a 2022+ sensitivity, never a headline dimension.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import duckdb
import yaml

from src.common.paths import CONFIGS, warehouse_dir

PRODUCED_BY = "src.research.charmatch:build_panel"

#: Dimensions that exist today. `industry` is specified in benchmarks.yml and is
#: NOT here because sector_history is unbuilt — see the module docstring.
LIVE_DIMENSIONS: tuple[str, ...] = ("size", "momentum", "volatility")
MISSING_DIMENSIONS: tuple[str, ...] = ("industry",)


class CharMatchError(RuntimeError):
    """The panel cannot be built or does not satisfy its own spec."""


@lru_cache(maxsize=1)
def spec() -> dict:
    cfg = yaml.safe_load((CONFIGS / "benchmarks.yml").read_text())
    for b in cfg["benchmarks"]:
        if b["id"] == "CHAR_MATCHED":
            return b["construction"]
    raise CharMatchError("benchmarks.yml has no CHAR_MATCHED entry")


@dataclass(frozen=True, slots=True)
class PanelResult:
    rows: int
    rebalances: int
    symbols: int
    path: Path
    median_cell_size: float
    thin_cell_share: float

    def render(self) -> str:
        return (
            f"  rows            {self.rows:>10,}\n"
            f"  rebalance dates {self.rebalances:>10,}\n"
            f"  symbols         {self.symbols:>10,}\n"
            f"  median cell     {self.median_cell_size:>10.1f} names\n"
            f"  thin cells      {self.thin_cell_share:>10.1%} below the "
            f"{spec()['min_names_per_cell']}-name floor"
        )


def _panel_sql(spine: str, buckets: int) -> str:
    """Monthly characteristic panel, computed in TRADING SESSIONS not calendar days.

    Every lag below counts sessions off the symbol's own price history. Calendar
    arithmetic would silently vary the lookback with holidays and suspensions,
    and a stock that stopped trading for a month would get a momentum figure
    spanning a different amount of market activity than its peers.
    """
    return f"""
    WITH px AS (
        SELECT symbol, date, close, volume, close * volume AS turnover,
               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date) AS i
        FROM read_parquet('{spine}')
        WHERE close > 0 AND volume IS NOT NULL
    ),
    r AS (
        SELECT *, close / NULLIF(LAG(close) OVER (PARTITION BY symbol ORDER BY date), 0) - 1 AS ret
        FROM px
    ),
    feat AS (
        SELECT symbol, date, i, close,
            -- SIZE: 20-session median turnover. benchmarks.yml allows market cap
            -- "or med_turnover where shares unavailable"; shares outstanding is
            -- not in the spine, so turnover is the live proxy for all rows.
            median(turnover) OVER (PARTITION BY symbol ORDER BY i
                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS adv20,
            -- VOLATILITY: 21-session return dispersion.
            stddev_samp(ret) OVER (PARTITION BY symbol ORDER BY i
                ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS vol21,
            -- MOMENTUM: 12-1. The one-month gap is not decoration — including
            -- the most recent month would load short-term REVERSAL into a
            -- momentum bucket, and confounds.yml already lists reversal as a
            -- blocking confound for exactly this reason.
            LAG(close, 21) OVER (PARTITION BY symbol ORDER BY i)
                / NULLIF(LAG(close, 252) OVER (PARTITION BY symbol ORDER BY i), 0) - 1 AS mom12_1,
            COUNT(*) OVER (PARTITION BY symbol ORDER BY i
                ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS hist
        FROM r
    ),
    -- THE REBALANCE CALENDAR IS THE MARKET'S, NOT EACH SYMBOL'S.
    --
    -- BUG FIXED 2026-08-23. This originally took the last session of each month
    -- PER SYMBOL. Symbols stop trading on different days — suspensions,
    -- delistings, illiquidity — so that scattered the panel across 2,765
    -- distinct "rebalance dates" instead of ~247 month-ends, leaving ~124
    -- symbols on each. Quintiles computed on 124 names across 125 cells put
    -- roughly ONE name in a cell, and a cell of one is not a benchmark, it is
    -- the stock itself. Median cell size came out at 7 with 63% of cells below
    -- the 10-name floor.
    --
    -- The rebalance calendar must be common to every symbol, or the cells are
    -- not cross-sections at all.
    cal AS (
        SELECT max(date) AS rebalance_date
        FROM (SELECT DISTINCT date FROM px)
        GROUP BY substr(date, 1, 7)
    ),
    month_end AS (
        SELECT f.symbol, f.date, f.adv20, f.vol21, f.mom12_1
        FROM feat f
        JOIN cal c ON c.rebalance_date = f.date
        WHERE f.hist >= 252 AND f.adv20 > 0 AND f.vol21 > 0 AND f.mom12_1 IS NOT NULL
    )
    SELECT date AS rebalance_date, symbol, adv20, vol21, mom12_1,
        NTILE({buckets}) OVER (PARTITION BY date ORDER BY adv20)   AS size_q,
        NTILE({buckets}) OVER (PARTITION BY date ORDER BY mom12_1) AS mom_q,
        NTILE({buckets}) OVER (PARTITION BY date ORDER BY vol21)   AS vol_q
    FROM month_end
    """


def build_panel(env: str | None = None, buckets: int = 5) -> PanelResult:
    """Build and persist the monthly characteristic panel.

    Quintiles are assigned INDEPENDENTLY per dimension and then intersected,
    which is what `benchmarks.yml` specifies (`sort: independent_then_intersect`)
    and what DGTW does. Sequential/nested sorting would make the second dimension
    conditional on the first and the cells would stop being comparable across
    dates as the cross-sectional distribution moved.
    """
    # THE ADJUSTED SPINE, NOT THE RAW ONE. `universe.yml` sets
    # `research_prices: adjusted`, and this module computes momentum and
    # volatility — both of which are RETURNS, and a return on raw prices reads a
    # 1:2 split as -50%.
    #
    # CORRECTED 2026-08-23. The first version read `price_spine` (raw), so every
    # quintile the panel assigned was contaminated by unadjusted corporate
    # actions, and so was every measurement built on it.
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    if not list((warehouse_dir(env) / "price_spine_adj").glob("**/*.parquet")):
        raise CharMatchError(
            "no ADJUSTED price spine. Run `python -m src.warehouse.spine` first. "
            "The raw spine is not a substitute: research_prices is `adjusted` in "
            "universe.yml, and raw and adjusted differ on 17.1% of rows."
        )

    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false;")
    out = warehouse_dir(env) / "char_panel"
    out.mkdir(parents=True, exist_ok=True)

    con.execute(f"CREATE OR REPLACE VIEW panel AS {_panel_sql(spine, buckets)}")
    con.execute(
        f"COPY (SELECT * FROM panel) TO '{out}' "
        f"(FORMAT PARQUET, PARTITION_BY (rebalance_date), OVERWRITE_OR_IGNORE 1)"
    )

    glob = f"{out}/**/*.parquet"

    # STEP 1.9: "every table written registers its artefact and edges". This
    # module wrote 330,861 rows and registered nothing for two days — found by
    # audit 2026-08-23, which is exactly how long an unregistered artefact stays
    # invisible. Addressed by DATA, not bytes (decision 0030).
    from src.governance import provenance as prov

    panel_cols = ("rebalance_date", "symbol", "adv20", "vol21", "mom12_1",
                  "size_q", "mom_q", "vol_q")
    digest = prov.data_checksum(con, glob, panel_cols)
    spine_hash = None
    try:
        spine_hash = prov.data_checksum(
            con, spine, ("symbol", "date", "open", "high", "low", "close", "volume", "_y"))
    except Exception:  # noqa: BLE001 - a missing parent must not block the build
        pass
    prov.register(
        prov.Artefact(digest, "FEATURE", "warehouse:char_panel", PRODUCED_BY,
                      params={"buckets": buckets, "dimensions": list(LIVE_DIMENSIONS),
                              "missing_dimensions": list(MISSING_DIMENSIONS),
                              "addressing": "data_checksum"}),
        parents=[(spine_hash, "input")] if spine_hash else (),
        env=env,
    )

    rows, dates, syms = con.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT rebalance_date), COUNT(DISTINCT symbol)"
        f" FROM read_parquet('{glob}')"
    ).fetchone()

    floor = spec()["min_names_per_cell"]
    med, thin = con.execute(
        f"""SELECT median(n), avg(CASE WHEN n < {floor} THEN 1.0 ELSE 0.0 END) FROM (
              SELECT rebalance_date, size_q, mom_q, vol_q, COUNT(*) AS n
              FROM read_parquet('{glob}') GROUP BY 1,2,3,4)"""
    ).fetchone()

    return PanelResult(rows, dates, syms, out, float(med or 0), float(thin or 0))


def main() -> int:
    print("CHARACTERISTIC PANEL  (Plan 2 §5.3, decision 0028 precondition)")
    print(f"  dimensions live   : {', '.join(LIVE_DIMENSIONS)}")
    print(f"  dimensions MISSING: {', '.join(MISSING_DIMENSIONS)} "
          f"(sector_history is Phase 3; degraded per benchmarks.yml degrade_order)")
    r = build_panel()
    print(r.render())
    print(f"\n  -> {r.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
