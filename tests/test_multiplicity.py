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
    [(10, 1.90), (100, 2.77), (171, 2.94), (1_000, 3.45), (31_893_556, 5.63)],
)
def test_expected_max_matches_the_published_estimator(trials, expected):
    """Golden values, TWO-SIDED, corrected 2026-08-18.

    The original values (1.57 / 2.53 / 2.71 / 3.26 / 5.51) were E[max of SIGNED
    normals] while `Bar.clears()` compares abs(t). The module matched a one-sided
    maximum and was applied two-sided, understating every bar it produced.
    Verified against Monte Carlo: at N=171, max(z)=2.693 but max|z|=2.922.

    Pinned because these numbers are quoted in the plans, the decision records
    and the HOD report; if the estimator changes, those documents become wrong.
    """
    assert expected_max_null_t(trials) == pytest.approx(expected, abs=5e-3)


def test_estimator_agrees_with_an_independent_derivation():
    # Recomputed here from the formula rather than from the module, so a typo in
    # the module cannot pass by matching itself.
    n = 171.0
    q = lambda p: norm.ppf((1 + p) / 2)  # noqa: E731 - two-sided |z| quantile
    manual = (1 - EULER_GAMMA) * q(1 - 1 / n) + EULER_GAMMA * q(1 - 1 / (n * math.e))
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
    assert b.required_t == pytest.approx(3.67, abs=0.02)
    assert b.expected_max_null_t == pytest.approx(2.94, abs=0.02)


def test_exp001_event_effect_clears_the_bar_only_narrowly():
    """t = -3.93 against a required 3.71 (df=246). Real, but not comfortably so.

    Consistent with the registration's own prior: at ~100 cells of search, a
    single winner near t = -3.9 is close to what noise produces.
    """
    b = bar(171, dof=246)
    assert b.clears(-3.93)
    assert not b.clears(-3.50)
    assert abs(-3.93) / b.required_t < 1.10, "margin over the bar is under 10%"


def test_the_seasonality_atlas_faces_a_brutal_bar():
    """31.9M cells. The predecessor's best pattern sat at the 94th percentile of
    rotated noise, which is nowhere near this."""
    b = bar(31_893_556)
    assert b.required_t > 7.0
    assert not b.clears(3.0)


def test_both_binding_regimes_are_reachable():
    # At small N the classical family-wise value binds; from ~100 trials upward
    # the expected noise maximum does. Both branches must be live or one is dead
    # code. The crossover moved DOWN when the floor became two-sided: at 171
    # trials family-wise used to bind (3.62) and now noise-max does (3.67).
    assert "family-wise" in bar(10).rationale
    assert "noise-max" in bar(171).rationale
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


# --- degrees of freedom (added 2026-08-18, after measurement) ----------------


class TestDegreesOfFreedom:
    """The correction that points the DANGEROUS way.

    Ignoring correlation between trials is conservative. Ignoring the fat tails
    of the t-distribution is not — it makes the bar too LOW, so results pass too
    easily. Track D is unaffected (df=246); Track S is affected badly (df=20).
    """

    def test_fat_tails_raise_the_expected_maximum(self):
        normal = expected_max_null_t(3146)
        assert expected_max_null_t(3146, dof=20) > normal * 1.15
        assert expected_max_null_t(3146, dof=60) > normal

    def test_high_dof_converges_to_the_normal_assumption(self):
        assert expected_max_null_t(3146, dof=100_000) == pytest.approx(
            expected_max_null_t(3146), rel=0.01
        )

    def test_expected_max_is_monotone_decreasing_in_dof(self):
        prev = float("inf")
        for df in (10, 20, 60, 246, 10_000):
            cur = expected_max_null_t(3146, dof=df)
            assert cur < prev
            prev = cur

    @pytest.mark.parametrize(
        ("trials", "dof", "expected"),
        [(100, 20, 3.101), (3146, 20, 4.588), (3146, 246, 3.804), (100_000, 20, 6.118)],
    )  # two-sided |t|, validated against Monte Carlo to within 1.0%
    def test_formula_matches_monte_carlo(self, trials, dof, expected):
        """Validated against direct simulation; max error 1.0% across the grid."""
        assert expected_max_null_t(trials, dof=dof) == pytest.approx(expected, abs=5e-3)

    def test_track_d_bar_is_essentially_unchanged_by_dof(self):
        """247 monthly cohorts give df=246, indistinguishable from normal."""
        assert bar(171, dof=246).required_t == pytest.approx(3.71, abs=0.03)

    def test_track_s_bar_rises_sharply_with_low_dof(self):
        """3,146 calendar cells on 21 yearly observations. The normal
        assumption said 4.68; the truth is 5.73 — a 22% understatement."""
        naive = bar(3146).required_t
        corrected = bar(3146, dof=20).required_t
        assert corrected > naive * 1.20

    def test_bad_dof_is_refused(self):
        with pytest.raises(MultiplicityError):
            expected_max_null_t(100, dof=0)

    def test_rationale_discloses_dof_when_used(self):
        assert "dof=20" in bar(3146, dof=20).rationale
        assert "dof=" not in bar(3146).rationale


class TestSimulatedNull:
    """When the grid geometry matters, measure it rather than assume it."""

    def test_simulated_null_recovers_a_known_iid_case(self):
        import numpy as np

        from src.research.multiplicity import simulated_max_null_t

        mean, sd = simulated_max_null_t(
            lambda rng: np.abs(rng.standard_normal(1000)).max(), reps=400, seed=0
        )
        # Both are now two-sided, so they must agree.
        assert mean == pytest.approx(expected_max_null_t(1000), abs=0.10)
        assert sd > 0

    def test_correlation_lowers_the_simulated_maximum(self):
        import numpy as np

        from src.research.multiplicity import simulated_max_null_t

        def sampler(rho):
            def f(rng):
                common = rng.standard_normal()
                idio = rng.standard_normal(1000)
                return np.abs(np.sqrt(rho) * common + np.sqrt(1 - rho) * idio).max()
            return f

        lo, _ = simulated_max_null_t(sampler(0.0), reps=300, seed=1)
        hi, _ = simulated_max_null_t(sampler(0.7), reps=300, seed=1)
        assert hi < lo
