"""Null calibration — Plan 3 step 6.9, Plan 2 §6.3.

The only test in this project that interrogates the machinery rather than the
market. Every verdict reached so far is a negative one resting on this pipeline;
this points the identical pipeline at data whose answer is "nothing" by
construction and checks that it agrees.
"""

from __future__ import annotations

import random

import pytest

from src.research import multiplicity, nullcal

pytestmark = pytest.mark.needs_data


# --- Romano-Wolf itself (step 6.8), pure arithmetic -------------------------


@pytest.mark.unit
def test_romano_wolf_finds_a_planted_signal():
    rng = random.Random(0)
    obs = [5.0, 0.2, -0.1, 0.3, 0.05]
    boot = [[rng.gauss(0, 1) for _ in range(5)] for _ in range(2000)]
    adj = multiplicity.romano_wolf(obs, boot)
    assert adj[0] < 0.01
    assert all(p > 0.5 for p in adj[1:])


@pytest.mark.unit
def test_romano_wolf_p_values_are_monotone_in_the_stepdown_order():
    """A stepdown can otherwise hand a weaker candidate a smaller adjusted p,
    which is incoherent as a ranking."""
    rng = random.Random(1)
    obs = [3.0, 2.5, 2.0, 1.0]
    boot = [[rng.gauss(0, 1) for _ in range(4)] for _ in range(1000)]
    adj = multiplicity.romano_wolf(obs, boot)
    order = sorted(range(4), key=lambda i: abs(obs[i]), reverse=True)
    seq = [adj[i] for i in order]
    assert seq == sorted(seq)


@pytest.mark.unit
def test_romano_wolf_never_reports_exactly_zero():
    """Davison-Hinkley: with B draws the smallest achievable p is 1/(B+1). A
    reported 0 would be an artefact of a finite bootstrap."""
    boot = [[0.0] * 2 for _ in range(99)]
    adj = multiplicity.romano_wolf([50.0, 40.0], boot)
    assert min(adj) == pytest.approx(1 / 100)


@pytest.mark.unit
def test_romano_wolf_refuses_a_ragged_bootstrap():
    with pytest.raises(multiplicity.MultiplicityError):
        multiplicity.romano_wolf([1.0, 2.0], [[0.1, 0.2], [0.3]])


@pytest.mark.unit
def test_it_is_a_stepdown_and_not_westfall_young_single_step():
    """WATCHED FAILING 2026-09-10.

    The first version of this file tested Romano-Wolf with one planted signal
    against flat noise, where a stepdown and a single-step give identical
    answers — so replacing `order[step:]` with `order`, which is precisely the
    difference between the two procedures, left every test green.

    The distinction only shows when the LARGEST candidate carries the widest
    bootstrap column: dropping it shrinks the max distribution the next
    candidate is judged against. That is where the power over Bonferroni and
    over single-step comes from, and it is the reason Plan 2 §6.2 specifies
    Romano-Wolf rather than Westfall-Young.
    """
    rng = random.Random(7)
    boot = [[rng.gauss(0, 3.0), rng.gauss(0, 1.0), rng.gauss(0, 1.0)]
            for _ in range(20_000)]
    obs = [4.0, 2.6, 0.1]
    stepdown = multiplicity.romano_wolf(obs, boot)

    def single_step(o, b):
        return [(sum(1 for d in b if max(abs(v) for v in d) >= abs(x)) + 1)
                / (len(b) + 1) for x in o]

    naive = single_step(obs, boot)
    assert stepdown[1] < naive[1] - 0.05, (
        f"candidate 1 adjusted to {stepdown[1]:.4f} by stepdown and "
        f"{naive[1]:.4f} single-step; if these match, the family is no longer "
        f"shrinking and this is not Romano-Wolf"
    )


