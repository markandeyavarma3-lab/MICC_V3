"""Tests for the trial-family scheme and the Track S partition.

These exist because on 2026-08-18 a verification pass found three gaps between
the two tracks, all of which would have surfaced only once Track S code ran:

  1. Track S had no exploration/confirmation partition at all
  2. a scan study could not be registered — no `scan` StudyKind, no scan confounds
  3. the trial counter, read literally, would have destroyed Track D

Gap 3 is the one that matters most, and `test_running_track_s_does_not_touch_track_d`
is its regression test.
"""

from __future__ import annotations

import pytest

from src.research.design import (
    ConfoundPlan,
    DesignRejected,
    HorizonPower,
    SidePrediction,
    StudyDesign,
    required_confounds,
)
from src.research.families import (
    FamilyError,
    charge,
    counter,
    family_ids,
    get,
    project_bar,
    project_counter,
    report,
)
from src.research.split import (
    ScanGuard,
    SplitViolation,
    entity_stratum,
    scan_spec,
    temporal_stratum,
)

pytestmark = pytest.mark.unit


# --- gap 3: the counter must not leak across tracks --------------------------


def test_running_track_s_does_not_touch_track_d():
    """THE REGRESSION TEST FOR THE WORST GAP FOUND.

    research.yml said the counter applied to "EVERYTHING"; scan.yml was silent.
    Read literally, a 31.9M-cell scan would have pushed Track D's bar from 3.71
    to 7.28, retroactively failing exp_001 and making every future deal study
    impossible. Track S would have killed Track D as collateral damage.
    """
    before = charge("TRACK_D_DEALS", 0).bar.required_t
    charge("TRACK_S_CALENDAR", 31_893_556)
    after = charge("TRACK_D_DEALS", 0).bar.required_t
    assert after == before, "a Track S scan moved Track D's bar"
    assert after == pytest.approx(3.71, abs=0.02)


def test_exp001_still_clears_after_the_family_scheme():
    """No recorded verdict may change as a side effect of fixing the scheme."""
    assert charge("TRACK_D_DEALS", 0).bar.clears(-3.93)


def test_a_scan_charges_its_own_family():
    c = charge("TRACK_S_CALENDAR", 1_000_000)
    assert c.trials_added == 1_000_000
    assert c.trials_after == counter("TRACK_S_CALENDAR") + 1_000_000
    assert c.dof == 20  # ~21 yearly observations per calendar cell


def test_the_calendar_family_carries_the_predecessors_completed_search():
    """31.9M cells of this space were already scanned. It is not virgin.

    A rebuild does not get to look at an already-searched space as though for
    the first time.
    """
    assert counter("TRACK_S_CALENDAR") >= 31_893_556
    assert get("TRACK_S_CALENDAR")["prior_external_search"] == 31_893_556


# --- the procedure exemption, and its limit ----------------------------------


def test_scan_width_does_not_charge_the_procedure_family():
    """The reasoning that makes 'scan wide to measure overfitting' legitimate.

    One procedure is under test per configuration; the 31.9M cells are the
    instrument that measures it, not competing hypotheses.
    """
    c = charge("TRACK_S_PROCEDURE", 31_893_556)
    assert c.trials_added == 0
    assert c.trials_after == 3  # one per top_n value
    assert c.bar.required_t < 3.0


def test_the_procedure_exemption_does_not_extend_to_pattern_families():
    """The moment a specific surviving pattern is reported, it pays full width."""
    proc = charge("TRACK_S_PROCEDURE", 31_893_556).bar.required_t
    patt = charge("TRACK_S_CALENDAR", 31_893_556).bar.required_t
    assert patt > proc * 3


# --- the project-level bar ---------------------------------------------------


def test_a_project_level_claim_faces_every_family():
    """A within-family bar answers 'best of the deal studies'. This answers
    'best of everything we tried'. Publishing only the friendlier one is the
    abuse the predecessor committed."""
    assert project_counter() == sum(counter(f) for f in family_ids())
    assert project_bar().required_t > charge("TRACK_D_DEALS", 0).bar.required_t


def test_report_shows_both_bars():
    text = report("TRACK_D_DEALS", 0)
    assert "within-family bar" in text and "project-level bar" in text


# --- anti-gaming -------------------------------------------------------------


def test_an_unknown_family_is_refused():
    with pytest.raises(FamilyError, match="unknown family"):
        charge("TRACK_X_CONVENIENT", 1)


