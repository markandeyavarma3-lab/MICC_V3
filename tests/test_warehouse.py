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
    """Re-running must verify, not re-copy. The second run is the check.

    UNRUNNABLE SINCE 2026-09-01, and skipped rather than deleted. Decision 0042
    removed MICCV2 from the machine, so there is no source to carry FROM and
    this can never execute again here. Deleting it would erase the record that
    idempotence was ever required; leaving it failing would train someone to
    ignore a red suite. It runs again the moment PREDECESSOR_ROOT points at a
    restored clone.
    """
    from src.common.paths import predecessor_root

    if not predecessor_root().is_dir():
        pytest.skip(
            "the predecessor was deleted (0042); restore it from "
            "data/raw/salvaged/predecessor_repos/MICCV2.bundle to run this"
        )
    rep = seed.carry(dry_run=False)
    assert rep.ok, rep.problems
    assert rep.copied == 0, f"a second carry copied {rep.copied} files; it should skip all"


def test_carry_refuses_honestly_when_the_predecessor_is_gone():
    """The failure mode that replaced it, and it IS testable.

    A missing predecessor must not read as "nothing to do". The message has to
    say that the deletion was deliberate, that seed.verify() is the thing to
    check first, and where the bundle is — otherwise a future reader finds a
    hard error pointing at a path that will never exist again.
    """
    from src.common.paths import predecessor_root

    if predecessor_root().is_dir():
        pytest.skip("the predecessor is present; this tests its absence")

    with pytest.raises(seed.SeedError) as exc:
        seed.carry(dry_run=True)
    msg = str(exc.value)
    assert "0042" in msg, "the error must name the decision that deleted it"
    assert "seed.verify" in msg, "it must say what to check first"
    assert "MICCV2.bundle" in msg, "it must say where the recovery path is"


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


@needs_spine
def test_the_price_spine_reconciles_exactly_with_its_inputs():
    """The spine must contain its sources and nothing else.

    FOUND BY MEASURING, 2026-09-01. `price_spine` held 3,819 rows that were in
    no source — 343 per session across the eleven collected dates, exactly the
    fund/ETF rows decision 0040 removed. The parser was re-run with the ISIN
    filter, which rewrote the inputs, and only `price_spine_adj` was rebuilt
    afterwards. The raw spine sat stale and disagreed with its own inputs while
    every row count still looked plausible.

    Row totals alone would not have caught it. The set difference does.
    """
    from src.common.paths import COLLECTED, SEED, SEED_INCREMENTS

    con = duckdb.connect()
    con.execute("SET memory_limit='6GB'")
    spine_glob = f"{warehouse_dir('prod') / 'price_spine'}/**/*.parquet"
    src = (
        f"SELECT symbol, date FROM read_parquet('{SEED}/stock_data/**/*.parquet')"
        f" UNION ALL SELECT symbol, date FROM"
        f" read_parquet('{SEED_INCREMENTS}/prices/**/*.parquet')"
    )
    if list((COLLECTED / "prices").glob("*.parquet")):
        src += (f" UNION ALL SELECT symbol, date FROM"
                f" read_parquet('{COLLECTED}/prices/*.parquet')")

    extra, missing = con.execute(
        f"WITH src AS ({src}),"
        f" sp AS (SELECT symbol, date FROM read_parquet('{spine_glob}'))"
        f" SELECT (SELECT COUNT(*) FROM (SELECT * FROM sp EXCEPT ALL SELECT * FROM src)),"
        f"        (SELECT COUNT(*) FROM (SELECT * FROM src EXCEPT ALL SELECT * FROM sp))"
    ).fetchone()

    assert extra == 0, (
        f"{extra:,} (symbol, date) rows are in price_spine but in no source — the "
        f"spine is stale relative to its inputs. Rebuild it: "
        f"python -m src.warehouse.spine"
    )
    assert missing == 0, (
        f"{missing:,} source rows never reached price_spine"
    )


