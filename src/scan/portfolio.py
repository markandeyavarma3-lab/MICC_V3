"""portfolio.py — the selected candidates as portfolios, net of costs.
Plan 4 §9, configs/scan.yml `costs`; decision 0085.

An IC is not a return. scan.yml: "Every surviving pattern is costed before it
is reported", and a pattern significant gross but negative net is
SIGNIFICANT_BUT_UNPROFITABLE — neither a pass nor a fail.

THE PORTFOLIO, aligned with the IC so the two describe one trade. On every
`rebalance`-th session t: rank J_t by the candidate's composite read in its
training sign, go long the top `quantile` and short the bottom, equal weight.
The return is each name's forward log return over t+1+gap .. t+gap+h — the
same window the IC scores — so with rebalance = h the holdings tile time.

COSTS AT THE PESSIMISTIC LEVEL (costs.yml reporting.levels.pessimistic) for a
NOTIONAL_INR long-short book: statutory round trip plus square-root impact,
priced on the median 20-session turnover and 63-session volatility of the
names traded that rebalance. Every name replaced is one round trip of its
per-name notional; turnover is the replaced fraction of each leg.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.stats import rankdata

NOTIONAL_INR = 100 * 1e7          # Rs 100 crore long-short, as exp_004


@dataclass
class Book:
    gross: np.ndarray        # per rebalance, long minus short, log
    turnover: np.ndarray     # per rebalance, mean replaced fraction of the two legs
    cost: np.ndarray         # per rebalance, fraction of one leg's notional
    sessions: np.ndarray     # rebalance session indices

    @property
    def net(self) -> np.ndarray:
        return self.gross - self.cost


def composite(stack: np.ndarray, ok: np.ndarray, idx: list[int], signs: list[float], t: int) -> np.ndarray:
    """The candidate's composite on J_t (rank-composite, decision 0084)."""
    m = ok[t]
    n = int(m.sum())
    return sum(s * rankdata(stack[i, t, m]) / n for i, s in zip(idx, signs, strict=True)) / len(idx)


def pessimistic_bps(per_name: float, adv: float, sigma: float, on: date) -> float:
    from src.research import costs
    sc = costs.cost_scenarios(turnover=per_name, on=on, quantity=per_name,
                              adv=adv if adv and adv > 0 else 1.0, sigma_daily=sigma)
    return next(s for s in sc.scenarios if s.name == "pessimistic").total_bps


def book(stack, ok, fwd_c, slots, adv_c, vol_c, dates, idx, signs, sessions,
         rebalance: int = 21, quantile: float = 0.2, notional: float = NOTIONAL_INR) -> Book:
    """Long-short book for one candidate over `sessions` (a fold's test window)."""
    gross, turn, cost, when = [], [], [], []
    prev_l: set = set()
    prev_s: set = set()
    for t in sessions[::rebalance]:
        m = ok[t]
        if m.sum() < 10:
            continue
        x = composite(stack, ok, idx, signs, t)
        cols = slots[t][m]
        y = fwd_c[t][m]
        k = max(1, int(round(quantile * len(x))))
        order = np.argsort(x)
        lo, hi = order[:k], order[-k:]
        L, S = set(cols[hi].tolist()), set(cols[lo].tolist())
        tl = 1.0 if not prev_l else len(L - prev_l) / len(L)
        ts = 1.0 if not prev_s else len(S - prev_s) / len(S)
        traded = np.r_[hi, lo]
        per_name = notional / 2 / k
        a = float(np.nanmedian(adv_c[t][m][traded]))
        v = float(np.nanmedian(vol_c[t][m][traded]))
        bps = pessimistic_bps(per_name, a, v if np.isfinite(v) else 0.02, dates[t])
        gross.append(float(np.nanmean(y[hi]) - np.nanmean(y[lo])))
        turn.append((tl + ts) / 2)
        cost.append((tl + ts) * bps / 10_000)       # each leg's replaced fraction pays a round trip
        when.append(t)
        prev_l, prev_s = L, S
    return Book(np.array(gross), np.array(turn), np.array(cost), np.array(when))