@pytest.mark.unit
def test_the_bootstrap_must_be_centred_or_the_null_is_never_imposed():
    """WATCHED FAILING 2026-09-10, and the direction was a surprise.

    Deleting the centring in `_run_procedure` left the real-data tests green,
    because no participant in this dataset has a mean far from zero, so
    subtracting it is nearly a no-op. On data where it is NOT a no-op the effect
    is large and CONSERVATIVE: an uncentred bootstrap carries the observed
    effect into the null it is supposed to represent, so a real signal is
    compared against a distribution that already contains it.

    Measured here: adjusted p 0.0002 centred, 0.6251 uncentred, on an identical
    statistic of t = 53. Not a rounding difference — the difference between
    finding something and hiding it.

    THROUGH `_run_procedure`, NOT AROUND IT. The first version of this test
    built its own panel and did its own centring, so it verified the concept
    while leaving the actual call site untested — deleting the centring inside
    `_run_procedure` kept it green. A test that reimplements the thing it is
    checking is checking itself.
    """
    months = [f"2020-{m:02d}" for m in range(1, 13)]
    cohorts = {
        "BIG": {m: [5.0 + 0.1 * i] for i, m in enumerate(months)},
        "FLAT": {m: [0.1 * ((i % 3) - 1)] for i, m in enumerate(months)},
    }
    observed, adjusted = nullcal._run_procedure(
        cohorts, months, ["BIG", "FLAT"], 5_000, random.Random(3))

    assert observed[0] > 20, "the synthetic signal is not large; the case is wrong"
    assert adjusted[0] < 0.01, (
        f"BIG adjusted to {adjusted[0]:.4f}; an uncentred bootstrap carries the "
        f"observed effect into the null it is meant to represent and hides it"
    )


# --- the permutation itself -------------------------------------------------


@pytest.mark.unit
def test_permutation_preserves_every_participant_event_count():
    """WHY WITHIN-DATE. If a permutation changed event counts, the eligibility
    filter would select a different population in each arm and the two sides of
    the comparison would not be measuring the same thing."""
    rows = [("A", "2020-01-01", "2020-01", 0.1), ("B", "2020-01-01", "2020-01", 0.2),
            ("C", "2020-01-01", "2020-01", 0.3), ("A", "2020-02-03", "2020-02", 0.4),
            ("B", "2020-02-03", "2020-02", 0.5)]
    before = {}
    for r in rows:
        before[r[0]] = before.get(r[0], 0) + 1
    for seed in range(25):
        out = nullcal._permute_within_date(rows, random.Random(seed))
        after = {}
        for r in out:
            after[r[0]] = after.get(r[0], 0) + 1
        assert after == before
        # and the returns stay attached to their own dates
        assert sorted((r[1], r[3]) for r in out) == sorted((r[1], r[3]) for r in rows)


# --- the calibration on real data -------------------------------------------


@pytest.fixture(scope="module")
def cal():
    return nullcal.run(252, permutations=200)


def test_the_procedure_does_not_manufacture_findings_from_noise(cal):
    """THE POINT OF THE WHOLE FILE.

    Romano-Wolf claims to control the family-wise error rate at 5%. Under labels
    that carry no information by construction, it must not produce a "supported"
    participant much more often than that. A rate far above 5% would mean every
    corrected p-value this project has published is too small.

    The bound is one-sided on purpose: a rate BELOW 5% means the correction is
    conservative, which is a fine place for the error to sit.
    """
    assert cal.perm_rate <= 0.08, (
        f"the correction produced a supported participant in {cal.perm_rate:.1%} "
        f"of pure-noise permutations against a nominal 5%"
    )


def test_no_participant_skill_survives_the_correction(cal):
    """Plan 2 §6.3: 'If the real data yields a similar number of supported
    participants as the shuffled data, there is no participant skill in this
    dataset — only variance.' Real is 0; shuffled is 0 in ~98% of runs."""
    assert cal.real_supported == 0
    assert cal.real_min_p > 0.05


def test_the_eligible_population_is_nothing_like_the_plan_expected(cal):
    """Plan 2 §6.3 step 1 expects >=30 matured events to reduce 27,417 names 'to
    a few hundred'. It reduces them to seven at twelve months. The estimate
    predates the participation cap (0038), EQ-only (0045), the suspension
    exclusion (0055) and CHAR_MATCHED's 74% coverage."""
    assert cal.n_eligible < 20


def test_almost_no_eligible_participant_has_enough_months_to_be_tested(cal):
    """THE FINDING THIS STEP ACTUALLY PRODUCED.

    §6.1 requires the monthly-cohort collapse so that overlapping events are not
    counted as independent observations. §6.3 sets eligibility on EVENTS. Those
    two are in conflict, because 30 events concentrated in one month is ONE
    observation: five of the ten eligible participants at the short horizons are
    present in exactly one month, and the median is two.

    So the leaderboard is not a leaderboard of seven. It is a leaderboard of one
    testable candidate and six whose statistic is zero by construction. This is
    not "no skill was found" — it is "the study specified in §6.3 cannot be run
    on this data", which is a different and more useful statement.
    """
    assert cal.testable <= 2, (
        f"{cal.testable} participants now clear {nullcal.MIN_MONTHS} months — if "
        f"this has genuinely risen, §6.3 may finally be runnable and the verdict "
        f"in decision 0056 needs revisiting"
    )
    assert min(cal.months_present) == 1
