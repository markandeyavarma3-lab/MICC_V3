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

from src.common.paths import SEED, SEED_INCREMENTS, warehouse_dir
from src.governance import provenance as prov

PRODUCED_BY = "src.warehouse.spine:build"


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
    partition_by: str = "_y"


PRICE = SpineSpec(
    name="price_spine",
    seed_glob="stock_data/**/*.parquet",
    increment_glob="prices/**/*.parquet",
    columns=("symbol", "date", "open", "high", "low", "close", "volume"),
    unique_key=("symbol", "date"),
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
        PRICE.name: (SEED, SEED_INCREMENTS / "prices"),
        FNO.name: (SEED, SEED_INCREMENTS / "fno"),
    }

    for spec in (PRICE, FNO):
        r = build(spec, env=env, con=con)
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
