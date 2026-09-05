"""deal_forward_outcomes — Plan 3 step 6.3, and the suspensions nobody saw.

Every study before this one recomputed forward returns inline, so nine horizons
and six benchmarks were specified and one horizon against one implicit benchmark
was measured. These tests pin the table those studies were meant to read, and
the defect building it exposed: `LEAD(close, 252)` counts ROWS, not sessions, so
a name suspended for five years supplied its 252nd row years later and the
result was labelled a twelve-month return.
"""

from __future__ import annotations

import duckdb
import pytest

from src.common.paths import research_db
from src.research import outcomes

pytestmark = pytest.mark.needs_data


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(research_db("prod")), read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="module")
def rows(con):
    return con.execute(
        "SELECT COUNT(*) FROM deal_forward_outcomes "
        "WHERE calculation_version = ?", [outcomes.CALCULATION_VERSION]).fetchone()[0]


def test_the_table_is_not_empty(rows):
    """It held 0 rows from the day the schema landed until 2026-09-05."""
    assert rows > 40_000


def test_all_nine_horizons_are_present(con):
    """Plan 3 step 6.3 says nine. They are derived from research.yml rather than
    restated, so a config edit that drops one must fail here."""
    hs = {h[0] for h in con.execute(
        "SELECT DISTINCT horizon_sessions FROM deal_forward_outcomes "
        "WHERE calculation_version = ?", [outcomes.CALCULATION_VERSION]).fetchall()}
    assert hs == {s for s, _ in outcomes.horizons()}
    assert len(hs) == 9


def test_a_horizon_never_spans_more_calendar_time_than_it_claims(con):
    """THE DEFECT THIS STEP FOUND.

    `LEAD(close, N)` is N traded ROWS. ATLASCYCLE supplied its 252nd row 3,506
    days — 9.6 years — after the event, and that was carried as a twelve-month
    outcome at -117.8% abnormal. 37 of 1,145 EXPLORE sell events span over 500
    days; they average -51.4% against -29.6% for the rest, moving the published
    headline from -29.59% to -30.30%.

    A HORIZON exit must fit inside the calendar span its own horizon allows.
    Anything wider is a suspension and is classified as one.
    """
    bad = con.execute("""
        SELECT COUNT(*) FROM deal_forward_outcomes
        WHERE calculation_version = ? AND exit_reason = 'HORIZON'
          AND date_diff('day', entry_date, exit_date) >
              horizon_sessions * 365.0 / 252.0 * 1.5 + 10
    """, [outcomes.CALCULATION_VERSION]).fetchone()[0]
    assert bad == 0, f"{bad} HORIZON exits span more calendar time than allowed"


def test_suspensions_are_found_rather_than_absorbed(con):
    """Plan 2 §3.4 names SUSPENDED as one of four cases and nothing could ever
    detect it — 0052 said as much. If this returns zero, the detector has
    stopped working and suspensions are back to being counted as ordinary."""
    n = con.execute(
        "SELECT COUNT(*) FROM deal_forward_outcomes "
        "WHERE calculation_version = ? AND exit_reason = 'SUSPENDED'",
        [outcomes.CALCULATION_VERSION]).fetchone()[0]
    assert n > 0


def test_recovery_factors_attach_to_terminated_positions_only(con):
    """A HORIZON exit realises a real price, so a recovery factor is meaningless
    on it. A DELISTED or SUSPENDED one is marked at last price and takes all
    three (Plan 2 §3.4, headline 0.0)."""
    wrong = con.execute("""
        SELECT
          COUNT(*) FILTER (WHERE exit_reason = 'HORIZON' AND recovery_factor IS NOT NULL),
          COUNT(*) FILTER (WHERE exit_reason <> 'HORIZON' AND recovery_factor IS NULL)
        FROM deal_forward_outcomes WHERE calculation_version = ?
    """, [outcomes.CALCULATION_VERSION]).fetchone()
    assert wrong == (0, 0)

    factors = {r[0] for r in con.execute(
        "SELECT DISTINCT recovery_factor FROM deal_forward_outcomes "
        "WHERE calculation_version = ? AND recovery_factor IS NOT NULL",
        [outcomes.CALCULATION_VERSION]).fetchall()}
    assert factors == set(outcomes.RECOVERY_FACTORS)


def test_excursions_bracket_the_position(con):
    """MAE is the worst the position went and cannot be positive; MFE is the
    best and cannot be negative. Both are measured from the entry price, so a
    sign violation means the window is misaligned with the entry."""
    bad = con.execute("""
        SELECT COUNT(*) FROM deal_forward_outcomes
        WHERE calculation_version = ?
          AND (max_adverse_excursion > 0 OR max_favorable_excursion < 0)
    """, [outcomes.CALCULATION_VERSION]).fetchone()[0]
    assert bad == 0


def test_cost_is_applied_and_is_not_free(con):
    """net_return runs through the Plan 2 §4 model. costs.yml's headline NSE
    round trip is 29.33 bps; a net return equal to the gross one means the cost
    leg silently did nothing."""
    gap = con.execute("""
        SELECT avg(stock_return - net_return) * 1e4
        FROM deal_forward_outcomes
        WHERE calculation_version = ? AND outcome_complete_flag
    """, [outcomes.CALCULATION_VERSION]).fetchone()[0]
    assert 15 < gap < 45, f"round-trip cost averaged {gap:.1f} bps"


def test_no_outcome_is_written_for_an_event_with_no_outcome(con):
    """CENSORED events — still trading, horizon runs past the data — get no row
    at all. 0052 established that pricing them at a recovery factor would invent
    a delisting for a live company."""
    reasons = {r[0] for r in con.execute(
        "SELECT DISTINCT exit_reason FROM deal_forward_outcomes "
        "WHERE calculation_version = ?", [outcomes.CALCULATION_VERSION]).fetchall()}
    assert "CENSORED" not in reasons
