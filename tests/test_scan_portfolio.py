"""The cost check for selected candidates (decision 0085): the book that the
IC describes, priced at the pessimistic level."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from src.scan import portfolio as P

pytestmark = pytest.mark.unit
K, T, U = 3, 200, 100
rng = np.random.default_rng(5)
DATES = [date(2016, 1, 4) + timedelta(days=i) for i in range(T)]


def _world(predictive: bool):
    stack = rng.normal(size=(K, T, U)).astype(np.float32)
    fwd = (0.05 * stack[0] if predictive else rng.normal(size=(T, U))).astype(np.float32) * 0.1
    ok = np.ones((T, U), bool)
    slots = np.tile(np.arange(U), (T, 1))
    adv = np.full((T, U), 5e8, np.float32)
    vol = np.full((T, U), 0.02, np.float32)
    return stack, ok, fwd, slots, adv, vol


def test_a_predictive_composite_earns_and_a_random_one_does_not():
    good = P.book(*_world(True), DATES, [0], [1.0], np.arange(T))
    bad = P.book(*_world(False), DATES, [0], [1.0], np.arange(T))
    assert good.gross.mean() > 0.01
    assert abs(bad.gross.mean()) < 0.05 and good.gross.mean() > bad.gross.mean()


def test_a_signal_that_never_changes_pays_only_the_first_rebalance():
    stack, ok, fwd, slots, adv, vol = _world(True)
    stack[:] = stack[:, :1, :]                        # frozen ranking
    b = P.book(stack, ok, fwd, slots, adv, vol, DATES, [0], [1.0], np.arange(T))
    assert b.turnover[0] == 1.0 and (b.turnover[1:] == 0).all()
    assert b.cost[0] > 0 and (b.cost[1:] == 0).all()


def test_cost_is_turnover_times_the_pessimistic_round_trip():
    b = P.book(*_world(False), DATES, [0], [1.0], np.arange(T))
    bps = P.pessimistic_bps(P.NOTIONAL_INR / 2 / 20, 5e8, 0.02, DATES[0])
    assert b.cost[0] == pytest.approx(2 * bps / 10_000)      # both legs bought new
    assert np.allclose(b.net, b.gross - b.cost)
