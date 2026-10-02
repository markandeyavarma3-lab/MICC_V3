"""exp_005's registered analysis (decision 0085): the verdict ladder, the
guard, and the whole pipeline end to end on a synthetic grid."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from src.scan import atlas as A
from src.scan import confirm as C
from src.scan import folds
from src.scan.panel import Panel

pytestmark = pytest.mark.unit
N3 = [1, 10, 100]


def test_no_n_passing_is_no_search_skill():
    assert C.decide(N3, [0.2, 0.3, 0.4], [0.01] * 3, {n: [0.01] for n in N3}) == "NO_SEARCH_SKILL"


def test_passing_only_on_the_plain_ic_is_a_rediscovery():
    assert C.decide(N3, [0.01, 0.2, 0.3], [0.2, 0.01, 0.3],
                    {n: [0.01] for n in N3}) == "REDISCOVERS_KNOWN_FACTORS"


def test_passing_both_but_losing_net_is_significant_but_unprofitable():
    assert C.decide(N3, [0.01] * 3, [0.01] * 3, {n: [-0.002, 0.001] for n in N3}) == "SIGNIFICANT_BUT_UNPROFITABLE"


def test_all_three_is_a_new_edge():
    assert C.decide(N3, [0.01] * 3, [0.01] * 3, {1: [0.01], 10: [-0.01], 100: [-0.01]}) == "SEARCH_FINDS_NEW_EDGE"


def test_bh_matches_the_step_up_with_the_running_minimum():
    assert np.allclose(C.bh([0.01, 0.04, 0.03]), [0.03, 0.04, 0.04])


def test_the_confirm_run_refuses_without_a_registration(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "governance_db", lambda env=None: tmp_path / "none.sqlite")
    with pytest.raises(RuntimeError, match="not REGISTERED"):
        C.registered_hash()


def _panel(T=1100, N=130, seed=0):
    rng = np.random.default_rng(seed)
    d, dates = date(2010, 1, 4), []
    while len(dates) < T:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    close = (100 * np.exp(np.cumsum(rng.normal(0, 0.02, (T, N)), axis=0))).astype(np.float32)
    vol = rng.integers(10_000, 1_000_000, (T, N)).astype(np.float32)
    z = np.zeros((T, N), np.float32)
    return Panel(dates, np.arange(N), close, close * 1.01, close * 0.99, close, vol,
                 np.ones((T, N), bool), z, z)


def test_the_whole_registered_analysis_runs_end_to_end(tmp_path):
    p = _panel()
    at = A.Atlas(p, tmp_path, horizon=21, depth=2, min_names=100,
                 only=["hi_252", "downvol_126", "mom_63_skip0", "rev_5", "vol_21"])
    at.run()
    bic, keys = at.load()
    fs = folds.sequential(p.dates, date(2010, 1, 1), date(2012, 1, 1), 1, 1, 21)
    o = C.evaluate(at, bic, keys, fs, [1, 5], reps=20)
    assert o.verdict in {"NO_SEARCH_SKILL", "REDISCOVERS_KNOWN_FACTORS",
                         "SIGNIFICANT_BUT_UNPROFITABLE", "SEARCH_FINDS_NEW_EDGE"}
    assert len(o.primary) == len(o.partial) == 2 and set(o.net_per_fold) == {1, 5}
    assert "Verdict" in C.render(o, "T", "n", fs)
