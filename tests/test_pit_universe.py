"""The point-in-time universe past the seed (src/warehouse/pit_universe.py):
the recovered rule reproduces the seed, and nothing up to the CONFIRM grid's
end changes."""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from src.common.paths import research_db, warehouse_dir
from src.warehouse import pit_universe as U

needs_spine = pytest.mark.skipif(
    not any((warehouse_dir("prod") / "price_spine").glob("**/*.parquet")) or not U.SEED_FILE.exists(),
    reason="raw spine or seed universe absent",
)


@pytest.mark.unit
def test_a_month_end_is_written_only_once_the_month_is_over_and_after_the_grid():
    s = [date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 29), date(2026, 10, 30),
         date(2026, 11, 2), date(2026, 11, 27)]
    # September ends before EXTEND_AFTER; November is not over; October is.
    assert U.month_ends(s) == [date(2026, 10, 30)]
    assert U.month_ends(s, after=date(2026, 1, 1)) == [date(2026, 9, 30), date(2026, 10, 30)]


@pytest.mark.unit
def test_without_an_extension_the_source_is_the_seed_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "out_path", lambda env=None: tmp_path / "none.parquet")
    assert "UNION" not in U.source_sql()


@pytest.mark.unit
def test_the_extension_never_reaches_back_past_the_grid(tmp_path, monkeypatch):
    ext = tmp_path / "ext.parquet"
    con = duckdb.connect()
    con.execute(f"COPY (SELECT DATE '2026-10-30' AS rebal_date, 'ACME' AS symbol, 63 AS n_days, 1e9 AS med_turnover,"
                f" 1 AS adv_rank, 1 AS top100, 1 AS top250, 1 AS top500, 1 AS liquid) TO '{ext}' (FORMAT PARQUET)")
    monkeypatch.setattr(U, "out_path", lambda env=None: ext)
    src = U.source_sql()
    assert f"<= DATE '{U.EXTEND_AFTER}'" in src
    if U.SEED_FILE.exists():
        seed_max = con.execute(f"SELECT max(CAST(rebal_date AS DATE)) FROM read_parquet('{U.SEED_FILE}')").fetchone()[0]
        got = con.execute(f"SELECT max(rebal_date) FILTER (WHERE symbol <> 'ACME'), "
                          f"count(*) FILTER (WHERE symbol = 'ACME') FROM ({src})").fetchone()
        assert got == (min(seed_max, U.EXTEND_AFTER), 1)


@pytest.mark.needs_data
@needs_spine
def test_the_recovered_rule_reproduces_the_seeds_may_2026_rebalance_to_the_rupee():
    """Median turnover and n_days, for every company the seed lists on
    2026-05-29 (measured 2026-10-11: 2,307 of 2,307)."""
    spine = str(warehouse_dir("prod") / "price_spine" / "**" / "*.parquet")
    con = duckdb.connect(str(research_db("prod")), read_only=True)
    try:
        sessions = [r[0] for r in con.execute(
            f"SELECT DISTINCT CAST(date AS DATE) FROM read_parquet('{spine}', hive_partitioning=true) "
            "WHERE CAST(date AS DATE) BETWEEN DATE '2026-01-01' AND DATE '2026-05-29' ORDER BY 1").fetchall()]
        win = sessions[-U.WINDOW:]
        # Every symbol, ETFs included, as the seed was built; the INE rule is
        # the extension's own (0040) and is not what this pins.
        got = con.execute(f"""
            WITH ours AS ({U.rebalance_sql(spine, win[0], date(2026, 5, 29), "SELECT DISTINCT UPPER(TRIM(symbol)) FROM read_parquet('" + spine + "', hive_partitioning=true)")}),
                 seed AS (SELECT UPPER(TRIM(symbol)) symbol, n_days, med_turnover FROM read_parquet('{U.SEED_FILE}')
                          WHERE CAST(rebal_date AS DATE) = DATE '2026-05-29')
            SELECT count(*), count(*) FILTER (WHERE o.n_days = s.n_days AND abs(o.med_turnover / s.med_turnover - 1) < 1e-9)
            FROM seed s JOIN ours o USING (symbol)""").fetchone()
    finally:
        con.close()
    assert got[0] >= 2300 and got[1] == got[0]
