"""The procedure test (Plan 4 §4, step 6S.3) on candidates whose truth is known:
pure noise must look like noise, and a persistent edge must be found."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from src.scan import folds, procedure

pytestmark = pytest.mark.unit


def _sessions(n):
    d, out = date(2005, 1, 3), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


S = _sessions(2600)            # ~2005-2014
SEQ = folds.sequential(S, date(2005, 1, 1), date(2008, 1, 1), 1, 1, 21)
CP = folds.cpcv(len(S), 10, 2, 21, 21)


def _ic(k=300, edge=0.0, n_edge=0, seed=0):
    rng = np.random.default_rng(seed)
    ic = rng.normal(0, 0.12, size=(len(S), k))
    if n_edge:
        signs = rng.choice([-1.0, 1.0], size=n_edge)
        ic[:, :n_edge] += edge * signs           # persistent, in either direction
    return ic


def test_noise_candidates_look_like_noise():
    rs, p = procedure.run(_ic(), SEQ, CP, [1, 10], reps=60)
    for r in rs:
        assert 0.1 <= r.hit_rate <= 0.9
        assert r.degradation > 0, "selecting the best of noise must look better in training"
        assert abs(r.rank_decay) < 0.1
        assert r.p_vs_null > 0.05
    assert 0.3 <= p <= 0.8


def test_a_persistent_edge_is_found_whichever_its_sign():
    rs, p = procedure.run(_ic(edge=0.03, n_edge=20), SEQ, CP, [1, 10], reps=60)
    for r in rs:
        assert r.hit_rate == 1.0 and r.mean_test_ic > 0.02
        assert r.p_vs_null < 0.05
    assert p < 0.2


def test_the_test_ic_is_read_in_the_training_sign():
    """A candidate that is reliably NEGATIVE is a good short; selecting on |IC|
    and reading the test in the training sign must count it as a hit."""
    ic = _ic(k=50, seed=3)
    ic[:, 0] -= 0.05
    r = procedure.select_and_test(ic, SEQ, 1)
    assert r.hit_rate == 1.0 and r.mean_test_ic > 0


def test_the_null_removes_lasting_edge():
    ic = _ic(edge=0.03, n_edge=20)
    null = procedure.null_hit_rates(ic, SEQ, 10, reps=60)
    assert 0.3 < null.mean() < 0.7, "the null still carries the edge it was meant to remove"


def test_the_null_is_centred_on_noise_not_biased_against_it():
    """The first null (demean, then rotate) sat near 0.1 on pure noise and made
    noise look significant at p = 0.016."""
    null = procedure.null_hit_rates(_ic(), SEQ, 10, reps=80)
    assert 0.35 < null.mean() < 0.65


def test_partial_selection_picks_what_a_full_sort_picks():
    rng = np.random.default_rng(9)
    tr = rng.normal(size=5000)
    cand = np.arange(5000)
    full = cand[np.argsort(-np.abs(tr))][:100]
    assert (procedure._top(tr, cand, 100) == full).all()


def test_the_shared_null_pass_equals_the_one_n_at_a_time_reference():
    """The reference is the original algorithm, written out: same seed, same
    block signs, select_and_test per N."""
    ic = _ic(k=120, seed=4)
    multi = procedure.null_hit_rates_multi(ic, SEQ, [1, 10], reps=15)
    for n in (1, 10):
        rng = np.random.default_rng(20261002)
        blocks = np.arange(ic.shape[0]) // procedure.NULL_BLOCK_SESSIONS
        ref = []
        for _ in range(15):
            signs = rng.choice([-1.0, 1.0], size=blocks[-1] + 1)[blocks]
            ref.append(procedure.select_and_test(ic * signs[:, None], SEQ, n, decay=False).hit_rate)
        assert np.allclose(multi[n], ref)
