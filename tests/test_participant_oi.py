"""participant_oi — the FII/DII proxy that sat unread in the seed for two weeks.

sources.yml has carried this table since decision 0027: 15,359 rows,
2014-01-01 -> 2026-06-25, F&O open interest by participant type. An audit found
109 of the seed's 119 tables were never loaded by any code, and this was one of
them. Real cash-flow FII/DII history is nearly unobtainable retrospectively
(sources.yml's own note); this table gives eleven years for the cost of a load.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.needs_data


@pytest.fixture(scope="module")
def loaded():
    from src.warehouse import participant_oi
    n = participant_oi.load("prod")
    return n


def test_the_full_seed_span_is_loaded(loaded):
    """15,359 rows, 2014-01-01 -> 2026-06-25 — the number sources.yml has
    quoted since 0027. A short load means the seed file or the join dropped
    rows silently."""
    assert loaded == 15_359


def test_the_load_is_idempotent(loaded):
    """Re-running must replace, not append. A doubled table would make every
    downstream SUM wrong by 2x without any error."""
    from src.warehouse import participant_oi
    n2 = participant_oi.load("prod")
    assert n2 == loaded == 15_359


def test_total_is_a_computed_row_not_a_sixth_participant(loaded):
    """THE TRAP THIS TABLE SETS FOR AN UNWARNED READER. TOTAL sums the other
    four categories. A naive SUM(...) GROUP BY session_date across all rows
    silently doubles the true figure. Measured on 2026-06-25: naive SUM is
    838,576, correct (excluding TOTAL) is 419,288 — exactly 2x.
    """
    import duckdb

    from src.common.paths import research_db

    con = duckdb.connect(str(research_db("prod")), read_only=True)
    try:
        naive = con.execute(
            "SELECT SUM(index_fut_long) FROM participant_oi WHERE session_date=?",
            ["2026-06-25"],
        ).fetchone()[0]
        real = con.execute(
            "SELECT SUM(index_fut_long) FROM participant_oi "
            "WHERE session_date=? AND category != 'TOTAL'", ["2026-06-25"],
        ).fetchone()[0]
    finally:
        con.close()
    assert naive == pytest.approx(2 * real), (
        "TOTAL no longer looks like a doubling row; verify the source shape "
        "has not changed before relying on this test as documentation"
    )


def test_the_schema_rejects_an_unknown_category():
    """Migration 0004's CHECK constraint. A sixth category value should fail
    loudly at INSERT, not silently widen what 'participant' means."""
    import duckdb

    from src.common.paths import research_db

    con = duckdb.connect(str(research_db("prod")))
    try:
        with pytest.raises(duckdb.ConstraintException):
            con.execute(
                "INSERT INTO participant_oi (session_date, category) "
                "VALUES ('2020-01-01', 'Retail')"
            )
    finally:
        con.close()


def test_no_row_is_labelled_flow():
    """sources.yml, in capitals: this is DERIVATIVES POSITIONING, NOT
    CASH-MARKET FLOW. The loader's vocabulary must not blur that — a 'flow'
    column name would let a future query mistake a position for a trade."""
    import inspect

    from src.warehouse import participant_oi

    src = inspect.getsource(participant_oi)
    assert "flow" not in src.lower() or "cash-market flow" in src.lower() or (
        "not cash" in src.lower()
    ), "the module may be using 'flow' language for a positioning table"


def test_registered_once_not_twice_on_reload(loaded):
    """Re-running load() must not create a second provenance artefact for the
    same logical dataset."""
    import sqlite3

    from src.common.paths import governance_db
    from src.warehouse import participant_oi

    participant_oi.load("prod")
    con = sqlite3.connect(governance_db("prod"))
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM artefact WHERE logical_name = "
            "'v1seed:participant_oi'"
        ).fetchone()[0]
    finally:
        con.close()
    assert n == 1
