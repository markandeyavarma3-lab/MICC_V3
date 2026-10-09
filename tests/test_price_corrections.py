"""The price-spine corrections (decision 0088): the rule that turns a one-day
jump into a correction or a quarantined suspect, and what the rebuilt spine
must then show. The Kite audit (0087) found TCS 2018 and INFY 2015 — 1:1
bonuses — still reading as -50% days in every study."""

from __future__ import annotations

import csv
import importlib.util
import inspect

import pytest

from src.common.paths import CONFIGS, ROOT

spec = importlib.util.spec_from_file_location("bpc", ROOT / "scripts" / "build_price_corrections.py")
bpc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bpc)


@pytest.mark.unit
def test_an_nse_recorded_action_uses_nses_own_factor():
    """WIPRO 2010: a 2:3 bonus, factor 0.6. The nearest strict ratio would
    have been 2/3; NSE's number wins when it matches the move."""
    cls, f, _ = bpc.classify(0.6055, None, 0.6, held=0.61)
    assert (cls, f) == ("T1", 0.6)


@pytest.mark.unit
def test_a_partly_applied_day_corrects_only_the_residual():
    """ONGC 2011: split AND bonus (0.25); the seed applied the split. Ours
    moved 0.47, so the correction is 1/2, not 1/4."""
    cls, f, _ = bpc.classify(0.4722, None, 0.25, held=0.47)
    assert (cls, f) == ("T1", 0.5)


@pytest.mark.unit
def test_kite_flat_and_a_split_ratio_is_a_correction():
    cls, f, _ = bpc.classify(0.5035, 1.0073, None, held=0.50)
    assert (cls, f) == ("T2", 0.5)


@pytest.mark.unit
def test_a_print_that_reverts_is_never_corrected():
    """'Correcting' a one-day print would rescale the whole history before it."""
    cls, f, _ = bpc.classify(0.5, 1.0, 0.5, held=0.99)
    assert (cls, f) == ("REVERTED", None)


@pytest.mark.unit
def test_a_move_kite_also_shows_is_real_and_left_alone():
    assert bpc.classify(0.55, 0.56, None, held=0.55)[:2] == ("REAL", None)


@pytest.mark.unit
def test_a_split_ratio_alone_is_quarantined_not_corrected():
    """No second source: a genuine crash lands on a strict ratio about one
    time in ten (4 of 42 Kite-confirmed real moves, 2026-10-09)."""
    assert bpc.classify(0.5, None, None, held=0.5)[:2] == ("UNCONFIRMED_RATIO", None)


@pytest.mark.unit
def test_the_frozen_files_are_disjoint_and_every_correction_names_its_evidence():
    if not (CONFIGS / "price_corrections.csv").exists():
        pytest.skip("corrections not frozen in this checkout")
    with (CONFIGS / "price_corrections.csv").open() as fh:
        fixes = list(csv.DictReader(fh))
    with (CONFIGS / "price_suspect_days.csv").open() as fh:
        sus = list(csv.DictReader(fh))
    assert {(r["symbol"], r["ex_date"]) for r in fixes}.isdisjoint({(r["symbol"], r["date"]) for r in sus})
    assert all(r["tier"] in ("T1", "T2") and r["evidence"] for r in fixes)
    assert all(0 < float(r["factor"]) < 25 for r in fixes)


@pytest.mark.unit
def test_the_discontinuity_guard_reads_the_whole_history_not_the_tail():
    """It checked only moves after the seed boundary, so 21 years of seed
    were never checked and 226 unadjusted actions sat in them."""
    from src.warehouse import spine
    src = inspect.getsource(spine._build_adjusted_impl)
    guard = src[src.index("survivors = c.execute("):src.index("if survivors >")]
    assert "boundary" not in guard and "price_suspect_days" in src


@pytest.mark.data
@pytest.mark.needs_data
def test_the_confirmed_missing_actions_are_gone_from_the_rebuilt_spine():
    duckdb = pytest.importorskip("duckdb")
    from src.common.paths import warehouse_dir
    adj = warehouse_dir("prod") / "price_spine_adj"
    if not list(adj.glob("**/*.parquet")):
        pytest.skip("adjusted spine not built in this environment")
    con = duckdb.connect()
    for symbol, ex in (("TCS", "2018-05-31"), ("INFY", "2015-06-15"), ("WIPRO", "2005-08-22"),
                       ("WIPRO", "2010-06-15"), ("ONGC", "2011-02-08")):
        r = con.execute(
            f"WITH s AS (SELECT date, close, LAG(close) OVER (ORDER BY date) prev"
            f" FROM read_parquet('{adj}/**/*.parquet') WHERE symbol = ?)"
            f" SELECT close / prev FROM s WHERE date = ?", [symbol, ex]).fetchone()
        assert r and 0.8 < r[0] < 1.25, f"{symbol} {ex} still moves {r}"