def test_a_new_family_requires_a_decision_record():
    from src.research.families import spec

    assert spec()["rules"]["new_family_requires_decision_record"] is True
    assert spec()["rules"]["may_not_move_result_to_smaller_family"] is True
    assert spec()["rules"]["family_immutable_after_registration"] is True


def test_negative_trials_are_refused():
    with pytest.raises(FamilyError):
        charge("TRACK_D_DEALS", -1)


# --- gap 1: Track S now has a partition --------------------------------------


@pytest.mark.parametrize(
    ("date", "expected"),
    [("2005-01-03", "EXPLORE"), ("2015-12-31", "EXPLORE"),
     ("2016-01-01", "CONFIRM"), ("2026-08-18", "CONFIRM")],
)
def test_temporal_split_assigns_by_date(date, expected):
    assert temporal_stratum(date) == expected


def test_the_temporal_split_is_mandatory():
    """It is the only partition that can test persistence, which is what a
    pattern claim actually asserts."""
    assert scan_spec()["temporal"]["mandatory"] is True
    assert scan_spec()["require_both"] is True


def test_the_entity_split_is_only_corroborating():
    """202 indices overlap heavily — NIFTY 50 sits inside NIFTY 100, 500 and
    most sector indices. Its result is never independent confirmation."""
    e = scan_spec()["entity"]
    assert e["mandatory"] is False
    assert e["verdict_role"] == "corroborating_only"
    assert e["overlap_warning"] is True


def test_entity_split_hits_its_declared_fractions():
    from collections import Counter

    c = Counter(entity_stratum(f"INDEX_{i}") for i in range(4000))
    assert abs(c["EXPLORE"] / 4000 - 0.40) < 0.03


def test_scan_confirm_is_refused_without_registration():
    with pytest.raises(SplitViolation, match="without a registered study"):
        ScanGuard().check("2020-06-01", purpose="peek at confirmation data")


def test_scan_explore_is_free():
    assert ScanGuard().check("2010-06-01", purpose="mine freely") == "EXPLORE"


def test_scan_confirm_is_allowed_for_a_registered_study():
    g = ScanGuard(registered_experiment="exp_010_calendar_rescan")
    assert g.check("2020-06-01", purpose="the registered test") == "CONFIRM"


# --- gap 2: a scan study can be registered, but must declare its family ------


def _scan_design(**kw):
    base = dict(
        study_id="exp_010_calendar_rescan",
        kind="scan",
        mechanism=(
            "Flow calendars are institutional: index rebalances, SIP inflows and "
            "fiscal-year effects recur on the same trading days, so a persistent "
            "cross-sectional ranking should exist on those days if anywhere."
        ),
        side_predictions=(
            SidePrediction(
                statement="the effect concentrates on index rebalance dates",
                falsifies_if="rebalance dates rank no better than random dates",
            ),
        ),
        horizons=(HorizonPower("ic_5s", 568, 0.0140, plausible_bound=0.02),),
        confounds=tuple(ConfoundPlan(c, "REQUIRED") for c in required_confounds("scan")),
        trials_before=171,
        trial_family_id="TRACK_S_CALENDAR",
        nominal_folds=16,
        effective_folds=8.0,
    )
    base.update(kw)
    return StudyDesign(**base)


def test_a_complete_scan_design_is_accepted():
    assert _scan_design().kind == "scan"


def test_a_scan_without_a_declared_family_is_refused():
    """Otherwise the search is charged to whichever counter flatters it."""
    with pytest.raises(DesignRejected, match="declare its trial family BEFORE"):
        _scan_design(trial_family_id=None)


def test_a_scan_naming_an_unknown_family_is_refused():
    with pytest.raises(DesignRejected, match="unknown family"):
        _scan_design(trial_family_id="TRACK_S_WHATEVER")


def test_a_single_fold_scan_is_refused():
    """One fold is an in-sample fit — which is what the 31.9M atlas was."""
    with pytest.raises(DesignRejected, match="at least 2 folds"):
        _scan_design(nominal_folds=1)


def test_a_scan_must_declare_effective_folds():
    """Anchored windows share ~95% of training data; 16 folds are not 16 tests."""
    with pytest.raises(DesignRejected, match="effective_folds not declared"):
        _scan_design(effective_folds=None)


def test_effective_folds_cannot_exceed_nominal():
    with pytest.raises(DesignRejected, match="impossible"):
        _scan_design(nominal_folds=8, effective_folds=16.0)


