"""CHAR_MATCHED: one definition, and the arithmetic it carries.

Until 2026-09-20 the benchmark benchmarks.yml calls primary was written out
twice — in `outcomes.py` for every deal outcome and in `holdings.py` for
exp_004 — and the registration draft called the second "outcomes.py's
construction, mirrored in holdings.py". A mirror kept by hand under a frozen
spec is how a registered study drifts from the table it claims to reproduce
with nothing to notice. The first test here makes that structurally
impossible; the rest pin what the one definition computes.
"""

from __future__ import annotations

import inspect
import re

import pytest

from src.research import charmatch, holdings, outcomes

pytestmark = pytest.mark.unit


# --- one definition ------------------------------------------------------------


def test_the_ladder_the_minimum_and_the_self_exclusion_are_defined_exactly_once():
    """Neither consumer may carry its own copy. The three fragments that
    decide what CHAR_MATCHED means — the level tuple, the self-exclusion
    formula, the `>=` against the cell minimum — must appear in charmatch.py
    and nowhere else."""
    for mod in (outcomes, holdings):
        src = inspect.getsource(mod)
        assert '("SIZE_MOM_VOL", "size_q, mom_q, vol_q")' not in src, f"{mod.__name__} redefines MATCH_LEVELS"
        assert "COALESCE(own.ret, 0)" not in src, f"{mod.__name__} carries its own self-exclusion"
        assert '["min_names_per_cell"]' not in src, f"{mod.__name__} reads the cell minimum from the yaml itself"
        assert "charmatch.ladder(" in src, f"{mod.__name__} does not consume the shared ladder"
    assert outcomes.MATCH_LEVELS is charmatch.MATCH_LEVELS
    assert holdings.MATCH_LEVELS is charmatch.MATCH_LEVELS


def test_the_level_order_is_finest_first_and_size_is_the_floor():
    """The ladder degrades; it never climbs. And SIZE is the last rung because
    a match on nothing is not a match — an event whose size cell is thin gets
    NULL, not the market."""
    levels = [lvl for lvl, _ in charmatch.MATCH_LEVELS]
    assert levels == ["SIZE_MOM_VOL", "SIZE_MOM", "SIZE"]
    keys = [k for _, k in charmatch.MATCH_LEVELS]
    assert all(keys[i].count(",") > keys[i + 1].count(",") for i in range(len(keys) - 1))


# --- the arithmetic, on a cell small enough to check by hand ---------------------


def _pool(con, rows):
    """cells(symbol, d, ret, size_q, mom_q, vol_q) and the three cm_ tables."""
    con.execute("CREATE TABLE cells (symbol VARCHAR, d DATE, ret DOUBLE, size_q INT, mom_q INT, vol_q INT)")
    con.executemany("INSERT INTO cells VALUES (?,?,?,?,?,?)", rows)
    for level, keys in charmatch.MATCH_LEVELS:
        con.execute(f"CREATE TABLE cm_{level} AS " + charmatch.cell_means_sql(level, keys))


def _bench(con, min_cell, symbol, d, size_q, mom_q, vol_q):
    lad = charmatch.ladder(min_cell, event="ec", own="own")
    con.execute("CREATE OR REPLACE TABLE ec AS SELECT ? AS symbol, CAST(? AS DATE) AS d, ? AS size_q, ? AS mom_q, ? AS vol_q",
                [symbol, d, size_q, mom_q, vol_q])
    return con.execute(f"""
        SELECT {lad.bench}, {lad.match_level}
        FROM ec LEFT JOIN cells own ON own.symbol = ec.symbol AND own.d = ec.d
        {lad.joins}""").fetchone()


def test_the_events_own_return_is_taken_out_of_its_cell_mean():
    """Five names in the cell, the event among them. The benchmark is the mean
    of the OTHER four, or every event is partly benchmarked against itself."""
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect()
    d = "2026-06-01"
    _pool(con, [("EVT", d, 0.50, 1, 1, 1), ("A", d, 0.10, 1, 1, 1), ("B", d, 0.20, 1, 1, 1),
                ("C", d, 0.30, 1, 1, 1), ("D", d, 0.40, 1, 1, 1)])
    bench, level = _bench(con, 5, "EVT", d, 1, 1, 1)
    assert bench == pytest.approx((0.10 + 0.20 + 0.30 + 0.40) / 4)
    assert level == "SIZE_MOM_VOL"


