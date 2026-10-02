"""The chunked, resumable runner and its benchmark gate (Plan 3 step 6S.6)."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from src.scan import atlas as A
from src.scan import folds, procedure
from src.scan.panel import Panel

pytestmark = pytest.mark.unit
ONLY = ["mom_63_skip0", "rev_5", "vol_21", "amihud_21", "dnet_21"]


def _panel(T=500, N=120, seed=0):
    rng = np.random.default_rng(seed)
    d, dates = date(2010, 1, 4), []
    while len(dates) < T:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    close = (100 * np.exp(np.cumsum(rng.normal(0, 0.02, (T, N)), axis=0))).astype(np.float32)
    vol = rng.integers(1_000, 100_000, (T, N)).astype(np.float32)
    deals = np.where(rng.random((T, N)) < 0.03, 1e7, 0).astype(np.float32)
    return Panel(dates, np.arange(N), close, close * 1.01, close * 0.99, close, vol,
                 np.ones((T, N), bool), deals, np.zeros((T, N), np.float32))


def test_block_means_are_the_session_weighted_mean_over_whole_blocks():
    rng = np.random.default_rng(1)
    daily = rng.normal(size=(105, 3))
    daily[5:9, 1] = np.nan
    sums, counts = zip(*(A.to_blocks(daily[:, k]) for k in range(3)), strict=True)
    b = A.BlockIC(np.stack(sums, axis=1), np.stack(counts, axis=1))
    idx = np.array([0, 2, 3])                          # blocks 0, 2, 3 = sessions 0-20, 42-83
    sess = np.r_[0:21, 42:84]
    assert np.allclose(b.mean_over(idx), np.nanmean(daily[sess], axis=0))


def test_block_folds_keep_only_whole_blocks_and_never_share_one():
    fs = folds.cpcv(2000, 10, 2, 21, 21)
    bf = A.block_folds(fs)
    for f in bf.folds:
        assert not np.intersect1d(f.train, f.test).size
    assert all(len(f.test) for f in bf.folds)


def test_the_procedure_gives_the_same_answer_on_blocks_as_on_days():
    rng = np.random.default_rng(2)
    daily = rng.normal(0, 0.1, size=(21 * 120, 40))
    daily[:, :3] += 0.04
    blocks = np.arange(len(daily)) // 21
    sums = np.stack([np.bincount(blocks, weights=daily[:, k]) for k in range(40)], axis=1)
    counts = np.stack([np.bincount(blocks) for _ in range(40)], axis=1)
    bic = A.BlockIC(sums, counts)
    bfs = folds.cpcv(120, 10, 2, 1, 1)                 # in blocks
    dfs = folds.FoldSet("d", [folds.Fold(f.name, np.concatenate([np.arange(b * 21, b * 21 + 21) for b in f.train]),
                                         np.concatenate([np.arange(b * 21, b * 21 + 21) for b in f.test]))
                              for f in bfs.folds], bfs.nominal, bfs.effective, "")
    a = procedure.select_and_test(bic, bfs, 3)
    b = procedure.select_and_test(daily, dfs, 3)
    assert a.hit_rate == b.hit_rate and a.mean_test_ic == pytest.approx(b.mean_test_ic)


def test_a_run_is_resumable_and_writes_only_what_is_missing(tmp_path):
    at = A.Atlas(_panel(), tmp_path, horizon=5, depth=2, shard_size=7, only=ONLY)
    assert at.total == 5 + 10 * 2
    assert at.run() == 4                               # ceil(25 / 7)
    (tmp_path / "shard_00002.npz").unlink()
    assert at.run() == 1
    bic, keys = at.load()
    assert bic.shape[1] == 25 and len(set(keys)) == 25


def test_a_resume_against_a_different_grid_is_refused(tmp_path):
    A.Atlas(_panel(), tmp_path, horizon=5, depth=1, shard_size=10, only=ONLY).run()
    other = A.Atlas(_panel(), tmp_path, horizon=21, depth=1, shard_size=10, only=ONLY)
    with pytest.raises(RuntimeError, match="different grid"):
        other.run()


def test_an_incomplete_grid_cannot_be_loaded(tmp_path):
    at = A.Atlas(_panel(), tmp_path, horizon=5, depth=2, shard_size=7, only=ONLY)
    at.run(limit_shards=2)
    with pytest.raises(RuntimeError, match="incomplete"):
        at.load()


def test_the_benchmark_projects_the_full_run(tmp_path):
    at = A.Atlas(_panel(), tmp_path, horizon=5, depth=2, only=ONLY)
    b = at.benchmark(fraction=0.5)
    assert b["candidates"] == 25 and b["sampled"] >= 12
    assert b["projected_days"] > 0 and b["within_budget"] is True
