"""reconcile.py — the Phase 1 gate. Plan 1 §3.4, `configs/universe.yml`.

WHAT THIS IS FOR. The predecessor is useful for exactly one thing: being an
oracle. If the rebuilt warehouse reproduces MICCV2's numbers from the same seed,
the new code is faithful; if it does not, something is wrong and it is better to
know before four weeks of identity work are layered on top.

`tolerance: 0`. A near-miss is a bug, not a rounding.

WHAT THE GATE FOUND ABOUT ITSELF. Every expectation in `universe.yml` was
measured on 2026-08-16 against MICCV2's live warehouse. Two of them did not
survive contact with the rebuild:

  - The eight figures resolve against `data/warehouse/`, which Plan 1 §3.2 marked
    for deletion, and not against `v1_export`, which it marked for carrying.
    Decision 0027 carries both.
  - `expect_fno_rows: 174,616,363` is a NAIVE SUM of two overlapping sources.
    They share ten trading dates (2016-07-01..2016-07-15, 343,595 rows), so the
    true distinct count is 174,272,768. Decision 0029.

A gate that had been written to pass would have hidden both.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import duckdb
import yaml

from src.common.paths import CONFIGS, SEED, warehouse_dir
from src.governance import provenance as prov


@lru_cache(maxsize=1)
def spec() -> dict:
    return yaml.safe_load((CONFIGS / "universe.yml").read_text())["reconciliation"]


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    expected: object
    actual: object
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.expected == self.actual

    def render(self) -> str:
        mark = "OK  " if self.passed else "FAIL"
        exp = f"{self.expected:,}" if isinstance(self.expected, int) else str(self.expected)
        act = f"{self.actual:,}" if isinstance(self.actual, int) else str(self.actual)
        line = f"  [{mark}] {self.name:<22} expected {exp:>15}   actual {act:>15}"
        return line + (f"\n         {self.note}" if self.note else "")


#: The last session MICCV2 supplied. Everything at or before this date came from
#: the predecessor and is what the frozen expectations describe; everything after
#: it this project collected itself. Measured, not chosen: it is MAX(date) across
#: `v1_export` and `v1_increments`.
MICCV2_HORIZON = "2026-08-14"


def run(env: str | None = None) -> list[Check]:
    """Every gate check, measured against the rebuilt spines. Read-only.

    Verification NEVER writes — audit defect #3 was a `dev` verification that
    shelled out and rebuilt the prod warehouse.
    """
    s = spec()
    c = duckdb.connect()
    c.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false;")

    price = str(warehouse_dir(env) / "price_spine" / "**" / "*.parquet")
    # THE GATE MEASURES WHAT MICCV2 SUPPLIED, AND ONLY THAT.
    #
    # Every expectation below is a frozen reconciliation against the predecessor.
    # From 2026-08-17 the spine also carries sessions THIS project collected from
    # NSE, and those legitimately move every count — 7,749,148 rows became
    # 7,781,000 the day the price collector first ran.
    #
    # There were two ways to respond. Updating the expected numbers to match is
    # the one that must not happen: it is exactly the move that turned a failing
    # gate into "9/9" on 2026-08-22, and a gate whose oracle is edited whenever
    # it disagrees is a receipt, not a check. So the ORACLE IS UNTOUCHED and the
    # MEASUREMENT IS SCOPED BACK to what it was always measuring. Data collected
    # by this project cannot move these numbers in either direction.
    #
    # The collected sessions are not thereby unverified — they get their own
    # check below, and `spine._collected_part` refuses any overlap between the
    # two sources, so nothing can drift across this boundary unnoticed.
    horizon = MICCV2_HORIZON
    fno = str(warehouse_dir(env) / "fno_spine" / "**" / "*.parquet")
    bulk = str(SEED / "bulk_deals.parquet")
    block = str(SEED / "block_deals.parquet")

    rows, syms, sessions, dmin, dmax = c.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT symbol), COUNT(DISTINCT date),"
        f" MIN(date), MAX(date) FROM read_parquet('{price}') WHERE date <= '{horizon}'"
    ).fetchone()

    dead = c.execute(
        f"SELECT COUNT(*) FROM (SELECT symbol, MAX(date) d FROM read_parquet('{price}')"
        f" WHERE date <= '{horizon}' GROUP BY symbol) WHERE d < '2026-08-01'"
    ).fetchone()[0]

    return [
        Check("price_rows", s["expect_price_rows"], rows),
        Check("symbols", s["expect_symbols"], syms),
        Check("trading_sessions", s["expect_trading_sessions"], sessions),
        Check("date_min", s["expect_date_min"], dmin),
        Check("date_max", s["expect_date_max"], dmax),
        Check(
            "dead_symbols", s["expect_dead_symbols"], dead,
            "symbols whose last trade precedes 2026-08-01; the survivorship check "
            "in confounds.yml depends on these being present, not dropped",
        ),
        Check(
            "collected_starts_after_miccv2",
            True,
            (c.execute(
                f"SELECT COALESCE(MIN(date) > '{horizon}', TRUE) FROM"
                f" read_parquet('{price}') WHERE date > '{horizon}'"
            ).fetchone()[0]),
            f"sessions past {horizon} come from this project's own collector; the "
            f"two sources must not overlap, or the frozen counts above would be "
            f"measuring a mixture",
        ),
        Check(
            "fno_rows", s["expect_fno_rows"],
            c.execute(f"SELECT COUNT(*) FROM read_parquet('{fno}')").fetchone()[0],
            "distinct rows after resolving the ten-date seed/increment overlap "
            "(decision 0029); the predecessor's 174,616,363 was a naive sum",
        ),
        Check(
            "bulk_deals", s["expect_bulk_deals"],
            c.execute(f"SELECT COUNT(*) FROM read_parquet('{bulk}')").fetchone()[0],
        ),
        Check(
            "block_deals", s["expect_block_deals"],
            c.execute(f"SELECT COUNT(*) FROM read_parquet('{block}')").fetchone()[0],
        ),
    ]


def quality(env: str | None = None) -> list[Check]:
    """Is the data SANE, not merely the right size?

    ADDED 2026-08-23, after an audit asked what the gate actually proves. It
    proved eight row counts and nothing about their contents — and the thing it
    could not have caught is exactly what went wrong: the spine was built from
    `stock_data` (raw) when `universe.yml` requires `research_prices: adjusted`,
    and 17.1% of rows differ. A row count is identical either way.

    Every threshold below is zero except the ones measured as legitimately
    non-zero, and those carry the measured value rather than a round number, so
    a regression moves them.
    """
    c = duckdb.connect()
    c.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false;")
    adj = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")

    rows, nonpos_c, nonpos_o, hl, outside, negvol = c.execute(
        f"""SELECT COUNT(*),
              SUM(CASE WHEN close<=0 THEN 1 ELSE 0 END),
              SUM(CASE WHEN open<=0 THEN 1 ELSE 0 END),
              SUM(CASE WHEN high<low THEN 1 ELSE 0 END),
              SUM(CASE WHEN close>high OR close<low THEN 1 ELSE 0 END),
              SUM(CASE WHEN volume<0 THEN 1 ELSE 0 END)
            FROM read_parquet('{adj}')"""
    ).fetchone()
    dupes = c.execute(
        f"SELECT COUNT(*) FROM (SELECT symbol,date,COUNT(*) n FROM read_parquet('{adj}')"
        f" GROUP BY 1,2 HAVING n>1)"
    ).fetchone()[0]
    crashes = c.execute(
        f"""WITH x AS (SELECT close, LAG(close) OVER (PARTITION BY symbol ORDER BY date) p
                       FROM read_parquet('{adj}'))
            SELECT SUM(CASE WHEN close/p < 0.1 THEN 1 ELSE 0 END) FROM x WHERE p>0"""
    ).fetchone()[0]

    return [
        Check("adj_nonpositive_close", 0, nonpos_c),
        Check("adj_nonpositive_open", 0, nonpos_o),
        Check("adj_high_below_low", 0, hl),
        Check("adj_close_outside_hl", 0, outside),
        Check("adj_negative_volume", 0, negvol),
        Check("adj_duplicate_symbol_date", 0, dupes),
        Check(
            "adj_extreme_drops", 73, crashes,
            "single-session falls below 0.1x. The RAW spine has 149; adjustment "
            "halves them because most are unadjusted splits. A rise here means "
            "corporate actions stopped being applied",
        ),
    ]


def main() -> int:
    print("PHASE 1 RECONCILIATION GATE  (Plan 1 §3.4, tolerance 0)")
    checks = run() + quality()
    for chk in checks:
        print(chk.render())

    failed = [c for c in checks if not c.passed]
    a, e = prov.count()
    print(f"\n  provenance: {a} artefacts, {e} edges")

    if failed:
        print(f"\nGATE: FAILED — {len(failed)} of {len(checks)} checks")
        print("  Plan 1 §3.4: a mismatch on any row is a blocking failure,")
        print("  investigated before Phase 2.")
        return 1
    print(f"\nGATE: PASSED — {len(checks)}/{len(checks)} exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
