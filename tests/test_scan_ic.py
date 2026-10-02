"""The daily rank IC (Plan 4 §5). Alignment is pinned exactly: a signal that
knows tomorrow's return must NOT score through the one-session gap."""

from __future__ import annotations

import numpy as np
import pytest

from src.scan import ic

pytestmark = pytest.mark.unit
rng = np.random.default_rng(7)


def test_the_forward_window_is_t_plus_1_plus_gap_through_t_plus_gap_plus_h():
    r = rng.normal(size=(30, 3))
    f = ic.forward_returns(r, h=5, gap=1)
    assert f[4, 1] == pytest.approx(r[6:11, 1].sum())       # t=4: sessions 6..10
    assert np.isnan(f[24, 0])                                  # 26..30 runs past the end
    f0 = ic.forward_returns(r, h=5, gap=0)
    assert f0[4, 1] == pytest.approx(r[5:10, 1].sum())


def test_a_missing_return_voids_the_window_rather_than_shortening_it():
    r = rng.normal(size=(20, 2))
    r[8, 0] = np.nan
    f = ic.forward_returns(r, h=3, gap=1)
    assert np.isnan(f[5, 0]) and np.isnan(f[6, 0]) and not np.isnan(f[5, 1])


def test_an_injected_signal_is_found_and_noise_is_not():
    T, N = 300, 200
    r = rng.normal(0, 0.02, size=(T, N))
    fwd = ic.forward_returns(r, h=5, gap=1)
    informed = fwd + rng.normal(0, 0.05, size=(T, N))          # carries information
    noise = rng.normal(size=(T, N))
    s_inf = ic.summary(ic.rank_ic(informed, fwd))
    s_noise = ic.summary(ic.rank_ic(noise, fwd))
    assert s_inf["mean"] > 0.1 and s_inf["t"] > 10
    assert abs(s_noise["t"]) < 3


def test_knowing_tomorrow_does_not_score_through_the_gap():
    """The bid-ask bounce rule: session t+1 is skipped, so a signal equal to
    the t+1 return carries nothing about t+2..t+1+h."""
    T, N = 400, 200
    r = rng.normal(0, 0.02, size=(T, N))
    tomorrow = np.vstack([r[1:], np.full((1, N), np.nan)])
    s = ic.summary(ic.rank_ic(tomorrow, ic.forward_returns(r, h=5, gap=1)))
    assert abs(s["t"]) < 3


def test_a_thin_date_has_no_ic():
    x = rng.normal(size=(5, 150))
    y = rng.normal(size=(5, 150))
    x[2, 60:] = np.nan                                         # 60 valid names on date 2
    out = ic.rank_ic(x, y, min_names=100)
    assert np.isnan(out[2]) and not np.isnan(out[1])


def test_rank_ic_matches_spearman_on_one_date():
    from scipy.stats import spearmanr
    x = rng.normal(size=(1, 150))
    y = x * 0.3 + rng.normal(size=(1, 150))
    assert ic.rank_ic(x, y)[0] == pytest.approx(spearmanr(x[0], y[0]).statistic)
