"""benchmarks.py — the daily benchmark panel. Plan 2 §5, Plan 3 step 6.3.

WHY THIS EXISTS. `benchmarks.yml` has specified six benchmarks since 2026-08-18
and every outcome row is supposed to carry a return against all six. Nothing
built any of them. `deal_forward_outcomes` and `outcome_benchmark_returns` both
hold 0 rows, and `charmatch.py` — 251 lines implementing the primary one — is
imported by nothing; step 5.6's own status note says the only test that mentions
it reads its source as text and never runs it.

WHAT IS ACTUALLY BUILDABLE, MEASURED RATHER THAN ASSUMED. Five of the six are
daily series and belong here. CHAR_MATCHED is per-event and lives in
`outcomes.py`, because a characteristic match has no meaning without an event to
match.

  NIFTY500_TR was the sixth and was UNBUILDABLE for 33 days. benchmarks.yml
  pointed it at `warehouse.benchmark_n500tr`, a cap-weighted-plus-dividend
  construction that no code in this repository ever wrote, on the stated
  ground that "niftyindices' own TRI series is not free-fetchable". That was
  falsified on 2026-09-15: the host serves the official series to a POST, and
  since 2026-09-19 it is collected nightly. The benchmark the config calls its
  `broad_market_headline` is now the OFFICIAL total-return index — the only
  series in this panel whose `total_return: true` the data actually carries.
  Decision 0077.

TWO CLAIMS IN THE CONFIG THAT THE DATA DOES NOT SUPPORT.

  1. NIFTY50_TR is declared `total_return: true`. The only NIFTY50 series held
     is `global_indices_daily`, which is OHLCV with no dividend leg and no
     adjusted close. It is a PRICE index. Indian large-cap dividend yield runs
     ~1.2%/yr, so using it as a total-return benchmark understates the
     benchmark and flatters any long-side result by roughly that much per year —
     1.2pp at the twelve-month primary horizon, against a plausible-effect bound
     of 6pp. That is a fifth of the bound, from a single mislabelled column.
     The id keeps its config name; `total_return_verified` is False and the
     shortfall is reported.

  2. SMALLCAP_SYNTH specifies `weighting: free_float_proxy_mcap`. No market-cap
     column exists in `pit_universe` — it carries `med_turnover` and rank only.
     Built equal-weighted and declared, because a turnover-weighted series
     labelled as cap-weighted is the same class of error as 1.

COVERAGE IS NOT UNIFORM AND THE GAPS ARE AT BOTH ENDS. The SEED index sources
stop at 2026-07-08 and 2026-06-25 while the price spine runs months past them,
so recent events have no NIFTY50_TR or MIDCAP benchmark; NIFTY50 starts
2007-09-17, so the first twenty months of deals have none either. NIFTY500_TR
is the exception at both ends — 1995-01-01 to yesterday, refreshed nightly,
because it is collected rather than inherited. Each benchmark reports its own
window and `outcomes.py` writes a row only where the benchmark actually covers
the event.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import yaml

from src.common.paths import COLLECTED, CONFIGS, SEED, warehouse_dir

BENCHMARKS_YML = CONFIGS / "benchmarks.yml"
PRODUCED_BY = "src.warehouse.benchmarks:build"

#: Written by this module, one daily close series per benchmark.
PANEL = "benchmark_daily"

#: Declared in benchmarks.yml, sourced from something that does not exist.
#: Named here so an absence is a declared constant rather than a silent gap.
#:
#: EMPTY SINCE 2026-09-19 (0077). NIFTY500_TR was its only entry and left it
#: when `collected:index_tri` landed. The machinery stays: the next benchmark
#: that cannot be built must be declared here and reported, not quietly
#: dropped from the panel — which is the failure this constant was written
#: for and would be the failure again if it were deleted for being empty.
UNAVAILABLE: dict[str, str] = {}

#: Built per event, not as a daily series — see `src/research/outcomes.py`.
PER_EVENT: tuple[str, ...] = ("CHAR_MATCHED",)


class BenchmarkError(RuntimeError):
    """A benchmark cannot be built, or does not satisfy its own spec."""


def spec() -> dict:
    return yaml.safe_load(BENCHMARKS_YML.read_text())


def declared_ids() -> tuple[str, ...]:
    return tuple(b["id"] for b in spec()["benchmarks"])


@dataclass(frozen=True, slots=True)
class Series:
    benchmark_id: str
    rows: int
    first: str
    last: str
    official: bool
    #: False wherever the config claims a property the data does not carry.
    spec_honoured: bool
    deviation: str = ""

    def render(self) -> str:
        tag = "official" if self.official else "constructed"
        line = (f"  {self.benchmark_id:<17} {self.rows:>6,} rows  "
                f"{self.first} .. {self.last}  {tag}")
        if not self.spec_honoured:
            line += f"\n      DEVIATES FROM SPEC: {self.deviation}"
        return line


def _nifty50_sql() -> str:
    """Price index. See docstring claim 1 — this is not the total return the
    config declares, and nothing in the seed carries the dividend leg."""
    return f"""
      SELECT 'NIFTY50_TR' AS benchmark_id, CAST(date AS DATE) AS date, close
      FROM read_parquet('{SEED}/global_indices_daily.parquet')
      WHERE symbol = 'NIFTY50' AND close > 0
    """


def _nifty500_tri_sql() -> str:
    """The OFFICIAL NIFTY 500 Total Returns Index — `collected:index_tri`,
    archived daily from niftyindices by `src/archive/index_tri.py`.

    `tri`, NEVER `ntr`. NTR_Value is the net-of-withholding series and the host
    did not compute it before ~2014: it is NULL on 4,957 of 7,860 rows. Reading
    it here would not fail — it would silently start the headline benchmark
    nineteen years late, which is the class of error this module's docstring is
    otherwise about.
    """
    return f"""
      SELECT 'NIFTY500_TR' AS benchmark_id, date, tri AS close
      FROM read_parquet('{COLLECTED}/index_tri/index_tri.parquet')
      WHERE index_key = 'NIFTY500' AND tri > 0
    """


def _midcap_sql() -> str:
    return f"""
      SELECT 'NIFTY_MIDCAP100' AS benchmark_id, CAST(date AS DATE) AS date, close
      FROM read_parquet('{SEED}/indices_data.parquet')
      WHERE name = 'NIFTY MIDCAP 100' AND close > 0
    """


def _constructed_sql(bid: str, spine: str, rank_lo: int, rank_hi: int) -> str:
    """An equal-weighted, point-in-time, delisting-aware portfolio.

    DELISTING-AWARE IS NOT A LABEL HERE. The daily return is the mean of the
    returns of the names that ACTUALLY TRADED both sessions. A name that stops
    trading contributes its last real return and then leaves, rather than being
    back-filled or dropped from history — which is the survivorship error the
    whole project is about (0052).

    Membership is taken from the most recent `pit_universe` rebalance at or
    before the date, so the portfolio holds what it would have held that day.
    """
    return f"""
      WITH px AS (
        SELECT symbol, CAST(date AS DATE) AS date, close,
               LAG(close) OVER (PARTITION BY symbol ORDER BY date) AS prev
        FROM read_parquet('{spine}') WHERE close > 0
      ),
      pu AS (
        SELECT symbol, CAST(rebal_date AS DATE) AS rebal_date, adv_rank
        FROM read_parquet('{SEED}/pit_universe.parquet')
        WHERE adv_rank BETWEEN {rank_lo} AND {rank_hi}
      ),
      member AS (
        SELECT p.symbol, p.date, p.close / p.prev - 1 AS ret
        FROM px p
        WHERE p.prev > 0
          AND EXISTS (
            SELECT 1 FROM pu
            WHERE pu.symbol = p.symbol
              AND pu.rebal_date = (
                SELECT MAX(r.rebal_date) FROM pu r
                WHERE r.symbol = p.symbol AND r.rebal_date <= p.date))
      ),
      daily AS (SELECT date, avg(ret) AS ret FROM member GROUP BY 1),
      -- Chain the daily equal-weighted returns into a level series so every
      -- benchmark in the panel is a `close` and the horizon arithmetic is one
      -- expression rather than two.
      lvl AS (
        SELECT date, exp(sum(ln(1 + ret)) OVER (ORDER BY date)) * 1000 AS close
        FROM daily WHERE ret > -1
      )
      SELECT '{bid}' AS benchmark_id, date, close FROM lvl
    """


def build(env: str | None = None) -> list[Series]:
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false;")

    parts = {
        "NIFTY50_TR": _nifty50_sql(),
        "NIFTY500_TR": _nifty500_tri_sql(),
        "NIFTY_MIDCAP100": _midcap_sql(),
        # rank_range from benchmarks.yml, read rather than restated.
        "SMALLCAP_SYNTH": None,
        "EW_TOP500": None,
    }
    by_id = {b["id"]: b for b in spec()["benchmarks"]}
    lo, hi = by_id["SMALLCAP_SYNTH"]["construction"]["rank_range"]
    parts["SMALLCAP_SYNTH"] = _constructed_sql("SMALLCAP_SYNTH", spine, lo, hi)
    parts["EW_TOP500"] = _constructed_sql("EW_TOP500", spine, 1, 500)

    # EACH BRANCH IS WRAPPED. A `WITH` clause is only legal at the head of a
    # statement, so a CTE-bearing branch after a UNION ALL is a parser error.
    union = "\nUNION ALL\n".join(f"SELECT * FROM ({q})" for q in parts.values())
    out = warehouse_dir(env) / PANEL
    out.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"COPY ({union}) TO '{out}' "
        f"(FORMAT PARQUET, PARTITION_BY (benchmark_id), OVERWRITE_OR_IGNORE 1)")

    glob = f"{out}/**/*.parquet"
    rows = con.execute(f"""
        SELECT benchmark_id, COUNT(*), MIN(date), MAX(date)
        FROM read_parquet('{glob}') GROUP BY 1 ORDER BY 1""").fetchall()
    if len(rows) != len(parts):
        raise BenchmarkError(
            f"wrote {len(rows)} benchmark(s) from {len(parts)} definitions — "
            f"a panel that silently drops a benchmark is worse than one that "
            f"declares it missing")

    deviations = {
        "NIFTY50_TR": ("declared total_return: true in benchmarks.yml; the only "
                       "NIFTY50 series held is a PRICE index with no dividend "
                       "leg, understating the benchmark by ~1.2%/yr"),
        "SMALLCAP_SYNTH": ("declared weighting: free_float_proxy_mcap; no market "
                           "cap exists in pit_universe, so built equal-weighted"),
    }
    return [Series(bid, n, str(a), str(b),
                   bool(by_id[bid].get("official", False)),
                   bid not in deviations, deviations.get(bid, ""))
            for bid, n, a, b in rows]


def main() -> int:
    print("BENCHMARK PANEL — Plan 2 §5, five daily series")
    series = build()
    for s in series:
        print(s.render())
    print()
    for bid in PER_EVENT:
        print(f"  {bid:<17} per-event, built in src/research/outcomes.py")
    for bid, why in UNAVAILABLE.items():
        print(f"  {bid:<17} UNAVAILABLE")
        print(f"      {why}")
    declared = set(declared_ids())
    covered = {s.benchmark_id for s in series} | set(PER_EVENT) | set(UNAVAILABLE)
    missing = declared - covered
    if missing:
        raise BenchmarkError(f"benchmarks.yml declares {sorted(missing)} and this "
                             f"module neither builds nor declares them")
    print(f"\n  {len(series)} daily + {len(PER_EVENT)} per-event + "
          f"{len(UNAVAILABLE)} unavailable = {len(declared)} declared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
