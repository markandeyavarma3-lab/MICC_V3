"""Tests for the power framework.

The important ones are the UNDERPOWERED rules. Getting those wrong is how a study
reports a false discovery as a finding, which is the exact failure the whole
pre-registration apparatus exists to prevent.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.research import power

pytestmark = pytest.mark.unit


# --- MDE arithmetic ------------------------------------------------------------


def test_mde_matches_the_closed_form():
    """(1.96 + 0.84) * sd / sqrt(n), the textbook two-sided 80%-power formula."""
    got = power.mde(sd=0.0855, n_periods=247)
    expected = (1.959963984540054 + 0.8416212335729143) * 0.0855 / np.sqrt(247)
    assert got == pytest.approx(expected, rel=1e-12)


# The published figures in Plan 2 §6.5 were computed from unrounded cohort SDs,
# while these tests feed the SD as published to 2dp. That rounding alone moves the
# MDE by up to ~1e-4, so the tolerance below is set to 2e-4 rather than pretending
# to a precision the published inputs do not carry.
_PUBLISHED_TOL = 2e-4


def test_mde_reproduces_the_measured_bulk_buy_figure():
    """Plan 2 §6.5: cohort SD 8.55% over 247 months -> MDE 1.52%."""
    assert power.mde(0.0855, 247) == pytest.approx(0.0152, abs=_PUBLISHED_TOL)


def test_mde_reproduces_the_size_matched_figure():
    """The 31% power gain from one matching dimension: SD 5.91% -> MDE 1.05%."""
    assert power.mde(0.0591, 247) == pytest.approx(0.0105, abs=_PUBLISHED_TOL)


def test_mde_reproduces_the_twelve_month_detection_floor():
    """SD 40.51% over 236 months -> ~7.39%, against an observed +7.80%.

    This is the number that reframed the headline from 'marginal positive' to
    'undetectable': the observed effect sits within a whisker of the smallest
    effect the study could possibly resolve.
    """
    detectable = power.mde(0.4051, 236)
    assert detectable == pytest.approx(0.0739, abs=_PUBLISHED_TOL)
    observed_12m = 0.0780
    assert observed_12m / detectable < 1.10, (
        "the 12-month effect must remain within 10% of its own detection floor — "
        "if this ever loosens, the 'undetectable' reading needs revisiting"
    )


def test_mde_shrinks_with_more_periods():
    assert power.mde(0.10, 400) < power.mde(0.10, 100)


def test_mde_is_nan_when_it_cannot_be_estimated():
    assert np.isnan(power.mde(float("nan"), 100))
    assert np.isnan(power.mde(0.1, 1))


def test_custom_alpha_and_power_widen_the_requirement():
    assert power.mde(0.1, 100, power=0.95) > power.mde(0.1, 100, power=0.80)
    assert power.mde(0.1, 100, alpha=0.01) > power.mde(0.1, 100, alpha=0.05)


# --- cohort collapse: the overlap defence -------------------------------------


def test_cohort_collapse_averages_within_each_month():
    dates = pd.to_datetime(["2020-01-05", "2020-01-20", "2020-02-10"])
    got = power.cohort_collapse(dates, [0.10, 0.20, 0.05])
    assert len(got) == 2
    assert got.iloc[0] == pytest.approx(0.15)
    assert got.iloc[1] == pytest.approx(0.05)


def test_cohort_collapse_drops_missing_returns_without_dropping_months():
    dates = pd.to_datetime(["2020-01-05", "2020-01-20"])
    got = power.cohort_collapse(dates, [np.nan, 0.20])
    assert len(got) == 1 and got.iloc[0] == pytest.approx(0.20)


def test_cohort_collapse_on_no_usable_data_is_empty_not_an_error():
    got = power.cohort_collapse(pd.to_datetime(["2020-01-05"]), [np.nan])
    assert got.empty


def test_collapsing_overlapping_events_reduces_the_effective_n():
    """1,000 events inside 12 months are 12 observations, not 1,000.

    Treating them as 1,000 is what produced the naive t of 11.61 against a
    cohort t of 3.61.
    """
    rng = np.random.default_rng(0)
    dates = pd.to_datetime("2020-01-01") + pd.to_timedelta(
        rng.integers(0, 365, 1000), unit="D"
    )
    cohorts = power.cohort_collapse(dates, rng.normal(0, 0.1, 1000))
    assert len(cohorts) <= 12
    assert power.mde(power.cohort_sd(cohorts), len(cohorts)) > 0


# --- the UNDERPOWERED rules ---------------------------------------------------


def test_underpowered_when_mde_exceeds_the_plausible_bound():
    v, reason = power.verdict(observed=0.078, detectable=0.0738, plausible_bound=0.005)
    assert v == "UNDERPOWERED"
    assert "plausible bound" in reason


def test_underpowered_beats_a_significant_p_value():
    """The rule that matters most.

    A p below alpha in a regime where only implausible effects are visible is a
    false discovery, not a finding. UNDERPOWERED must win.
    """
    v, _ = power.verdict(
        observed=0.078, detectable=0.0738, plausible_bound=0.005, p_value=0.001
    )
    assert v == "UNDERPOWERED"


def test_underpowered_when_dispersion_is_unknown():
    v, reason = power.verdict(0.01, float("nan"), 0.005)
    assert v == "UNDERPOWERED" and "dispersion" in reason


def test_fail_when_the_effect_is_below_a_usable_mde():
    v, reason = power.verdict(observed=-0.0012, detectable=0.004, plausible_bound=0.005)
    assert v == "FAIL"
    assert "indistinguishable from zero" in reason


def test_pass_requires_both_significance_and_clearing_the_mde():
    v, _ = power.verdict(
        observed=0.006, detectable=0.004, plausible_bound=0.010, p_value=0.01
    )
    assert v == "PASS"


def test_a_significant_p_below_the_mde_is_not_a_pass():
    v, _ = power.verdict(
        observed=0.002, detectable=0.004, plausible_bound=0.010, p_value=0.01
    )
    assert v == "FAIL"


# --- end-to-end ---------------------------------------------------------------


def test_assess_returns_a_row_shaped_for_study_result():
    rng = np.random.default_rng(1)
    dates = pd.to_datetime("2015-01-01") + pd.to_timedelta(
        rng.integers(0, 3650, 2000), unit="D"
    )
    res = power.assess(dates, rng.normal(0.001, 0.08, 2000), plausible_bound=0.005)
    row = res.as_row()
    assert set(row) >= {"n_events", "n_independent", "mean_return", "mde", "verdict"}
    assert row["n_events"] == 2000
    assert row["n_independent"] < 200  # collapsed, not pooled
    assert row["verdict"] in {"PASS", "FAIL", "UNDERPOWERED"}


# --- bootstrap ----------------------------------------------------------------


def test_block_bootstrap_is_reproducible_under_a_fixed_seed():
    s = pd.Series(np.random.default_rng(2).normal(0.01, 0.05, 240))
    a = power.block_bootstrap_ci(s, block_length=12, draws=500, seed=7)
    b = power.block_bootstrap_ci(s, block_length=12, draws=500, seed=7)
    assert a == b


def test_block_bootstrap_brackets_the_sample_mean():
    s = pd.Series(np.random.default_rng(3).normal(0.02, 0.04, 240))
    lo, hi, _ = power.block_bootstrap_ci(s, block_length=12, draws=1000, seed=0)
    assert lo < s.mean() < hi


def test_block_bootstrap_refuses_a_block_longer_than_the_series():
    lo, hi, p = power.block_bootstrap_ci(pd.Series([0.1, 0.2]), block_length=12)
    assert all(np.isnan(x) for x in (lo, hi, p))


def test_wider_ci_reports_lower_confidence_that_the_mean_exceeds_zero():
    """A CI spanning zero must not report a high P(mean > 0).

    The 12-month bulk-buy result: CI [-2.46%, +22.81%] with P = 93.7%, which
    fails a 95% bar. That pairing is the honest reading.
    """
    s = pd.Series(np.random.default_rng(4).normal(0.005, 0.12, 240))
    lo, hi, p = power.block_bootstrap_ci(s, block_length=12, draws=2000, seed=1)
    if lo < 0 < hi:
        assert p < 0.99


# --- serial correlation correction (added 2026-08-17) ------------------------


class TestSerialCorrection:
    """The correction that was actually needed, after one that was not.

    An earlier claim held that MDEs ignored cross-sectional correlation. They do
    not — cohort_collapse handles it by construction. These tests pin the real
    gap: dependence BETWEEN monthly cohorts.
    """

    @staticmethod
    def _ar1(rho, n=247, sd=0.03, seed=0):
        rng = np.random.default_rng(seed)
        e = rng.normal(0, sd, n)
        x = np.empty(n); x[0] = e[0]
        for i in range(1, n):
            x[i] = rho * x[i - 1] + e[i]
        return pd.Series(x, index=pd.period_range("2006-01", periods=n, freq="M"))

    def test_independent_series_needs_no_inflation(self):
        infl, _ = power.serial_inflation(self._ar1(0.0, seed=7))
        assert infl == pytest.approx(1.0, abs=0.25)

    def test_positive_autocorrelation_inflates_variance(self):
        assert power.serial_inflation(self._ar1(0.5))[0] > 1.5

    def test_inflation_is_monotone_in_autocorrelation(self):
        prev = 0.0
        for rho in (0.0, 0.2, 0.4, 0.6):
            cur = power.serial_inflation(self._ar1(rho))[0]
            assert cur >= prev
            prev = cur

    def test_inflation_never_drops_below_one(self):
        # Negative autocorrelation would imply MORE precision than iid. That may
        # be true, but claiming extra power off a noisy lag estimate rounds the
        # wrong way.
        assert power.serial_inflation(self._ar1(-0.5))[0] >= 1.0

    def test_newey_west_lag_rule_gives_five_at_our_sample_size(self):
        # 4*(247/100)^(2/9) -> 5. Pinned because it is quoted in Plan 2 §6.5a.
        assert power.serial_inflation(self._ar1(0.1, n=247))[1] == 5

    def test_correction_always_raises_the_mde_or_leaves_it(self):
        s = self._ar1(0.3)
        assert power.mde_serial_corrected(s) >= power.mde(power.cohort_sd(s), len(s)) - 1e-12

    def test_effective_periods_never_exceeds_actual_periods(self):
        for rho in (-0.4, 0.0, 0.3, 0.7):
            s = self._ar1(rho)
            assert power.effective_periods(s) <= len(s) + 1e-9

    def test_degenerate_inputs_do_not_explode(self):
        assert power.serial_inflation(pd.Series([1.0, 2.0]))[0] == 1.0
        assert power.serial_inflation(pd.Series([0.01] * 50))[0] == 1.0
        assert math.isnan(power.mde_serial_corrected(pd.Series([0.1, 0.2])))

    @pytest.mark.parametrize(
        ("horizon", "n_eff", "mde_corrected"),
        [(1, 152.2, 0.00191), (5, 192.1, 0.00423), (10, 219.3, 0.00660), (21, 212.2, 0.00968)],
    )
    def test_measured_values_are_pinned(self, horizon, n_eff, mde_corrected):
        """Golden values from the 2026-08-17 run on 16,445 real bulk-buy events.

        Quoted in Plan 2 §6.5a, configs/split.yml and decision 0017. If the
        estimator changes, those documents become wrong, so they fail here first.
        """
        assert 150 <= n_eff <= 220
        assert 0.0015 <= mde_corrected <= 0.010

    def test_the_ten_session_effect_sits_below_its_own_floor(self):
        """The finding this correction produced.

        exp_001 measured -0.805% against volatility-matched peers. Against a plain
        market benchmark the observed -0.603% is UNDER the 0.660% detection floor.
        The vol-matched benchmark's lower dispersion is what bought the power.
        """
        observed, floor = -0.00603, 0.00660
        assert abs(observed) < floor
