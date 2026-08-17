"""Tests for the multiplicity bar.

The point of this module is that `trials_before` stops being a diary entry. So
the tests are mostly about the bar MOVING when the trial count moves, and about
it being impossible to argue the bar downwards.
"""

from __future__ import annotations

import math

import pytest
from scipy.stats import norm

from src.research.multiplicity import (
    EULER_GAMMA,
    MultiplicityError,
    bar,
    effective_trials,
    expected_max_null_t,
    sidak_alpha,
)

pytestmark = pytest.mark.unit


# --- the core arithmetic -----------------------------------------------------


def test_a_single_trial_expects_nothing():
    assert expected_max_null_t(1) == 0.0


def test_expected_max_grows_with_the_number_of_trials():
    prev = -1.0
    for n in (1, 10, 100, 171, 1_000, 10_000, 31_893_556):
        cur = expected_max_null_t(n)
        assert cur > prev, f"E[max t] did not increase at n={n}"
        prev = cur


@pytest.mark.parametrize(
    ("trials", "expected"),
    [(10, 1.57), (100, 2.53), (171, 2.71), (1_000, 3.26), (31_893_556, 5.51)],
)
def test_expected_max_matches_the_published_estimator(trials, expected):
    """Golden values, recomputed from the Lopez de Prado formula directly.

    Pinned because these are the numbers quoted in Plan 2 and the decision
    records; if the estimator changes, the documents become wrong.
    """
    assert expected_max_null_t(trials) == pytest.approx(expected, abs=5e-3)


def test_estimator_agrees_with_an_independent_derivation():
    # Recomputed here from the formula rather than from the module, so a typo in
    # the module cannot pass by matching itself.
    n = 171.0
    manual = (1 - EULER_GAMMA) * norm.ppf(1 - 1 / n) + EULER_GAMMA * norm.ppf(
        1 - 1 / (n * math.e)
    )
    assert expected_max_null_t(171) == pytest.approx(manual, rel=1e-12)


def test_estimator_tracks_the_sqrt_2_ln_n_asymptotic_at_large_n():
    # Not equal — the asymptotic is crude at working N, which is why it is not
    # what the module uses — but they must be in the same neighbourhood.
    for n in (10_000, 1_000_000):
        assert expected_max_null_t(n) == pytest.approx(math.sqrt(2 * math.log(n)), rel=0.20)


# --- the bar -----------------------------------------------------------------


def test_more_trials_means_a_higher_bar():
    """The entire purpose of the module in one assertion."""
    prev = -1.0
    for n in (1, 10, 100, 171, 1_000, 31_893_556):
        cur = bar(n).required_t
        assert cur > prev, f"bar did not rise at {n} trials"
        prev = cur


def test_the_project_bar_at_its_actual_trial_count():
    """171 is where this project stands: 68 carried + ~100 exploratory + logged."""
    b = bar(171)
    assert b.required_t == pytest.approx(3.62, abs=0.02)
    assert b.expected_max_null_t == pytest.approx(2.71, abs=0.02)


def test_exp001_event_effect_clears_the_bar_only_narrowly():
    """t = -3.93 against a required 3.62. Real, but not comfortably so.

    Consistent with the registration's own prior: at ~100 cells of search, a
    single winner near t = -3.9 is close to what noise produces.
    """
    b = bar(171)
    assert b.clears(-3.93)
    assert not b.clears(-3.50)
    assert abs(-3.93) / b.required_t < 1.10, "margin over the bar is under 10%"


def test_the_seasonality_atlas_faces_a_brutal_bar():
    """31.9M cells. The predecessor's best pattern sat at the 94th percentile of
    rotated noise, which is nowhere near this."""
    b = bar(31_893_556)
    assert b.required_t > 6.5
    assert not b.clears(3.0)


def test_the_noise_floor_binds_at_very_large_trial_counts():
    # At small N the classical family-wise value binds; at huge N the expected
    # noise maximum does. Both regimes must be reachable or one branch is dead.
    assert "family-wise" in bar(171).rationale
    assert "noise-max" in bar(31_893_556).rationale


def test_margin_is_disclosed_as_a_judgement_not_a_derivation():
    assert "judgement, not a" in bar(171).rationale


# --- correlation cannot be used to argue the bar down ------------------------


def test_correlated_trials_count_for_less():
    assert effective_trials(100, 0.0) == pytest.approx(100)
    assert effective_trials(100, 0.5) < 3


def test_effective_trials_never_exceeds_nominal_or_falls_below_one():
    assert effective_trials(100, 0.0) <= 100
    assert effective_trials(100, 0.99) >= 1.0
    assert effective_trials(1, 0.9) == 1.0


def test_claiming_correlation_lowers_the_bar_but_never_below_a_single_trial():
    high = bar(1_000).required_t
    low = bar(1_000, mean_correlation=0.9).required_t
    assert low < high
    assert low >= bar(1).required_t


# --- refusals ----------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1])
def test_nonsense_trial_counts_are_refused(bad):
    with pytest.raises(MultiplicityError):
        bar(bad)


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5])
def test_nonsense_alpha_is_refused(bad):
    with pytest.raises(MultiplicityError):
        sidak_alpha(bad, 10)


def test_negative_margin_is_refused():
    with pytest.raises(MultiplicityError):
        bar(171, margin=-0.1)
