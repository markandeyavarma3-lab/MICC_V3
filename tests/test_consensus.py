"""The consensus study's event construction, which its whole result rests on.

0031 put consensus on the critical path. If the constructor over-fires, the
power estimate is optimistic and a study gets registered that should not be; if
it under-fires, the project abandons a viable study. Both errors are silent —
the row counts look plausible either way — so the definition is pinned here.
"""

from __future__ import annotations

import pytest

from src.research import consensus

pytestmark = pytest.mark.unit


def test_the_threshold_and_window_match_the_config():
    """participants.yml is the owner's decision; this file must not drift from
    it. The alternates exist as declared robustness runs, never as a search for
    the threshold that produces a result."""
    import yaml
    from src.common.paths import CONFIGS

    spec = yaml.safe_load((CONFIGS / "participants.yml").read_text())["consensus"]
    assert consensus.THRESHOLD == spec["threshold_institutions"]
    assert consensus.WINDOW_SESSIONS == spec["window_sessions"]
    assert spec["primary_definition"] == "distinct_participant_name", (
        "consensus.py keys on the raw client name; if the primary definition "
        "changes to parent grouping the constructor must change with it"
    )


def test_both_bases_are_measured_and_neither_is_chosen_silently():
    """The modelling decision this study cannot make on its own.

    For a bulk buy the event IS the trade, so an untradeable deal is not an
    event — 0038's argument. For consensus the event is a convergence and the
    trade is a position of my own choosing, so the ceiling arguably applies to
    my position rather than to theirs. Reporting only one basis would bury that.
    """
    src = (consensus.__file__)
    text = open(src).read()
    assert "STRICT" in text and "PERMISSIVE" in text
    strict = consensus._events_sql(strict=True)
    perm = consensus._events_sql(strict=False)
    assert "eligible_for_research" in strict
    assert "eligible_for_research" not in perm, (
        "the permissive basis must not silently re-apply the participation cap"
    )


def test_the_permissive_basis_still_removes_what_is_not_conviction():
    """A same-day round trip is a market maker's inventory and a PROP_HFT
    participant is 100% round-trip by measurement. Neither is an institution
    converging on a view, and counting them would inflate every event count."""
    perm = consensus._events_sql(strict=False)
    assert "same_day_round_trip_flag" in perm
    assert "PROP_HFT" in perm
    assert "side = 'BUY'" in perm, "sells are a different study (0031)"


def test_events_fire_on_the_crossing_not_the_state():
    """THE DEFECT THIS PREVENTS. Counting every session on which 3+ institutions
    are inside the trailing window turns one convergence into an event per
    session it persists — measured 2026-09-01 at 5,952 session-states against
    2,374 crossings, a 2.5x inflation of n that flows straight into the MDE."""
    sql = consensus._events_sql(strict=False)
    assert "LAG(n_inst)" in sql, "no crossing detection — this counts states"
    assert f"< {consensus.THRESHOLD}" in sql, (
        "the previous count must be BELOW the threshold for a crossing"
    )


def test_the_window_is_trading_sessions_not_calendar_days():
    """A calendar window silently widens across holidays. The observed calendar
    has three Saturday sessions no generated one would hold."""
    sql = consensus._events_sql(strict=True)
    assert "ROW_NUMBER() OVER (ORDER BY date)" in sql, "no session index"
    assert f"s.i - {consensus.WINDOW_SESSIONS - 1}" in sql, (
        "the window must be expressed in session indices"
    )


def test_the_bound_is_the_same_rule_as_the_bulk_study():
    """Consensus must not get a friendlier bar than 0038 applied to bulk buys.
    Both scale linearly with horizon at research.yml's rate (0028)."""
    from src.research import measure

    v = consensus.Verdict("STRICT", "252s (12m)", 12.0, 100, 50, 0.5, 0.10)
    assert v.bound == pytest.approx(measure.BOUND_PER_MONTH * 12.0)
    assert not v.powered, "10% MDE against a 6% bound is not powered"
