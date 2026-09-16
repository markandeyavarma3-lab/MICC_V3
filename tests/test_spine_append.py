"""`spine.append_sessions`: nightly F&O lands without a 175M-row rebuild.

Decision 0066. 0065 landed history with a full `spine.build(FNO)`; nothing
ran it again, so the day after, `fno_spine` was stale once more. The
collector needed a path that appends the day's sessions and rewrites only
the year partition they fall in — with the full build's guarantees, or a
refusal. Synthetic three-column-shape spine in tmp, throwaway ledger; no
prod, no seed.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from src.governance import provenance as prov
from src.warehouse import spine

pytestmark = pytest.mark.unit

COLS = spine.FNO.columns  # 15 legacy columns


def _row(date, sym, strike=0.0, opt="XX", inst="FUTSTK", close=100.0):
    return (date, inst, sym, "2026-09-29", strike, opt, close, close, close, close, close,
            10, 1.5, 1000, 0)


def _write(con, rows, dest: Path):
    con.execute("CREATE OR REPLACE TABLE t (" + ", ".join(
        f"{c} {'DOUBLE' if c in ('strike','open','high','low','close','settle_pr','val_inlakh') else 'BIGINT' if c in ('contracts','open_int','chg_in_oi') else 'VARCHAR'}"
        for c in COLS) + ")")
    con.executemany(f"INSERT INTO t VALUES ({','.join('?' * len(COLS))})", rows)
    dest.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY (SELECT * FROM t) TO '{dest}' (FORMAT PARQUET)")


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A spine with 2025 and 2026 partitions, a collected dir, a ledger."""
    wh = tmp_path / "warehouse"
    coll = tmp_path / "collected"
    monkeypatch.setattr(spine, "warehouse_dir", lambda e=None: wh)
    monkeypatch.setattr(spine, "COLLECTED", coll)
    monkeypatch.setattr(spine, "_parent_dirs", lambda spec: ())
    monkeypatch.setattr(prov, "governance_db", lambda e=None: tmp_path / "g.sqlite")
    con = duckdb.connect()
    # partitions carry _y like the real spine
    con.execute("CREATE TABLE p (" + ", ".join(
        f"{c} {'DOUBLE' if c in ('strike','open','high','low','close','settle_pr','val_inlakh') else 'BIGINT' if c in ('contracts','open_int','chg_in_oi') else 'VARCHAR'}"
        for c in COLS) + ", _y BIGINT)")
    for r, y in ((_row("2025-12-30", "AAA"), 2025), (_row("2025-12-31", "AAA"), 2025),
                 (_row("2026-09-14", "AAA"), 2026), (_row("2026-09-15", "AAA"), 2026),
                 (_row("2026-09-15", "AAA", 100.0, "CE", "OPTSTK"), 2026)):
        con.execute(f"INSERT INTO p VALUES ({','.join('?' * (len(COLS) + 1))})", (*r, y))
    wh.mkdir()
    con.execute(f"COPY p TO '{wh / spine.FNO.name}' (FORMAT PARQUET, PARTITION_BY (_y), OVERWRITE_OR_IGNORE 1)")
    return wh, coll, con


def _spine_rows(con, wh):
    return con.execute(f"SELECT date, instrument, symbol, strike, option_typ FROM read_parquet('{wh}/fno_spine/**/*.parquet') ORDER BY 1,2,3,4").fetchall()


def test_new_sessions_are_appended_into_their_year_partition_only(world):
    wh, coll, con = world
    _write(con, [_row("2026-09-16", "AAA"), _row("2026-09-16", "BBB")], coll / "fno" / "date=2026-09-16.parquet")
    before_2025 = (wh / "fno_spine" / "_y=2025" / "data_0.parquet").stat().st_mtime_ns
    r = spine.append_sessions(spine.FNO)
    assert (r.seed_rows, r.increment_rows, r.rows) == (5, 2, 7)
    assert [x[0] for x in _spine_rows(con, wh)][-2:] == ["2026-09-16", "2026-09-16"]
    assert (wh / "fno_spine" / "_y=2025" / "data_0.parquet").stat().st_mtime_ns == before_2025, (
        "an append must not touch partitions it adds nothing to"
    )
    assert not list((wh / "fno_spine").glob("**/*.partial"))
    assert r.artefact_hash, "the appended spine is registered (0064)"


def test_a_session_already_in_the_spine_is_not_appended_twice(world):
    wh, coll, con = world
    _write(con, [_row("2026-09-15", "AAA"), _row("2026-09-15", "AAA", 100.0, "CE", "OPTSTK")],
           coll / "fno" / "date=2026-09-15.parquet")
    r = spine.append_sessions(spine.FNO)
    assert r.increment_rows == 0 and r.rows == 5


def test_a_collected_session_missing_from_the_spine_is_a_refusal_not_a_hole(world):
    """09-10 is older than the spine's last date but absent from it: only a
    full build can place it. Appending around it would leave a hole."""
    wh, coll, con = world
    _write(con, [_row("2026-09-10", "AAA")], coll / "fno" / "date=2026-09-10.parquet")
    with pytest.raises(spine.SpineError, match="not in the spine"):
        spine.append_sessions(spine.FNO)


def test_a_duplicate_key_inside_the_new_session_is_refused(world):
    wh, coll, con = world
    _write(con, [_row("2026-09-16", "AAA"), _row("2026-09-16", "AAA")], coll / "fno" / "date=2026-09-16.parquet")
    with pytest.raises(spine.SpineError, match="duplicate key"):
        spine.append_sessions(spine.FNO)
    assert len(_spine_rows(con, wh)) == 5, "a refused append leaves the spine as it was"


def test_a_new_year_gets_a_new_partition(world):
    wh, coll, con = world
    _write(con, [_row("2027-01-02", "AAA")], coll / "fno" / "date=2027-01-02.parquet")
    r = spine.append_sessions(spine.FNO)
    assert r.rows == 6 and (wh / "fno_spine" / "_y=2027" / "data_0.parquet").exists()


def test_no_collected_source_is_a_no_op_that_still_registers(world):
    wh, coll, con = world
    r = spine.append_sessions(spine.FNO)
    assert r.rows == 5 and r.increment_rows == 0


def test_collect_daily_lands_fno_by_append_after_derivatives():
    """The path that matters. An archive stage with no land stage after it is
    the 0058 boundary wearing a new hat."""
    sh = (Path(__file__).parents[1] / "scripts" / "collect_daily.sh").read_text()
    assert "src.ingest.fno --append" in sh
    assert sh.index("src.archive.derivatives") < sh.index("src.ingest.fno --append") < sh.index("src.warehouse import spine")
    assert "fno --build-spine" not in sh, "a nightly full rebuild is the thing --append exists to avoid"
