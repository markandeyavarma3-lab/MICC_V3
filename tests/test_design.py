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
    return (HorizonPower("10s", 3345, 0.00163), HorizonPower("21s", 1600, 0.0031))


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
    assert d.required_t == pytest.approx(3.62, abs=0.02)
    assert len(d.powered_horizons) == 2


def test_summary_names_the_bar_and_the_dilution():
    d = _design(kind="portfolio", confounds=_confounds("portfolio"), expected_dilution=0.30)
    s = d.summary()
    assert "required |t|" in s and "3.6" in s
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
    d = _design(horizons=(HorizonPower("10s", 3345, 0.00163),
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
