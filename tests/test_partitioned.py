"""A partitioned dataset is replaced whole (src/common/partitioned.py).

DuckDB's PARTITION_BY + OVERWRITE_OR_IGNORE overwrote data_0.parquet and left
an earlier write's data_1.parquet: char_panel held 29,833 duplicated keys from
August and CHAR_MATCHED benchmarks varied between identical runs."""

from __future__ import annotations

import duckdb
import pytest

from src.common.partitioned import replace_partitioned

pytestmark = pytest.mark.unit


def test_a_stale_file_from_an_earlier_write_cannot_survive(tmp_path):
    out = tmp_path / "panel"
    (out / "k=1").mkdir(parents=True)
    con = duckdb.connect()
    con.execute(f"COPY (SELECT 1 AS k, 99 AS v) TO '{out}/k=1/data_1.parquet' (FORMAT PARQUET)")  # the stale file
    replace_partitioned(con, "SELECT 1 AS k, 7 AS v UNION ALL SELECT 2, 8", out, "k")
    got = con.execute(f"SELECT k, v FROM read_parquet('{out}/**/*.parquet', hive_partitioning=true) ORDER BY k").fetchall()
    assert got == [(1, 7), (2, 8)]
    assert not (tmp_path / "panel.partial").exists() and not (tmp_path / "panel.old").exists()


def test_no_writer_uses_overwrite_or_ignore_again():
    from src.common.paths import ROOT
    offenders = [p for p in (ROOT / "src").rglob("*.py")
                 if p.name != "partitioned.py" and "OVERWRITE_OR_IGNORE" in p.read_text()]
    assert not offenders, offenders