@needs_spine
def test_the_two_price_spines_cover_the_same_universe():
    """Raw and adjusted must describe the same instruments.

    They diverged at 4,412 against 4,382 symbols for the same reason: one was
    built before decision 0040's ISIN filter and one after. A 30-symbol gap
    between the spine research reads and the spine it is checked against is the
    kind of difference nobody notices until a result depends on it.
    """
    con = duckdb.connect()
    a, b = (
        con.execute(
            f"SELECT COUNT(DISTINCT symbol) FROM"
            f" read_parquet('{warehouse_dir('prod') / t}/**/*.parquet')"
        ).fetchone()[0]
        for t in ("price_spine", "price_spine_adj")
    )
    assert a == b, (
        f"price_spine has {a:,} symbols and price_spine_adj has {b:,}; one was "
        f"built from different inputs than the other"
    )


@pytest.mark.unit
def test_the_collector_takes_the_same_series_as_the_seed():
    """0045. The seed is EQ-only across twenty-one years — measured against the
    exchange's own files, not read from a config, because no config said so.

    bhavcopy.py declared ("EQ","BE","BZ") until 2026-09-01, which would have
    made the universe change definition at 2026-08-17. BE is the trade-to-trade
    surveillance segment, entered precisely when a price behaves unusually,
    which is the population a deal study is about.
    """
    from src.ingest import bhavcopy

    assert bhavcopy.SERIES == ("EQ",), (
        f"the collector takes {bhavcopy.SERIES} but the seed is EQ-only; a "
        f"universe that changes definition mid-series is decision 0045's defect"
    )


@needs_spine
def test_the_forward_horizon_is_not_silently_stretched_beyond_tolerance():
    """0045. Forward returns use LEAD(close, N) over the symbol's own row
    number, so a gap in the series stretches the horizon in calendar time.
    Measured: median 372 days for a '12-month' window, 4.86% past 450 days,
    worst 1,553 days.

    This pins the MEDIAN, which is the part that would signal a systemic change
    — a jump here means the spine has started dropping sessions wholesale.
    """
    con = duckdb.connect()
    con.execute("SET memory_limit='6GB'")
    glob = f"{warehouse_dir('prod') / 'price_spine_adj'}/**/*.parquet"
    med = con.execute(
        f"WITH px AS (SELECT symbol, date,"
        f"   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date) i"
        f"   FROM read_parquet('{glob}')),"
        f" fw AS (SELECT date, LEAD(date, 252) OVER"
        f"   (PARTITION BY symbol ORDER BY i) x FROM px)"
        f" SELECT median(DATEDIFF('day', CAST(date AS DATE), CAST(x AS DATE)))"
        f" FROM fw WHERE x IS NOT NULL"
    ).fetchone()[0]
    assert 360 <= med <= 400, (
        f"the median '252-session' window spans {med:.0f} calendar days; "
        f"outside 360-400 means the spine's session coverage has changed"
    )


@pytest.mark.unit
def test_two_spine_builds_cannot_run_at_once():
    """0049. price_spine_adj/_y=2005/data_0.parquet was corrupted on
    2026-09-02 by a manual rebuild racing the 22:30 scheduled one.

    The corruption was invisible to COUNT(*), which reads only the parquet
    footer — every row count in the project stayed correct while any read of
    the `symbol` column raised TProtocolException. collect_daily.sh now rebuilds
    three times a session, so the race is not rare.
    """
    from src.warehouse import spine

    with spine._exclusive("test_spine"):
        with pytest.raises(spine.SpineError, match="another test_spine build"):
            with spine._exclusive("test_spine"):
                pass
    # released on exit, so a later build is not blocked forever
    with spine._exclusive("test_spine"):
        pass


@pytest.mark.unit
def test_the_identity_rebuild_reads_before_it_destroys():
    """0049. master.py ran DELETE on security_master and symbol_history, then
    died on the corrupt spine. DuckDB autocommits, so the deletes stood: three
    tables went to 0 rows because one upstream file was briefly unreadable.

    The spine is now materialised into a temp table BEFORE the deletes, so an
    unreadable partition raises with both tables still populated. Not a
    transaction — DuckDB refuses the FK'd delete inside one.
    """
    import inspect

    src = inspect.getsource(__import__("src.identity.master", fromlist=["build"]).build)
    temp = src.index("_spine_symbols")
    delete = src.index('DELETE FROM symbol_history')
    assert temp < delete, (
        "the spine is read AFTER the delete; an unreadable partition would "
        "again empty security_master and symbol_history"
    )
