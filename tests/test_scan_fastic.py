"""The moment-based IC (decision 0084) against direct computation. The fast
path is only allowed because it is EXACTLY the declared statistic."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import rankdata

from src.scan import fastic
from src.scan import ic as icmod

pytestmark = pytest.mark.unit
rng = np.random.default_rng(11)
K, T, U = 4, 30, 150


def _data():
    base = rng.normal(size=(K, T, U)).astype(np.float32)
    fwd = (0.3 * base[0] - 0.2 * base[2] + rng.normal(size=(T, U))).astype(np.float32)
    base[1, :, :10] = np.round(base[1, :, :10])          # ties
    base[3, 5, 7] = np.nan                                 # one missing signal value
    fwd[8, :70] = np.nan                                   # a thin date: 80 names
    return base, fwd


def _common(base, fwd, t):
    return np.isfinite(fwd[t]) & np.isfinite(base[:, t, :]).all(axis=0)


def test_depth_one_is_exactly_spearman_on_the_common_cross_section():
    base, fwd = _data()
    mo = fastic.moments(base, fwd, min_names=100)
    fast = fastic.batch_ic(mo, np.array([[0], [1], [2]]), np.ones((3, 1)))
    for k in range(3):
        x = base[k].astype(float).copy()
        y = fwd.astype(float).copy()
        for t in range(T):
            m = _common(base, fwd, t)
            x[t, ~m] = np.nan
            y[t, ~m] = np.nan
        direct = icmod.rank_ic(x, y, min_names=100)
        assert np.allclose(fast[:, k], direct, equal_nan=True, atol=1e-5), k


def test_a_combination_is_the_composite_against_the_return_rank():
    base, fwd = _data()
    mo = fastic.moments(base, fwd, min_names=100)
    idx, sg = np.array([[0, 2, 3]]), np.array([[1.0, -1.0, 1.0]])
    fast = fastic.batch_ic(mo, idx, sg)[:, 0]
    for t in range(T):
        m = _common(base, fwd, t)
        if m.sum() < 100:
            assert np.isnan(fast[t])
            continue
        comp = sum(s * rankdata(base[i, t, m]) / m.sum() for i, s in zip(idx[0], sg[0], strict=True)) / 3
        direct = np.corrcoef(comp, rankdata(fwd[t, m]) / m.sum())[0, 1]
        assert fast[t] == pytest.approx(direct, abs=1e-5), t


def test_one_missing_signal_value_removes_the_name_for_every_candidate():
    base, fwd = _data()
    mo = fastic.moments(base, fwd, min_names=100)
    assert mo.n[5] == _common(base, fwd, 5).sum() == U - 1
    assert np.isnan(mo.cyy[8]), "80 names is below the floor; no IC that date"


def test_block_sums_match_the_reference_blocking():
    from src.scan import atlas
    ic = rng.normal(size=(50, 3))
    ic[[3, 30], 1] = np.nan
    s, c = fastic.block_sums(ic, 21)
    for k in range(3):
        rs, rc = atlas.to_blocks(ic[:, k], 21)
        assert np.allclose(s[:, k], rs) and (c[:, k] == rc).all()


def test_the_partial_ic_is_the_correlation_of_residualised_ranks():
    base, fwd = _data()
    mo = fastic.moments(base, fwd, min_names=100)
    idx, sg, F = np.array([[1, 3]]), np.array([[1.0, -1.0]]), np.array([0, 2])
    fast = fastic.batch_partial_ic(mo, idx, sg, F)[:, 0]
    for t in range(T):
        m = _common(base, fwd, t)
        if m.sum() < 100:
            continue
        n = m.sum()
        r = [rankdata(base[i, t, m]) / n for i in range(K)]
        comp = (r[1] - r[3]) / 2
        y = rankdata(fwd[t, m]) / n
        X = np.column_stack([np.ones(n), r[0], r[2]])
        rc = comp - X @ np.linalg.lstsq(X, comp, rcond=None)[0]
        ry = y - X @ np.linalg.lstsq(X, y, rcond=None)[0]
        direct = np.corrcoef(rc, ry)[0, 1]
        assert fast[t] == pytest.approx(direct, abs=1e-4), t


def test_a_candidate_that_is_only_a_factor_has_no_partial_ic():
    base, fwd = _data()
    mo = fastic.moments(base, fwd, min_names=100)
    p = fastic.batch_partial_ic(mo, np.array([[0]]), np.array([[1.0]]), np.array([0, 2]))
    assert np.nanmax(np.abs(p)) < 1e-3