def test_a_delisted_event_with_no_forward_return_is_not_subtracted():
    """The name never entered the mean, so taking it out would remove a
    contribution that was never added — the mean of the four IS the bench."""
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect()
    d = "2026-06-01"
    _pool(con, [("A", d, 0.10, 1, 1, 1), ("B", d, 0.20, 1, 1, 1),
                ("C", d, 0.30, 1, 1, 1), ("D", d, 0.40, 1, 1, 1)])
    bench, _ = _bench(con, 4, "GONE", d, 1, 1, 1)   # GONE has no row in cells
    assert bench == pytest.approx(0.25)


def test_the_cell_minimum_is_a_minimum_not_a_strict_bound():
    """benchmarks.yml says min_names_per_cell: N. A cell of exactly N names
    qualifies; `> N` would silently require N+1 and reject cells the config
    accepts."""
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect()
    d = "2026-06-01"
    _pool(con, [(f"N{i}", d, 0.1 * i, 1, 1, 1) for i in range(4)])   # exactly four
    bench, level = _bench(con, 4, "OUT", d, 1, 1, 1)
    assert bench is not None and level == "SIZE_MOM_VOL"
    bench, level = _bench(con, 5, "OUT", d, 1, 1, 1)                 # one short
    assert bench is None and level is None


def test_a_thin_fine_cell_degrades_to_the_next_rung_and_says_so():
    """Three names share the event's size and momentum but only one its
    volatility. The three-way cell is thin; the two-way one qualifies; the
    rung that answered is recorded rather than inferred."""
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect()
    d = "2026-06-01"
    _pool(con, [("A", d, 0.10, 1, 1, 9), ("B", d, 0.20, 1, 1, 9), ("C", d, 0.30, 1, 1, 1)])
    bench, level = _bench(con, 3, "OUT", d, 1, 1, 1)
    assert level == "SIZE_MOM"
    assert bench == pytest.approx(0.20)


def test_the_cellmap_is_point_in_time_at_or_before_the_date():
    """A name carries the most recent rebalance AT OR BEFORE the date — never
    the next one, which was not knowable then."""
    duckdb = pytest.importorskip("duckdb")
    import pandas as pd
    con = duckdb.connect()
    panel = pd.DataFrame([("X", "2026-01-01", 1, 1, 1), ("X", "2026-04-01", 2, 2, 2), ("X", "2026-07-01", 3, 3, 3)],
                         columns=["symbol", "rebalance_date", "size_q", "mom_q", "vol_q"])
    panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "cp.parquet"
        con.execute(f"COPY (SELECT * FROM panel) TO '{p}' (FORMAT PARQUET)")
        got = con.execute(charmatch.cellmap_sql(
            "SELECT 'X' AS symbol, CAST('2026-05-15' AS DATE) AS d UNION ALL "
            "SELECT 'X', CAST('2026-04-01' AS DATE)", str(p))).fetchall()
    by_d = {str(d): (s, m, v) for _, d, s, m, v in got}
    assert by_d["2026-05-15"] == (2, 2, 2), "May must see the April rebalance, not July's"
    assert by_d["2026-04-01"] == (2, 2, 2), "AT the rebalance date means that rebalance"


def test_the_spec_prose_no_longer_claims_a_mirror():
    """The registration text described a hand-kept copy. It is no longer true
    and a hashed spec must not freeze a false description of the method."""
    import importlib.util
    from pathlib import Path
    root = Path(charmatch.__file__).resolve().parents[2]
    sm = importlib.util.spec_from_file_location("register_exp004", root / "scripts" / "register_exp004.py")
    reg = importlib.util.module_from_spec(sm); sm.loader.exec_module(reg)
    policy = reg.build_spec((2500, 2500, 2886))["benchmark_policy"]
    assert not re.search(r"mirror", policy, re.I)
    assert "charmatch" in policy
