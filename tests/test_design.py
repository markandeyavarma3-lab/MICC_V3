"""Tests for the pre-registration design gate.

The test that matters most is `test_exp001_as_designed_would_be_rejected`. If the
gate cannot catch the defect this project has already committed, it is decoration.
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

pytestmark = pytest.mark.unit


MECHANISM = (
    "Institutions that sell into the market are more often acting on private "
    "information than institutions that buy, because buying is driven by inflows, "
    "index tracking and rebalancing while selling is comparatively discretionary."
)


def _side_predictions():
    return (
        SidePrediction(
            statement="the effect scales monotonically with deal value / ADV20",
            falsifies_if="the deal-size quintiles are flat or non-monotonic",
        ),
    )


def _confounds(kind="event_study", **overrides):
    return tuple(
        ConfoundPlan(cid, overrides.get(cid, "REQUIRED"),
                     "n/a" if overrides.get(cid) == "NOT_APPLICABLE" else "")
        for cid in required_confounds(kind)
    )


def _powered():
    # Session horizons must state their own bound: decision 0018 is OPEN, so the
    # per-month config default may not be silently applied to a 10-session MDE.
    return (
        HorizonPower("10s", 3345, 0.00163, plausible_bound=0.0024),
        HorizonPower("21s", 1600, 0.0031, plausible_bound=0.0050),
    )


def _design(**kw):
    base = dict(
        study_id="exp_002_institutional_selling",
        kind="event_study",
        mechanism=MECHANISM,
        side_predictions=_side_predictions(),
        horizons=_powered(),
        confounds=_confounds(),
        trials_before=171,
    )
    base.update(kw)
    return StudyDesign(**base)


# --- the happy path ----------------------------------------------------------


def test_a_complete_design_is_accepted():
    d = _design()
    assert d.required_t == pytest.approx(3.67, abs=0.02)
    assert len(d.powered_horizons) == 2


def test_summary_names_the_bar_and_the_dilution():
    d = _design(kind="portfolio", confounds=_confounds("portfolio"), expected_dilution=0.30)
    s = d.summary()
    assert "required |t|" in s and "3.6" in s  # 3.67 at 171 trials
    assert "30.00% of the book" in s


# --- rule 1: computed MDE, not a template ------------------------------------


def test_a_study_blind_at_every_horizon_is_refused():
    """The defect the original plan shipped with.

    At 12 months MDE is 7.38% against a plausible bound of 0.50%, and the
    "+7.80% signal" sat directly on its own detection floor.
    """
    with pytest.raises(DesignRejected, match="EVERY horizon is underpowered"):
        _design(horizons=(HorizonPower("12m", 247, 0.0738),
                          HorizonPower("24m", 120, 0.1150)))


def test_a_study_with_one_powered_horizon_survives():
    # Mixed is fine — the weak horizons report UNDERPOWERED, which is silence
    # rather than a negative. Only total blindness is a design defect.
    d = _design(horizons=(HorizonPower("10s", 3345, 0.00163, plausible_bound=0.0024),
                          HorizonPower("12m", 247, 0.0738)))
    assert len(d.powered_horizons) == 1
    assert len(d.underpowered_horizons) == 1
    assert "UNDERPOWERED" in d.summary()


def test_declaring_no_horizons_is_refused():
    with pytest.raises(DesignRejected, match="no horizons"):
        _design(horizons=())


# --- rule 2: mechanism and a side-prediction that can fail -------------------


def test_a_missing_mechanism_is_refused():
    with pytest.raises(DesignRejected, match="mechanism is missing or too thin"):
        _design(mechanism="measure it and see")


def test_a_mechanism_without_side_predictions_is_refused():
    with pytest.raises(DesignRejected, match="no side-predictions"):
        _design(side_predictions=())


def test_a_side_prediction_with_no_failure_condition_is_refused():
    """A prediction that cannot fail is a description, satisfiable after the fact."""
    with pytest.raises(DesignRejected, match="cannot fail is a description"):
        SidePrediction(statement="the effect will be interesting", falsifies_if="   ")


# --- rule 3: the checklist is run, not remembered ----------------------------


def test_omitting_a_blocking_confound_is_refused():
    partial = tuple(c for c in _confounds() if c.confound_id != "microstructure")
    with pytest.raises(DesignRejected, match="microstructure"):
        _design(confounds=partial)


def test_a_confound_may_be_skipped_only_in_writing():
    with pytest.raises(DesignRejected, match="no written reason"):
        ConfoundPlan("volatility", "NOT_APPLICABLE", "")


def test_a_confound_skipped_with_a_reason_is_accepted():
    plans = tuple(
        ConfoundPlan(c.confound_id, "NOT_APPLICABLE", "single-sector study by design")
        if c.confound_id == "sector_concentration" else c
        for c in _confounds()
    )
    assert "sector_concentration" in _design(confounds=plans).summary()


def test_unknown_confound_ids_are_refused():
    with pytest.raises(DesignRejected, match="unknown confound"):
        _design(confounds=_confounds() + (ConfoundPlan("vibes", "REQUIRED"),))


def test_microstructure_is_blocking_for_every_event_study():
    # It ate 71% of the 1-day effect. It does not get to be optional.
    assert "microstructure" in required_confounds("event_study")


def test_dilution_is_blocking_for_portfolio_studies():
    assert "dilution" in required_confounds("portfolio")


# --- economic significance, computed before ----------------------------------


def test_a_portfolio_study_without_a_dilution_estimate_is_refused():
    with pytest.raises(DesignRejected, match="expected dilution BEFORE"):
        _design(kind="portfolio", confounds=_confounds("portfolio"))


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5])
def test_nonsense_dilution_is_refused(bad):
    with pytest.raises(DesignRejected, match="not a fraction"):
        _design(kind="portfolio", confounds=_confounds("portfolio"), expected_dilution=bad)


# --- the one that justifies the module ---------------------------------------


def test_exp001_as_designed_would_be_rejected():
    """exp_001 reached a verdict. This gate would have stopped it first.

    Its actual design, as registered on 2026-08-16:

      - a hypothesis with a DIRECTION but no mechanism — "such names underperform
        volatility-matched peers by ~0.805%" restates the finding, it does not
        explain why institutions selling should predict anything
      - no side-predictions, so nothing beyond the headline could fail
      - dilution assumed at 2.4% and never computed; the true figure was 1.2%,
        which made the pass bar exactly the full expected effect rather than half
        of it, and explained the entire gap between t -3.93 and t -0.25

    Any one of the three is fatal here. The study still ran, and its rejection was
    correct — but it was rejected by its holdout after a day of work, not by its
    design in an afternoon.
    """
    with pytest.raises(DesignRejected, match="no side-predictions"):
        _design(
            study_id="exp_001_bulk_deal_avoidance_filter",
            mechanism=(
                "A long-only top-500 book that excludes names with a disclosed "
                "bulk-deal BUY in the trailing 10 sessions earns more, because "
                "such names underperform volatility-matched peers by ~0.805%."
            ),
            side_predictions=(),
        )

    # And separately, as a portfolio study it could not have been registered at
    # all without stating the number nobody computed.
    with pytest.raises(DesignRejected, match="expected dilution BEFORE"):
        _design(
            study_id="exp_001_bulk_deal_avoidance_filter",
            kind="portfolio",
            confounds=_confounds("portfolio"),
        )


# --- three integration bugs found 2026-08-18, all making the bar too easy ----


class TestBarIntegration:
    """The design gate computed bars that ignored the machinery built to set them.

    Every one of these made results EASIER to pass, which is the direction that
    matters.
    """

    def test_the_bar_uses_the_declared_family_not_raw_trials_before(self):
        """BUG: `trial_family_id` was validated and then never used.

        A scan declaring TRACK_S_CALENDAR — which carries 31,893,556 prior trials
        from the predecessor's completed atlas — was handed a bar computed from
        trials_before=171. That is |t| >= 3.67 where the truth is 11.76. The
        family scheme was built the same day to prevent exactly this, and the
        design gate walked straight past it.
        """
        from src.research.families import charge

        d = StudyDesign(
            study_id="exp_011_scan_bar_check",
            kind="scan",
            mechanism=MECHANISM,
            side_predictions=_side_predictions(),
            horizons=(HorizonPower("ic_5s", 568, 0.0140, plausible_bound=0.02),),
            confounds=tuple(ConfoundPlan(c, "REQUIRED") for c in required_confounds("scan")),
            trials_before=171,
            trial_family_id="TRACK_S_CALENDAR",
            nominal_folds=16,
            effective_folds=8.0,
        )
        assert d.required_t == pytest.approx(
            charge("TRACK_S_CALENDAR", 0).bar.required_t, abs=0.01
        )
        assert d.required_t > 10, "the 31.9M prior search is not being charged"

    def test_declaring_dof_raises_the_bar(self):
        """BUG: `bar()` was called with no dof, assuming a normal distribution.

        For a statistic on few observations the t has far fatter tails, so the
        normal assumption understates the bar — 22% for a calendar cell on 21
        yearly observations.
        """
        loose = _design().required_t
        tight = _design(dof=20).required_t
        assert tight > loose * 1.15

    def test_track_d_dof_is_a_small_correction(self):
        """247 monthly cohorts give df=246, indistinguishable from normal."""
        assert _design(dof=246).required_t == pytest.approx(_design().required_t, abs=0.06)


class TestOpenDecisionStopsTheCode:
    """Decision 0018 is unresolved. The code must refuse, not guess."""

    def test_a_session_horizon_without_an_explicit_bound_is_refused(self):
        """BUG: it silently compared a 1-session MDE to a PER-MONTH bound.

        A unit error that made short horizons look powered when they may not be.
        """
        with pytest.raises(DesignRejected, match="unit error"):
            _design(horizons=(HorizonPower("1s", 3345, 0.00191),))

    def test_a_monthly_horizon_may_still_use_the_config_default(self):
        h = HorizonPower("12m", 247, 0.0738)
        assert h.is_powered is False  # 7.38% against a 0.50% bound

    def test_an_explicit_bound_is_always_honoured(self):
        assert HorizonPower("1s", 3345, 0.00191, plausible_bound=0.0024).is_powered
        assert not HorizonPower("1s", 3345, 0.00191, plausible_bound=0.0010).is_powered

    @pytest.mark.parametrize("label", ["12m", "3 months", "6mo", "1M"])
    def test_monthly_labels_are_recognised(self, label):
        from src.research.design import _is_monthly_horizon

        assert _is_monthly_horizon(label)

    @pytest.mark.parametrize("label", ["10s", "ic_5s", "21s", "10d", "session_5"])
    def test_non_monthly_labels_are_not(self, label):
        from src.research.design import _is_monthly_horizon

        assert not _is_monthly_horizon(label)
