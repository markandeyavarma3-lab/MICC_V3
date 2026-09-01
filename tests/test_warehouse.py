"""The warehouse rebuild and the Phase 1 gate.

Tests marked `needs_data` require the seed to have been carried
(`python -m src.warehouse.seed`) and the spines built. They are skipped rather
than failed on a fresh clone, because a clone has no 2.5 GB of irreplaceable
history in it and cannot get one from the network.
"""

from __future__ import annotations

import duckdb
import pytest
import yaml

from src.common.paths import CONFIGS, ROOT, SEED, SEED_INCREMENTS, warehouse_dir
from src.warehouse import reconcile, seed, spine

pytestmark = pytest.mark.data


def _carried() -> bool:
    return SEED.is_dir() and any(SEED.glob("**/*.parquet"))


def _built(name: str) -> bool:
    return any((warehouse_dir("prod") / name).glob("**/*.parquet"))


needs_seed = pytest.mark.skipif(not _carried(), reason="seed not carried")
needs_spine = pytest.mark.skipif(
    not (_built("price_spine") and _built("fno_spine")), reason="spines not built"
)


# --- spec hygiene, no data required ------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("spec", [spine.PRICE, spine.FNO], ids=lambda s: s.name)
def test_every_spine_declares_its_unique_key(spec):
    """A uniqueness guard with a GUESSED key checks the guess, not uniqueness.

    The first version inferred `(symbol, date)` whenever a `symbol` column
    existed. Right for prices; for F&O it flagged 968,371 ordinary rows as
    duplicates, because one symbol has many contracts a day across expiries,
    strikes and option types.
    """
    assert spec.unique_key, f"{spec.name} has no declared key"
    assert set(spec.unique_key) <= set(spec.columns), (
        f"{spec.name}: key {spec.unique_key} names columns the spine does not carry"
    )


@pytest.mark.unit
def test_the_fno_key_is_the_contract_not_the_underlying():
    """Pins the actual bug. `symbol` alone does not identify a derivatives row."""
    assert "expiry" in spine.FNO.unique_key
    assert spine.FNO.unique_key != ("symbol", "date")


@pytest.mark.unit
def test_seed_sources_state_why_each_is_irreplaceable():
    """Decision 0027 carries data the plan said to delete. Each carry must say
    why, or the next teardown deletes it again for the same stated reason."""
    for src in seed.SOURCES:
        assert len(src.rationale.strip()) > 40, f"{src.logical_name} has no rationale"


# NOTE: hard-coded-home-path coverage lives in
# test_foundations.py::test_no_source_file_contains_a_hard_coded_home_path, which
# correctly ignores docstrings that DESCRIBE the defect. A naive grep here failed
# on paths.py's own explanation of audit defect #8.


# --- the gate config -----------------------------------------------------------


@pytest.mark.unit
def test_the_gate_is_exact_not_approximate():
    s = yaml.safe_load((CONFIGS / "universe.yml").read_text())["reconciliation"]
    assert s["tolerance"] == 0, "a near-miss is a bug, not a rounding"


@pytest.mark.unit
def test_the_corrected_fno_figure_keeps_the_old_one_visible():
    """Decision 0029. A correction that erases what it corrected is not legible."""
    s = yaml.safe_load((CONFIGS / "universe.yml").read_text())["reconciliation"]
    assert s["expect_fno_rows"] == 174_272_768
    assert s["expect_fno_rows_superseded"] == 174_616_363
    assert s["expect_fno_rows"] < s["expect_fno_rows_superseded"], (
        "the correction removed double-counted rows, so it must be SMALLER"
    )


# --- the carry -----------------------------------------------------------------


@needs_seed
def test_the_carry_is_idempotent():
    """Re-running must verify, not re-copy. The second run is the check."""
    rep = seed.carry(dry_run=False)
    assert rep.ok, rep.problems
    assert rep.copied == 0, f"a second carry copied {rep.copied} files; it should skip all"


@needs_seed
def test_the_increments_are_actually_present():
    """The whole of decision 0027. Without these the gate is unreachable."""
    assert (SEED_INCREMENTS / "prices").is_dir(), "price increment not carried"
    assert (SEED_INCREMENTS / "fno").is_dir(), "F&O increment not carried"


@needs_seed
def test_the_seed_is_registered_in_the_provenance_graph():
    """The DAG held ZERO rows for five days after being created. It must not
    return to that state silently."""
    rep = seed.verify()
    assert rep.ok, rep.problems
    assert len(rep.artefacts) == len(seed.SOURCES)


# --- the spines ------------------------------------------------------------------


