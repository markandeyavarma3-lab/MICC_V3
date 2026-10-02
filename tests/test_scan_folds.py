"""Track S folds (Plan 3 step 6S.1). The gate: the EFFECTIVE fold count is
reported beside the nominal one, and no training session can see a test block."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from src.scan import folds

pytestmark = pytest.mark.unit


def _sessions(start=date(2005, 1, 1), end=date(2026, 9, 30)):
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


S = _sessions()


def test_the_configured_designs_have_the_measured_counts():
    """scan.yml: 16 sequential folds ~ 8 independent; CPCV 120 paths over 16 groups."""
    fs = folds.from_config(S)
    assert fs["sequential"].nominal == 16 and 8 <= fs["sequential"].effective <= 9
    assert fs["cpcv"].nominal == 120 and fs["cpcv"].effective == 16


def test_no_sequential_training_session_reaches_into_its_test_window():
    fs = folds.from_config(S)["sequential"]
    for f in fs.folds:
        assert f.train.max() < f.test.min() - 21, f.name       # the 21-session embargo
        assert f.train.min() == fs.folds[0].train.min()          # anchored: training always starts in 2005


def test_cpcv_purges_before_and_embargoes_after_every_test_block():
    fs = folds.cpcv(1600, n_groups=16, k_test_groups=2, purge_sessions=21, embargo_sessions=21)
    for f in fs.folds:
        assert not np.intersect1d(f.train, f.test).size
        blocks = np.split(f.test, np.where(np.diff(f.test) != 1)[0] + 1)
        for b in blocks:
            near = (f.train >= b[0] - 21) & (f.train <= b[-1] + 21)
            assert not near.any(), f"{f.name}: training within the purge/embargo of a test block"


def test_each_cpcv_group_is_tested_in_n_minus_one_paths():
    fs = folds.cpcv(1600, n_groups=16, k_test_groups=2, purge_sessions=0, embargo_sessions=0)
    counts = np.bincount(np.concatenate([f.test for f in fs.folds]) // 100)
    assert set(counts.tolist()) == {15 * 100}


def test_an_explore_run_never_tests_on_confirmation_data():
    """split.yml: explore ends 2015-12-31. Development runs cut there."""
    end = date(2015, 12, 31)
    fs = folds.from_config(S, end=end)
    last = max(S[i] for i in np.concatenate([f.test for f in fs["sequential"].folds]))
    assert last <= end
    assert max(S[i] for i in np.concatenate([f.test for f in fs["cpcv"].folds])) <= end


def test_a_single_fold_is_refused():
    with pytest.raises(ValueError, match="single fold"):
        folds.sequential(S, date(2005, 1, 1), date(2025, 1, 1), 2, 1, 21)


def test_a_test_window_mostly_past_the_data_is_dropped_not_kept_short():
    fs = folds.from_config(S)["sequential"]
    assert fs.folds[-1].name == "seq_2025"      # 2026's window would be 9 months of 24