def test_scan_confounds_cover_the_track_s_specific_risks():
    req = required_confounds("scan")
    for needed in ("multiple_testing_declared", "null_is_measured_not_assumed",
                   "fold_independence", "bid_ask_bounce", "prior_search_of_this_space"):
        assert needed in req, f"{needed} is not blocking for a scan"


def test_omitting_a_scan_confound_is_refused():
    partial = tuple(
        ConfoundPlan(c, "REQUIRED")
        for c in required_confounds("scan")
        if c != "bid_ask_bounce"
    )
    with pytest.raises(DesignRejected, match="bid_ask_bounce"):
        _scan_design(confounds=partial)


# --- persistence: the counters must actually move ----------------------------
#
# These exist because trials.yml declared the counters "monotonic, never reset"
# while nothing incremented them — charge() was a pure function and
# project_counter() summed static YAML. A 31.9M-cell scan could have run without
# moving anything, which is exp_001's `trials_before` failure rebuilt one level
# up, inside the file whose subject is that failure.


class TestPersistence:
    def test_a_committed_charge_moves_the_counter(self):
        from src.research.families import commit_charge, persisted_counter

        before = persisted_counter("TRACK_S_SIGNALS")
        commit_charge("TRACK_S_SIGNALS", 5_000, "unit test: signal grid")
        assert persisted_counter("TRACK_S_SIGNALS") == before + 5_000

    def test_persisted_counter_never_falls_below_the_yaml_carried_value(self):
        from src.research.families import counter, persisted_counter

        for fid in family_ids():
            assert persisted_counter(fid) >= counter(fid)

    def test_committing_to_one_family_leaves_the_others_alone(self):
        from src.research.families import commit_charge, persisted_counter

        before = persisted_counter("TRACK_D_DEALS")
        commit_charge("TRACK_S_SIGNALS", 100, "unit test: isolation check")
        assert persisted_counter("TRACK_D_DEALS") == before

    def test_the_procedure_family_records_a_zero_charge_rather_than_nothing(self):
        """'We ran a 31.9M-cell scan and it cost this family nothing' is a claim
        that belongs in the ledger, not inferred from a config.

        The invariant is absolute rather than relative: however wide the scan and
        however many times it runs, this family's counter stays at its fixed size,
        because exactly one procedure is under test per configuration.
        """
        from src.research.families import commit_charge, get, persisted_counter

        fixed = int(get("TRACK_S_PROCEDURE")["fixed_family_size"])
        for width in (31_893_556, 1_000_000, 5_000):
            c = commit_charge("TRACK_S_PROCEDURE", width, f"unit test: width {width}")
            assert c.trials_added == 0
            assert c.trials_after == fixed
            assert persisted_counter("TRACK_S_PROCEDURE") == fixed

    def test_a_charge_must_say_what_was_searched(self):
        from src.research.families import commit_charge

        with pytest.raises(FamilyError, match="what was searched"):
            commit_charge("TRACK_S_SIGNALS", 10, "   ")

    def test_the_ledger_is_append_only(self):
        import sqlite3

        from src.common.paths import governance_db
        from src.research.families import commit_charge

        commit_charge("TRACK_S_SIGNALS", 1, "unit test: append-only probe")
        con = sqlite3.connect(governance_db("dev"))
        try:
            for sql in ("UPDATE family_charge SET trials_added = 0",
                        "DELETE FROM family_charge"):
                with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                    con.execute(sql)
        finally:
            con.close()

    def test_monotonicity_is_enforced_by_trigger_not_by_promise(self):
        import sqlite3
        from datetime import UTC, datetime

        from src.common.paths import governance_db
        from src.research.families import commit_charge, persisted_counter

        commit_charge("TRACK_S_SIGNALS", 50, "unit test: monotonic probe")
        high = persisted_counter("TRACK_S_SIGNALS")
        con = sqlite3.connect(governance_db("dev"))
        try:
            with pytest.raises(sqlite3.IntegrityError, match="monotonic"):
                con.execute(
                    "INSERT INTO family_charge (family_id, trials_added, trials_after,"
                    " dof, required_t, description, recorded_at) VALUES (?,?,?,?,?,?,?)",
                    ("TRACK_S_SIGNALS", 0, high - 1, 20, 3.0, "rewind attempt",
                     datetime.now(UTC).isoformat()),
                )
        finally:
            con.close()