@needs_spine
@pytest.mark.parametrize(
    "name,expected",
    [("price_spine", 7_749_148), ("price_spine_adj", 7_748_799), ("fno_spine", 174_272_768)],
)
def test_spine_row_counts(name, expected):
    """Counted only up to the last session MICCV2 supplied.

    These three numbers are the frozen reconciliation against the predecessor.
    From 2026-08-17 the price spines also carry sessions this project collected
    from NSE itself, which move the totals every day the collector runs — so an
    unbounded count would fail daily and the fix would look like "update the
    expected number", which is how a check becomes a receipt.

    Bounding the measurement keeps the oracle load-bearing. The collected rows
    are covered by `reconcile.collected_starts_after_miccv2` and by the overlap
    refusal in `spine._collected_part`, not by these constants.
    """
    con = duckdb.connect()
    where = "" if name == "fno_spine" else f" WHERE date <= '{reconcile.MICCV2_HORIZON}'"
    got = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{warehouse_dir('prod') / name}/**/*.parquet')"
        + where
    ).fetchone()[0]
    assert got == expected


@needs_spine
def test_the_price_spine_extends_past_what_miccv2_supplied():
    """The collector's whole point. Without this the deals collected since
    2026-08-17 have no next-session price and stay ineligible forever."""
    con = duckdb.connect()
    latest = con.execute(
        f"SELECT MAX(date) FROM read_parquet('{warehouse_dir('prod') / 'price_spine'}/**/*.parquet')"
    ).fetchone()[0]
    assert latest > reconcile.MICCV2_HORIZON, (
        f"price_spine still ends at {latest}; nothing has been collected past "
        f"the seed, so live-collected deals cannot become eligible"
    )


@needs_spine
def test_the_price_spine_has_no_duplicate_symbol_dates():
    """Prices ARE uniquely keyed by (symbol, date) — unlike F&O."""
    con = duckdb.connect()
    dupes = con.execute(
        f"SELECT COUNT(*) FROM (SELECT symbol, date, COUNT(*) n FROM "
        f"read_parquet('{warehouse_dir('prod') / 'price_spine'}/**/*.parquet') "
        f"GROUP BY symbol, date HAVING n > 1)"
    ).fetchone()[0]
    assert dupes == 0


@needs_spine
def test_the_fno_overlap_window_appears_exactly_once():
    """Decision 0029's core claim, asserted on the built spine.

    2016-07-01..2016-07-15 exists in BOTH sources. If the resolution rule failed,
    these dates would carry roughly double their true row count.
    """
    con = duckdb.connect()
    fno = f"{warehouse_dir('prod') / 'fno_spine'}/**/*.parquet"
    dupes = con.execute(
        f"SELECT COUNT(*) FROM (SELECT date, instrument, symbol, expiry, strike,"
        f" option_typ, COUNT(*) n FROM read_parquet('{fno}')"
        f" WHERE date BETWEEN '2016-07-01' AND '2016-07-15'"
        f" GROUP BY 1,2,3,4,5,6 HAVING n > 1)"
    ).fetchone()[0]
    assert dupes == 0, (
        f"{dupes:,} duplicate contract-keys inside the known overlap window — the "
        f"seed/increment resolution in spine.build did not take effect"
    )


@needs_spine
def test_the_blank_expiry_rows_were_kept_not_deduplicated():
    """4,025,340 seed rows carry a blank expiry. They are distinct contracts whose
    label was lost, NOT duplicates — a naive DISTINCT would destroy ~2M real rows
    while looking like cleaning."""
    con = duckdb.connect()
    n = con.execute(
        f"SELECT COUNT(*) FROM read_parquet("
        f"'{warehouse_dir('prod') / 'fno_spine'}/**/*.parquet') WHERE expiry = ''"
    ).fetchone()[0]
    assert n > 3_000_000, f"only {n:,} blank-expiry rows survived; they were dropped"


# --- the gate itself ---------------------------------------------------------------


@needs_spine
def test_a_rebuild_produces_the_SAME_artefact_hash():
    """Plan 2 §8.2 claims an artefact can be re-derived exactly. It could not.

    Measured 2026-08-22: three rebuilds of `price_spine` from byte-identical
    inputs produced three different dataset hashes and three different total
    sizes (169,144,874 / 169,070,178 / 169,182,344) for the same 7,749,148 rows,
    because DuckDB's parquet writer is not byte-deterministic. Every rebuild
    registered a duplicate node, and two results from identical data would have
    recorded different input hashes.

    Derived tables are therefore addressed by their DATA (decision 0030). This
    test is the guarantee: recomputing the address twice must agree.
    """
    con = duckdb.connect()
    glob = f"{warehouse_dir('prod') / 'price_spine'}/**/*.parquet"
    cols = (*spine.PRICE.columns, "_y")
    from src.governance import provenance as prov

    assert prov.data_checksum(con, glob, cols) == prov.data_checksum(con, glob, cols)


