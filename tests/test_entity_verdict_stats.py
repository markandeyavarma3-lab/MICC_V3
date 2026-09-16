"""exp_002 significance machinery — the part that does not need the warehouse.

These tests exist because the first implementation of this study substituted a
normal approximation for the registered moving-block bootstrap, and that
substitution — not the data — produced its two reported FDR passes. The
arithmetic below is checkable without a single price row, so it is checked here
rather than only inside a run nobody can reproduce without the database.
"""

from __future__ import annotations

import math

import pytest

from src.research import entity_verdict as E


def _rows(ent, dates, excess, era, side="BUY", gv=1e7, adv=1e9, qty=1000):
    return [(ent, d, side, gv, adv, qty, "NSE", x, 0.0, x, era)
            for d, x in zip(dates, excess)]


def _months(n, start_year=2006):
    return [f"{start_year + i // 12:04d}-{i % 12 + 1:02d}-15" for i in range(n)]


class TestTheRegisteredBootstrapReplacesTheNormalApproximation:
    """The registration froze `permutation_policy` as a moving-block bootstrap.
    The code ran `math.erfc(|t|/sqrt(2))` instead."""

    def test_two_deals_are_not_testable_at_all(self):
        """THE BUG THAT MATTERED. Two observations cannot fill a three-month
        block, so the registered procedure declines. The normal approximation
        it replaced returned p = 0.0000 on the same two points."""
        assert E._p_form(["2006-01-15", "2006-07-15"], [-0.27, -0.28]) is None

    def test_the_normal_approximation_would_have_passed_those_same_two_deals(self):
        """Not a test of our code — a test of the claim that motivated the fix,
        so the reasoning is checkable rather than asserted."""
        vals = [-0.27, -0.28]
        mean = sum(vals) / len(vals)
        var = sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)
        t = mean / math.sqrt(var / len(vals))
        p_normal = math.erfc(abs(t) / math.sqrt(2))
        assert p_normal < 0.05 / 24, (
            "the substituted test clears the BH rank-1 threshold on two deals"
        )

    def test_computability_is_decided_by_month_span_not_deal_count(self):
        """The correction's own claim, pinned. The bootstrap resamples WHOLE
        MONTHS, so five deals inside three months is as uncomputable as two
        deals — and five deals across five months is computable and may well be
        significant. An earlier draft of the memo said both published passers
        were uncomputable; only the n=2 one is known to be."""
        five_in_three = ["2006-01-15", "2006-01-20", "2006-02-15",
                         "2006-02-20", "2006-03-15"]
        assert E._p_form(five_in_three, [-0.12] * 5) is None

        five_in_five = [f"2006-0{i}-15" for i in range(1, 6)]
        p = E._p_form(five_in_five, [-0.12] * 5)
        assert p is not None, "five deals across five months IS computable"
        assert p < 0.05 / 24, (
            "and can still clear the BH rank-1 threshold — so the fix does not "
            "automatically erase the five-deal pass"
        )

    def test_a_long_series_is_testable(self):
        p = E._p_form(_months(36), [0.02] * 36)
        assert p is not None and 0.0 < p <= 1.0

    def test_p_is_floored_at_the_bootstrap_resolution_never_zero(self):
        p = E._p_form(_months(60), [0.05] * 60)
        assert p >= 1.0 / E.BOOTSTRAP_DRAWS, "p = 0 is an artefact of finite draws"

    def test_the_seed_makes_it_reproducible(self):
        d, v = _months(36), [0.01 * (i % 7) for i in range(36)]
        assert E._p_form(d, v) == E._p_form(d, v)

    def test_noise_is_not_significant(self):
        vals = [0.01 if i % 2 else -0.01 for i in range(48)]
        assert E._p_form(_months(48), vals) > 0.05


class TestBenjaminiHochbergIsAStepUp:
    def test_adjusted_values_are_monotone_in_p(self):
        """q_(i) = min over j >= i of p_(j)*m/j. Without the running minimum a
        larger p can be reported as more significant than a smaller one."""
        q = E._bh([("a", 0.001), ("b", 0.30), ("c", 0.31)], m=24)
        assert q["a"] <= q["b"] <= q["c"]

    def test_the_running_minimum_actually_binds(self):
        """Raw p*m/rank is non-monotone here: rank 2 gives 0.08*24/2 = 0.96 but
        rank 3 gives 0.09*24/3 = 0.72. The step-up pulls rank 2 down to 0.72;
        without it, p = 0.08 would be reported as LESS significant than the
        larger p = 0.09."""
        q = E._bh([("x", 0.001), ("y", 0.08), ("z", 0.09)], m=24)
        assert q["y"] == pytest.approx(0.72)
        assert q["z"] == pytest.approx(0.72)
        assert q["y"] < 0.08 * 24 / 2

    def test_the_family_is_the_declared_24_not_the_computable_count(self):
        one = E._bh([("a", 0.001)], m=24)
        assert one["a"] == 0.001 * 24


class TestRankIC:
    def test_below_the_floor_it_refuses(self):
        assert E._rank_ic([1, 2], [1, 2]) is None

    def test_perfect_agreement_is_one(self):
        assert E._rank_ic([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == pytest.approx(1.0)

    def test_perfect_disagreement_is_minus_one(self):
        assert E._rank_ic([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]) == pytest.approx(-1.0)

    def test_a_constant_side_has_no_correlation_rather_than_a_crash(self):
        assert E._rank_ic([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]) is None


class TestScoringEndToEnd:
    def test_a_two_deal_entity_cannot_pass_fdr_and_is_counted_untestable(self):
        """The whole point. SUNDARAM had two formation deals and was published
        as a BH-FDR 5% pass."""
        rows = (_rows("SPARSE", ["2006-01-15", "2006-07-15"], [-0.27, -0.28], "form")
                + _rows("SPARSE", _months(12, 2016), [0.01] * 12, "eval"))
        v = E._score(rows)
        s = next(x for x in v.entities if x.entity == "SPARSE")
        assert s.p_form is None and s.q_form is None
        assert v.passed_fdr == 0
        assert v.n_untestable == 1

    def test_an_entity_with_no_formation_deals_is_counted_separately(self):
        v = E._score(_rows("NEW", _months(12, 2016), [0.01] * 12, "eval"))
        assert v.n_zero_formation == 1
        assert v.n_untestable == 0, "no formation deal is not the same as untestable"

    def test_alive_is_the_registered_conjunction(self):
        rows = (_rows("A", _months(24), [0.02] * 24, "form")
                + _rows("A", _months(12, 2016), [0.02] * 12, "eval"))
        v = E._score(rows)
        in_top = [s for s in v.entities if s.tier == "TOP"
                  and s.q_form is not None and s.q_form < E.FDR_ALPHA]
        assert v.alive == (bool(in_top) and v.tier_eval.get("TOP", -1) > 0)
