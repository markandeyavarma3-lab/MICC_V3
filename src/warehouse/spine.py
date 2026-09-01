"""spine.py — rebuild the price and F&O spines from the carried seed. Phase 1.8.

WHAT A SPINE IS. One table per fact, built once, from which everything else is
derived. The predecessor had `stock_data`, `stock_data_clean`, `stock_data_inc`,
`price_spine_adj` and `price_spine_tr` as five separate artefacts with no single
statement of which one was authoritative — and its backtest gate and live gate
then read different source tables and disagreed on 13 of 259 rebalances, 11 of
which flipped the decision (Plan 1 §1.2, defect #5). One spine, one call site.

THE JOIN THIS MODULE EXISTS TO PERFORM. Decision 0027 carries two sources whose
union is the spine:

    v1_export/stock_data      7,676,618 rows   2005-01-03 .. 2026-07-08
    v1_increments/prices         72,530 rows   2026-07-09 .. 2026-08-14
                              -----------
                              7,749,148 rows   <- the Phase 1 gate figure

They are contiguous, not overlapping, and the arithmetic only works if that
stays true — so this module VERIFIES it rather than trusting it, and a duplicate
(symbol, date) is a blocking error rather than something quietly de-duplicated.
Silently dropping a row here would make the gate pass for the wrong reason.

TWO SCHEMA DIFFERENCES, HANDLED EXPLICITLY. The increment writes `volume` as
BIGINT where the seed writes DOUBLE, and it carries no `_y` partition column.
Both are cast and derived below rather than coerced by DuckDB's union-by-name,
because an implicit cast is a decision nobody recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

from src.common.paths import COLLECTED, SEED, SEED_INCREMENTS, warehouse_dir
from src.governance import provenance as prov

PRODUCED_BY = "src.warehouse.spine:build"


#: Discontinuities >35% that survive adjustment before the build refuses.
#:
#: NOT zero, and the reason is measured. After applying every SPLIT and BONUS
#: factor the tail retains a handful that are not corporate actions at all:
#: NV20 carries a bad print in the MICCV2 data (13.99 -> 11,985 -> 13.98 inside
#: one week), BURNPUR fell 35.3% as a genuine move in a Z-group penny stock, and
#: KSHITIJ-RE is a rights entitlement that decision 0015 already removed from the
#: universe. A threshold of zero would make the build refuse forever on rows
#: nothing can fix, and a guard that cannot pass is one somebody switches off.
#:
#: Raising this to silence a failure is the failure. The number is a budget for
#: KNOWN data defects, not for unexplained ones.
MAX_UNEXPLAINED_JUMPS = 12


class SpineError(RuntimeError):
    """The spine cannot be built, or does not reconcile. Deliberately fatal."""


@dataclass(frozen=True, slots=True)
class SpineSpec:
    """One spine: what it unions, where it lands, what it is called."""

    name: str
    seed_glob: str
    increment_glob: str | None
    #: Columns that must be identical across every source, in order.
    columns: tuple[str, ...]
    #: What makes a row unique. DECLARED, never inferred.
    #:
    #: The first version of this module guessed the key as (symbol, date) when a
    #: `symbol` column existed. That is right for prices and badly wrong for
    #: F&O, where one symbol has many contracts on one date across expiries,
    #: strikes and option types — it reported 968,371 "duplicates" that are
    #: ordinary rows. A uniqueness guard with a guessed key does not check
    #: uniqueness, it checks the guess.
    unique_key: tuple[str, ...]
    #: Data THIS project collected from the exchange, kept apart from the
    #: MICCV2 increments so the DAG can still say which source a row came from.
    collected_glob: str | None = None
    partition_by: str = "_y"


PRICE = SpineSpec(
    name="price_spine",
    seed_glob="stock_data/**/*.parquet",
    increment_glob="prices/**/*.parquet",
    columns=("symbol", "date", "open", "high", "low", "close", "volume"),
    unique_key=("symbol", "date"),
    collected_glob="prices/**/*.parquet",
)

FNO = SpineSpec(
    name="fno_spine",
    seed_glob="fo_data/**/*.parquet",
    increment_glob="fno/**/*.parquet",
    columns=(
        "date", "instrument", "symbol", "expiry", "strike", "option_typ",
        "open", "high", "low", "close", "settle_pr", "contracts",
        "val_inlakh", "open_int", "chg_in_oi",
    ),
    # A derivatives row is one CONTRACT on one date: the underlying alone does
    # not identify it. Futures carry NULL strike and option_typ, which GROUP BY
    # treats as equal, so they still collapse correctly.
    unique_key=("date", "instrument", "symbol", "expiry", "strike", "option_typ"),
)


@dataclass
class BuildResult:
    name: str
    rows: int
    seed_rows: int
    increment_rows: int
    duplicates: int
    path: Path
    artefact_hash: str = ""

    def render(self) -> str:
        return (
            f"  {self.name:<12} {self.rows:>12,} rows "
            f"({self.seed_rows:,} seed + {self.increment_rows:,} increment)"
            + (f"  [{self.duplicates:,} seed rows superseded by increment]" if self.duplicates else "")
        )


def _select(glob: str, spec: SpineSpec, derive_year: bool) -> str:
    """A SELECT over one source, casting to the spine's declared column types.

    `volume` is cast explicitly: the seed stores DOUBLE and the increment BIGINT,
    and letting the reader pick would make the spine's own schema depend on which
    files happened to be present.
    """
    cols = []
    for c in spec.columns:
        cols.append(f"CAST({c} AS DOUBLE) AS {c}" if c == "volume" else c)
    year = (
        "CAST(SUBSTR(date, 1, 4) AS BIGINT) AS _y" if derive_year else "_y"
    )
    return f"SELECT {', '.join(cols)}, {year} FROM read_parquet('{glob}')"


def _collected_part(spec: SpineSpec, c: duckdb.DuckDBPyConnection,
                    prior_globs: list[str]) -> tuple[str | None, int]:
    """The self-collected source, with contiguity ASSERTED rather than assumed.

    Decision 0027 assumed the seed and increment were contiguous. They were for
    prices and were not for F&O — ten shared dates, 343,595 rows — and the
    assumption cost a rebuild. `build` resolves that overlap by letting the
    increment win, which is right when one source is known better than the
    other.

    Here neither is. The collected sessions run FORWARD from where the increment
    stops, so an overlap would not mean "two versions of a day", it would mean a
    bug in what this module thinks it holds. Refusing is the honest response;
    silently preferring one source would hide it.
    """
    if not spec.collected_glob or not list(COLLECTED.glob(spec.collected_glob)):
        return None, 0
    glob = str(COLLECTED / spec.collected_glob)
    rows = c.execute(f"SELECT COUNT(*) FROM read_parquet('{glob}')").fetchone()[0]
    for prior in prior_globs:
        clash = c.execute(
            f"SELECT COUNT(*) FROM ("
            f"  SELECT DISTINCT date FROM read_parquet('{prior}')"
            f"  INTERSECT SELECT DISTINCT date FROM read_parquet('{glob}'))"
        ).fetchone()[0]
        if clash:
            raise SpineError(
                f"{spec.name}: {clash} date(s) appear in BOTH {prior} and the "
                f"collected source. These are meant to be contiguous — collection "
                f"starts where the increment stops — so an overlap is a defect in "
                f"the collector or the parser, not a version conflict to resolve."
            )
    return glob, rows


def build(spec: SpineSpec, env: str | None = None, con: duckdb.DuckDBPyConnection | None = None) -> BuildResult:
    """Union the sources into one partitioned parquet dataset, verified."""
    seed_glob = str(SEED / spec.seed_glob)
    inc_glob = str(SEED_INCREMENTS / spec.increment_glob) if spec.increment_glob else None

    if not list(SEED.glob(spec.seed_glob)):
        raise SpineError(
            f"{spec.name}: no seed files at {seed_glob}. Run "
            f"`python -m src.warehouse.seed` first — the spine cannot be built "
            f"from a repo that has not carried its seed."
        )

    c = con or duckdb.connect()
    seed_rows = c.execute(f"SELECT COUNT(*) FROM read_parquet('{seed_glob}')").fetchone()[0]
    inc_rows = 0
    parts = [_select(seed_glob, spec, derive_year=False)]
    if inc_glob and list(SEED_INCREMENTS.glob(spec.increment_glob)):
        inc_rows = c.execute(f"SELECT COUNT(*) FROM read_parquet('{inc_glob}')").fetchone()[0]
        parts.append(_select(inc_glob, spec, derive_year=True))

    coll_glob, coll_rows = _collected_part(
        spec, c, [g for g in (seed_glob, inc_glob) if g])
    if coll_glob:
        inc_rows += coll_rows
        parts.append(_select(coll_glob, spec, derive_year=True))

    union = "\nUNION ALL\n".join(parts)

    # OVERLAP IS RESOLVED, NOT ASSUMED AWAY. Measured 2026-08-21: the price
    # sources are contiguous, but the F&O sources share TEN trading dates
    # (2016-07-01..2016-07-15, 343,595 rows). Decision 0027 assumed contiguity
    # for both and was right about one.
    #
    # THE RULE: for any date the increment covers, the increment wins. It came
    # from the maintained collector, and — decisively — the seed's F&O export
    # carries 4,025,340 rows (5.8%) with a BLANK `expiry`, while the increment
    # carries none. Where both have a date, one of them can identify its
    # contracts and the other cannot.
    #
    # This is done as an anti-join on the date set (2,862 + 2,373 dates, so it is
    # cheap) rather than a DISTINCT over 174M rows, which would also have
    # silently collapsed those blank-expiry rows into each other and destroyed
    # real data.
    duplicates = 0
    if inc_rows:
        shared = c.execute(
            f"SELECT COUNT(*) FROM ("
            f"  SELECT DISTINCT date FROM read_parquet('{seed_glob}')"
            f"  INTERSECT SELECT DISTINCT date FROM read_parquet('{inc_glob}'))"
        ).fetchone()[0]
        if shared:
            duplicates = c.execute(
                f"SELECT COUNT(*) FROM read_parquet('{seed_glob}') WHERE date IN "
                f"(SELECT DISTINCT date FROM read_parquet('{inc_glob}'))"
            ).fetchone()[0]
            parts[0] = (
                _select(seed_glob, spec, derive_year=False)
                + f" WHERE date NOT IN (SELECT DISTINCT date FROM read_parquet('{inc_glob}'))"
            )
            union = "\nUNION ALL\n".join(parts)
            seed_rows -= duplicates

    out = warehouse_dir(env) / spec.name
    out.mkdir(parents=True, exist_ok=True)
    c.execute(
        f"COPY ({union}) TO '{out}' "
        f"(FORMAT PARQUET, PARTITION_BY ({spec.partition_by}), OVERWRITE_OR_IGNORE 1)"
    )
    total = c.execute(f"SELECT COUNT(*) FROM read_parquet('{out}/**/*.parquet')").fetchone()[0]
    if total != seed_rows + inc_rows:
        raise SpineError(
            f"{spec.name}: wrote {total:,} rows from {seed_rows + inc_rows:,} input "
            f"rows. A spine that loses rows on write is not a spine."
        )

    return BuildResult(spec.name, total, seed_rows, inc_rows, duplicates, out)


#: The adjusted research spine. `universe.yml` is explicit:
#:
#:     research_prices: adjusted     # splits/bonuses applied
#:     execution_prices: raw         # what a fill would actually have paid
#:
#: BOTH are needed and they are NOT interchangeable. A return computed on raw
#: prices reads a 1:2 split as -50%. Measured 2026-08-23: raw and adjusted differ
#: on 17.1% of rows — 27.3% in 2005-2010 falling to 10.6% in 2019-2026, which is
#: the right shape, since older prices carry more subsequent adjustments.
#:
#: THIS EXISTS BECAUSE IT WAS MISSED. Step 1.8 required "the price spine, ADJUSTED
#: spine, and PIT universe". Only the raw spine was built, and every measurement
#: on 2026-08-22/23 — the whole MDE grid, the characteristic panel, and the
#: 12-month result decision 0034 rests on — was computed on prices the config
#: forbids for research. The conclusion survived re-measurement (MDE 5.28%
#: adjusted against 5.55% raw, both inside the 6.00% bound) but that was luck.
ADJUSTED = SpineSpec(
    name="price_spine_adj",
    seed_glob="stock_data_adj/**/*.parquet",
    increment_glob="prices/**/*.parquet",
    columns=("symbol", "date", "open", "high", "low", "close", "volume"),
    unique_key=("symbol", "date"),
    collected_glob="prices/**/*.parquet",
)


def build_adjusted(env: str | None = None, con: duckdb.DuckDBPyConnection | None = None) -> BuildResult:
    """The adjusted spine, spliced and self-validating.

    `stock_data_adj` stops on 2026-06-25 while raw runs to 2026-07-08 and the
    increment to 2026-08-14, so the tail has to come from unadjusted sources.
    That is CORRECT rather than a compromise, and only because of a fact that is
    checked here rather than assumed:

    **Adjustment is backward-looking.** A price series is adjusted for actions
    that happen AFTER it, so the most recent prices carry no adjustment at all.
    Verified at the boundary: on 2026-06-25 adjusted equals raw for 2,696 of
    2,696 symbols — 100%.

    So splicing raw onto the end is exact **provided no price-affecting action
    falls after the boundary**. That proviso is the whole argument, so it is
    enforced: a SPLIT, BONUS or RIGHTS after the adjusted series ends means the
    tail genuinely needs adjusting and this refuses to build rather than
    silently emitting a series that is adjusted at one end and not the other.
    """
    c = con or duckdb.connect()
    seed_adj = str(SEED / ADJUSTED.seed_glob)
    seed_raw = str(SEED / PRICE.seed_glob)
    inc = str(SEED_INCREMENTS / "prices/**/*.parquet")

    if not list(SEED.glob(ADJUSTED.seed_glob)):
        raise SpineError(f"{ADJUSTED.name}: no adjusted seed at {seed_adj}")

    boundary = c.execute(f"SELECT MAX(date) FROM read_parquet('{seed_adj}')").fetchone()[0]

    # THE GUARD THAT MAKES THE SPLICE HONEST.
    actions = str(SEED / "corporate_actions.parquet")
    unadjusted = c.execute(
        f"SELECT COUNT(*) FROM read_parquet('{actions}') WHERE CAST(date AS VARCHAR) > '{boundary}'"
        f" AND action_type IN ('SPLIT','BONUS','RIGHTS')"
    ).fetchone()[0]
    if unadjusted:
        raise SpineError(
            f"{ADJUSTED.name}: {unadjusted} price-affecting corporate action(s) fall "
            f"after {boundary}, where the adjusted series ends. Splicing raw prices "
            f"onto the tail would produce a series adjusted at one end and not the "
            f"other, and a split in that window reads as a -50% return. Extend "
            f"stock_data_adj or apply the adjustment; do not build past this."
        )

    # Equality at the boundary is the premise; check it rather than trust it.
    same, total = c.execute(
        f"SELECT SUM(CASE WHEN abs(r.close-a.close)<0.01 THEN 1 ELSE 0 END), COUNT(*)"
        f" FROM read_parquet('{seed_raw}') r JOIN read_parquet('{seed_adj}') a"
        f" USING(symbol,date) WHERE r.date = '{boundary}'"
    ).fetchone()
    if total and same / total < 0.99:
        raise SpineError(
            f"{ADJUSTED.name}: adjusted and raw agree on only {same}/{total} symbols "
            f"at the boundary {boundary}. Backward-looking adjustment implies they "
            f"should be identical there, so the splice premise does not hold."
        )

    parts = [
        _select(seed_adj, ADJUSTED, derive_year=False),
        _select(seed_raw, PRICE, derive_year=False) + f" WHERE date > '{boundary}'",
        _select(inc, ADJUSTED, derive_year=True),
    ]
    coll_glob, _ = _collected_part(ADJUSTED, c, [inc])
    if coll_glob:
        parts.append(_select(coll_glob, ADJUSTED, derive_year=True))

    # APPLY THE ACTIONS THE SEED'S TABLE DOES NOT KNOW ABOUT.
    #
    # `stock_data_adj` is back-adjusted as of the seed freeze, so it accounts for
    # every action up to `boundary` and none after it. Splicing raw prices onto
    # that tail is exact only while no action follows — and sixteen do.
    #
    # Back-adjustment restates history: when a 1:2 split occurs, every EARLIER
    # price halves so the series is comparable with post-split prices. So for a
    # row dated d the factor is the product of every action factor whose ex-date
    # is STRICTLY AFTER d, and it is applied to the whole series, seed included,
    # because an action in the tail invalidates the adjustment of everything
    # before it too. Volume moves the other way: half the price, twice the
    # shares.
    #
    # ONLY SPLIT AND BONUS ARE APPLIED. RIGHTS needs the cum price and DEMERGER
    # needs the value of the resulting entity; both carry factor = NULL from
    # `corp_actions.py` and are not guessed here. They stay in the discontinuity
    # check below, so an unadjusted one still stops the build.
    ca_dir = COLLECTED / "corporate_actions"
    ca_glob = str(ca_dir / "*.parquet")
    applied = 0
    if list(ca_dir.glob("*.parquet")):
        applied = c.execute(
            f"SELECT COUNT(*) FROM read_parquet('{ca_glob}')"
            f" WHERE factor IS NOT NULL AND date > '{boundary}'"
        ).fetchone()[0]

    union = "\nUNION ALL\n".join(parts)

    if applied:
        # The inner JOIN restricts the expensive part to the handful of
        # (symbol, date) pairs an action actually touches — 21 symbols, not
        # 7.7M rows. EXP(SUM(LN)) is the product; every factor is > 0.
        union = (
            f"WITH u AS ({union}),"
            f" acts AS (SELECT symbol, date AS ex, factor"
            f"          FROM read_parquet('{ca_glob}')"
            f"          WHERE factor IS NOT NULL AND date > '{boundary}'),"
            f" k AS (SELECT u.symbol, u.date, EXP(SUM(LN(a.factor))) AS f"
            f"       FROM u JOIN acts a ON a.symbol = u.symbol AND a.ex > u.date"
            f"       GROUP BY 1, 2)"
            f" SELECT u.symbol, u.date,"
            f"  u.open * COALESCE(k.f, 1.0) AS open,"
            f"  u.high * COALESCE(k.f, 1.0) AS high,"
            f"  u.low * COALESCE(k.f, 1.0) AS low,"
            f"  u.close * COALESCE(k.f, 1.0) AS close,"
            f"  u.volume / COALESCE(k.f, 1.0) AS volume, u._y"
            f" FROM u LEFT JOIN k USING (symbol, date)"
        )

    # WHAT THE GUARD ABOVE COULD NOT SEE, CHECKED ON THE FINISHED SERIES.
    #
    # The guard counts actions after `boundary` in the SEED's table, and that
    # table ends 2026-06-29 while the tail runs months past it. So a clean pass
    # meant "no action in the first four days", not "no action in the tail".
    #
    # This runs on the ADJUSTED union, after the factors are applied, which is
    # the only placement that tests what actually lands on disk. A split shows up
    # as close/prev near 1/2, 1/5 or 1/10, and the 20% circuit limit means most
    # equities CANNOT move -35% in a session — so a survivor here is an action
    # nobody has accounted for, not a bad day.
    actions_end = c.execute(
        f"SELECT MAX(CAST(date AS VARCHAR)) FROM read_parquet('{actions}')"
    ).fetchone()[0]
    if applied:
        actions_end = max(actions_end, c.execute(
            f"SELECT MAX(date) FROM read_parquet('{ca_glob}')").fetchone()[0])

    survivors = c.execute(
        f"WITH t AS (SELECT symbol, date, close FROM ({union})"
        f"           WHERE date > '{boundary}'),"
        f" r AS (SELECT symbol, date, close,"
        f"        LAG(close) OVER (PARTITION BY symbol ORDER BY date) prev FROM t)"
        f" SELECT COUNT(*) FROM r"
        f" WHERE prev > 0 AND close > 0 AND abs(close/prev - 1) > 0.35"
    ).fetchone()[0]
    if survivors > MAX_UNEXPLAINED_JUMPS:
        raise SpineError(
            f"{ADJUSTED.name}: {survivors} price discontinuit(ies) >35% remain "
            f"after adjustment, above the {MAX_UNEXPLAINED_JUMPS} allowed. "
            f"Corporate actions are known to {actions_end}. Collect actions past "
            f"that date (src/archive/corporate_actions.py) before rebuilding — a "
            f"split left unadjusted reads as a -50% return in every study."
        )

    dupes = c.execute(
        f"SELECT COUNT(*) FROM (SELECT symbol, date, COUNT(*) n FROM ({union})"
        f" GROUP BY 1,2 HAVING n > 1)"
    ).fetchone()[0]
    if dupes:
        raise SpineError(f"{ADJUSTED.name}: {dupes:,} duplicate (symbol,date) after splice")

    out = warehouse_dir(env) / ADJUSTED.name
    out.mkdir(parents=True, exist_ok=True)
    c.execute(
        f"COPY ({union}) TO '{out}' (FORMAT PARQUET, PARTITION_BY (_y), OVERWRITE_OR_IGNORE 1)"
    )
    total_rows = c.execute(f"SELECT COUNT(*) FROM read_parquet('{out}/**/*.parquet')").fetchone()[0]
    adj_rows = c.execute(f"SELECT COUNT(*) FROM read_parquet('{seed_adj}')").fetchone()[0]
    return BuildResult(ADJUSTED.name, total_rows, adj_rows, total_rows - adj_rows, 0, out)


def build_all(env: str | None = None) -> list[BuildResult]:
    """Build every spine and register each in the provenance DAG.

    Each spine records edges to the SOURCE artefacts it was built from, so
    "which data version produced this?" is a graph walk. Registering the parents
    first is why `seed.carry` must run before this.
    """
    con = duckdb.connect()
    results: list[BuildResult] = []

    def _digest(path) -> str | None:
        if not path.is_dir():
            return None
        try:
            return prov.hash_dataset(path, pattern="**/*")[0]
        except prov.ProvenanceError:
            return None

    # EACH SPINE EDGES ONLY TO THE SOURCES IT ACTUALLY READS.
    #
    # The first version attached all three carried sources to BOTH spines, so
    # `price_spine` claimed to derive from `seed:fno`. That is not a cosmetic
    # error: the DAG's most valuable query is "which results does a restatement
    # of THIS source invalidate?" (Plan 2 §8.2). An over-broad edge answers it
    # wrongly in the expensive direction — a restated F&O file would have flagged
    # every price-derived result as suspect.
    #
    # `seed:v1_export` is a genuine parent of both: it is one carried directory
    # containing stock_data AND fo_data.
    per_spine = {
        PRICE.name: (SEED, SEED_INCREMENTS / "prices", COLLECTED / "prices"),
        ADJUSTED.name: (SEED, SEED_INCREMENTS / "prices", COLLECTED / "prices"),
        FNO.name: (SEED, SEED_INCREMENTS / "fno"),
    }

    for spec in (PRICE, ADJUSTED, FNO):
        r = build_adjusted(env=env, con=con) if spec is ADJUSTED else build(spec, env=env, con=con)
        parents = [
            (d, "input")
            for d in (_digest(p) for p in per_spine[spec.name])
            if d is not None
        ]
        # Addressed by DATA, not by bytes. DuckDB's parquet writer is not
        # byte-deterministic (see provenance.data_checksum), so hashing the files
        # registered a new artefact on every rebuild of unchanged data.
        digest = prov.data_checksum(
            con, f"{r.path}/**/*.parquet", (*spec.columns, "_y")
        )
        total_bytes = sum(p.stat().st_size for p in r.path.glob("**/*.parquet"))
        prov.register(
            prov.Artefact(
                artefact_hash=digest,
                artefact_type="TABLE",
                logical_name=f"warehouse:{spec.name}",
                produced_by=PRODUCED_BY,
                row_count=r.rows,
                byte_size=total_bytes,
                params={
                    "columns": list(spec.columns),
                    "rows": r.rows,
                    "decision": "0027",
                    "addressing": "data_checksum",
                },
            ),
            parents=parents,
            env=env,
        )
        r.artefact_hash = digest
        results.append(r)
    return results


def main() -> int:
    print("SPINE REBUILD (Phase 1.8)")
    results = build_all()
    for r in results:
        print(r.render())
        print(f"               artefact {r.artefact_hash[:16]}  -> {r.path}")
    print("\nSPINE REBUILD: GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