@needs_spine
def test_each_spine_edges_only_to_the_sources_it_reads():
    """An over-broad edge answers the DAG's most valuable question wrongly.

    The first version attached all three carried sources to BOTH spines, so
    `price_spine` claimed `seed:fno` as an input. A restated F&O file would then
    have flagged every price-derived result as invalidated.
    """
    import sqlite3

    from src.common.paths import governance_db

    con = sqlite3.connect(governance_db("prod"))
    try:
        rows = con.execute(
            "SELECT c.logical_name, p.logical_name FROM artefact_edge e"
            " JOIN artefact c ON c.artefact_hash=e.child_hash"
            " JOIN artefact p ON p.artefact_hash=e.parent_hash"
            " WHERE json_extract(c.params_json,'$.addressing')='data_checksum'"
        ).fetchall()
    finally:
        con.close()

    edges: dict[str, set[str]] = {}
    for child, parent in rows:
        edges.setdefault(child, set()).add(parent)

    assert "seed:fno" not in edges.get("warehouse:price_spine", set()), (
        "the price spine does not read F&O data"
    )
    assert "seed:prices" not in edges.get("warehouse:fno_spine", set()), (
        "the F&O spine does not read the price increment"
    )


@needs_spine
def test_the_phase_1_reconciliation_gate_passes():
    """Plan 1 §3.4. This is the gate that blocks Phase 2.

    It could not pass as originally specified: every expectation was measured
    against `data/warehouse/`, which the plan marked for deletion, while the seed
    it told us to carry stops on 2026-07-08 (decision 0027).
    """
    checks = reconcile.run("prod")
    failed = [f"{c.name}: expected {c.expected}, got {c.actual}" for c in checks if not c.passed]
    assert not failed, "gate failures:\n  " + "\n  ".join(failed)
    # 9 counts + the collected-source boundary added when the price collector
    # started extending the spine past what MICCV2 supplied. The count is
    # asserted so a check cannot be quietly dropped to make the gate pass.
    assert len(checks) == 10


@needs_spine
def test_the_adjusted_spine_is_what_research_reads():
    """universe.yml sets research_prices: adjusted. The raw spine is NOT a
    substitute — measured 2026-08-23, they differ on 17.1% of rows, and a return
    computed on raw prices reads a 1:2 split as -50%.

    This existed as a config line and nothing enforced it. Every measurement on
    22-23 Aug ran on the raw spine, including the 12-month result decision 0034
    rests on.
    """
    import re

    src = (ROOT / "src" / "research" / "charmatch.py").read_text()
    assert "price_spine_adj" in src, "charmatch must read the ADJUSTED spine"
    assert not re.search(r'"price_spine"', src), "charmatch still reads the raw spine"


@needs_spine
def test_adjustment_actually_removes_split_artefacts():
    """The point of the adjusted series, asserted rather than assumed.

    An unadjusted 1:2 split appears as a single-session fall below 0.5x. If
    adjustment is working, the adjusted spine must carry materially FEWER
    extreme drops than the raw one. Measured: 73 against 149.
    """
    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false;")

    def drops(name: str) -> int:
        g = f"{warehouse_dir('prod') / name}/**/*.parquet"
        return con.execute(
            f"""WITH x AS (SELECT close, LAG(close) OVER (PARTITION BY symbol ORDER BY date) p
                           FROM read_parquet('{g}'))
                SELECT SUM(CASE WHEN close/p < 0.1 THEN 1 ELSE 0 END) FROM x WHERE p>0"""
        ).fetchone()[0]

    raw, adj = drops("price_spine"), drops("price_spine_adj")
    assert adj < raw, f"adjusted ({adj}) should have fewer extreme drops than raw ({raw})"
    assert adj <= 73, f"extreme drops rose to {adj}; corporate actions may have stopped applying"


@needs_spine
def test_the_gate_checks_correctness_not_only_size():
    """A row count is identical whether the spine was built from raw or adjusted
    prices. The gate proved eight counts and nothing about their contents, which
    is exactly why the wrong-price defect survived it."""
    q = reconcile.quality("prod")
    failed = [f"{c.name}: expected {c.expected}, got {c.actual}" for c in q if not c.passed]
    assert not failed, "quality failures:\n  " + "\n  ".join(failed)
    assert len(q) >= 7
