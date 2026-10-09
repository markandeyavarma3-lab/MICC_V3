"""exp_001 rebuilt (src/research/avoidance.py): the mechanics the frozen spec
pins — the 10-session window after the next open, the cost on incremental
turnover only, and a deterministic bootstrap."""

from __future__ import annotations

import numpy as np
import pytest

from src.research import avoidance as A

pytestmark = pytest.mark.unit


def test_an_event_on_day_d_excludes_holding_days_d_plus_1_to_d_plus_10():
    ev = np.zeros((30, 1), bool)
    ev[5, 0] = True
    ex = A.excluded(ev)
    assert not ex[5, 0] and ex[6, 0] and ex[15, 0] and not ex[16, 0]
    assert ex[:, 0].sum() == 10


def test_a_second_event_inside_the_window_extends_it():
    ev = np.zeros((40, 1), bool)
    ev[[5, 12], 0] = True
    ex = A.excluded(ev)[:, 0]
    assert ex[6:23].all() and not ex[23]


def test_open_to_open_returns_line_up_with_the_holding_day():
    o = np.array([[100.0], [110.0], [99.0]])
    r = A.open_to_open(o)
    assert r[0, 0] == pytest.approx(0.10) and r[1, 0] == pytest.approx(-0.10) and np.isnan(r[2, 0])


def test_no_events_means_no_difference_and_no_cost():
    rng = np.random.default_rng(1)
    ret = rng.normal(0, 0.01, (50, 20))
    uni = np.ones((50, 20), bool)
    d = A.paired_net(ret, uni, np.zeros((50, 20), bool), np.ones(20, bool))
    assert np.allclose(d, 0)


def test_the_filter_pays_cost_only_when_a_name_enters_or_leaves_exclusion():
    ret = np.zeros((30, 10))
    uni = np.ones((30, 10), bool)
    ev = np.zeros((30, 10), bool)
    ev[5, 0] = True
    d = A.paired_net(ret, uni, A.excluded(ev), np.ones(10, bool))
    charged = np.flatnonzero(d < 0)
    assert list(charged) == [6, 16]                        # leaves on day 6, back on day 16
    assert d[6] == pytest.approx(-A.ROUND_TRIP / 9)        # 1/N of the filtered book, one change


def test_the_excluded_names_return_is_what_the_filter_avoids():
    ret = np.zeros((30, 4))
    ret[8, 0] = -0.10                                       # the bought name falls inside its window
    uni = np.ones((30, 4), bool)
    ev = np.zeros((30, 4), bool)
    ev[5, 0] = True
    d = A.paired_net(ret, uni, A.excluded(ev), np.ones(4, bool), round_trip=0.0)
    assert d[8] == pytest.approx(0.0 - (-0.10 / 4))        # filtered book 0, unfiltered -2.5%


def test_the_bootstrap_is_deterministic_and_annualised():
    x = np.random.default_rng(3).normal(0.0001, 0.001, 2000)
    a = A.block_bootstrap_ci(x, draws=500)
    assert a == A.block_bootstrap_ci(x, draws=500)
    assert a[0] == pytest.approx(x.mean() * 252) and a[1] < a[0] < a[2]
