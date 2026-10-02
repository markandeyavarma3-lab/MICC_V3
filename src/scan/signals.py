"""signals.py — Track S2's base signals and their combinations.
Plan 4 §7, Plan 3 step 6S.5, configs/scan.yml `signals`.

EVERY BASE SIGNAL HAS A WRITTEN MECHANISM (scan.yml
`require_mechanism_per_base_signal`). The scan is wide on purpose — the width
is the instrument that measures overfitting — but width is not a licence to
include things nobody can explain. A signal without a mechanism raises.

EVERY SIGNAL USES DATA THROUGH THE CLOSE OF t AND NOTHING LATER. Rolling
windows end at t; nothing is centred, nothing shifted backwards. A test
perturbs every price after a cut and requires every signal's values before
the cut to be unchanged — the property that makes the IC's forward window
honest.

THE COUNT IS COMPUTED, NEVER WRITTEN DOWN. scan.yml's "~190" is a planning
figure; `base_signals()` and `combination_count()` give the realised numbers
at run time, and the multiplicity bar is simulated from those. A test greps
this package for hard-coded totals.

COMBINATIONS. A depth-d candidate is the equal-weight mean of the
cross-sectional percentile ranks of d distinct base signals, each entering
with a sign. Signs are relative, so a depth-d combination has 2^(d-1)
orientations — the overall direction is chosen by the procedure test, which
selects on |IC|. Threshold crossings (scan.yml `crosses_with_thresholds`) are
an extension measured by the benchmark gate, not built here.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import combinations
from math import comb

import numpy as np
import pandas as pd

from src.scan.panel import Panel

MECHANISMS = {
    "momentum": "underreaction to news: prices adjust to information over weeks, so past winners keep winning",
    "reversal": "liquidity provision is paid: short-term price pressure from uninformed flow reverts",
    "volatility": "risk compensation, or the low-volatility anomaly where lottery-seeking overprices risky names",
    "volume": "attention and participation: unusual volume marks news and draws buyers",
    "liquidity": "the illiquidity premium: holders of hard-to-trade names are paid for it",
    "seasonal": "flow calendar effects: recurring institutional flows repeat at the same time each year",
    "institutional": "disclosed institutional buying carries information or price pressure (Track D's inputs)",
}


@dataclass(frozen=True)
class BaseSignal:
    id: str
    family: str
    note: str
    fn: Callable[[Ctx], np.ndarray]

    @property
    def mechanism(self) -> str:
        if self.family not in MECHANISMS:
            raise ValueError(f"{self.id}: family {self.family!r} has no written mechanism")
        return f"{MECHANISMS[self.family]} — {self.note}"


class Ctx:
    """Derived arrays, computed once per panel and shared by every signal."""

    def __init__(self, p: Panel):
        self.p = p
        self.r = p.log_returns().astype(np.float64)
        self.turnover = (p.close * p.volume).astype(np.float64)
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)     # session 0 has no return
            self.m = np.nanmean(np.where(p.universe, self.r, np.nan), axis=1)
        self._cache: dict = {}
        # ONLY arrays this context holds for its whole life may be cached by
        # identity. The first version keyed every array on id(), and a
        # temporary (an overnight-gap array, say) freed after use handed its
        # address to the next temporary, which then read the first one's
        # rolling result: 16 signals failed the no-lookahead test that way.
        self._stable = {id(x) for x in (self.r, self.turnover, p.close, p.open, p.high,
                                         p.low, p.volume, p.deal_buy, p.deal_sell)}

    def roll(self, a: np.ndarray, L: int, how: str) -> np.ndarray:
        key = (id(a), L, how)
        if id(a) in self._stable and key in self._cache:
            return self._cache[key]
        r = pd.DataFrame(a).rolling(L, min_periods=max(2, int(0.8 * L)))
        out = getattr(r, how)().to_numpy()
        if id(a) in self._stable:
            self._cache[key] = out
        return out


def _lag(a: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(a, np.nan)
    if k < len(a):
        out[k:] = a[:len(a) - k]
    return out


def _momentum() -> list[BaseSignal]:
    out = []
    for L in (21, 42, 63, 126, 189, 252):
        for s in (0, 5, 21):
            if s >= L:
                continue
            out.append(BaseSignal(f"mom_{L}_skip{s}", "momentum", f"return over sessions t-{L}..t-{s}",
                                  lambda c, L=L, s=s: _lag(c.roll(c.r, L - s, "sum"), s)))
    for L in (63, 126, 252):
        out.append(BaseSignal(f"ram_{L}", "momentum", f"{L}-session return per unit volatility",
                              lambda c, L=L: c.roll(c.r, L, "sum") / c.roll(c.r, L, "std")))
        out.append(BaseSignal(f"hi_{L}", "momentum", f"price relative to its {L}-session high (anchoring)",
                              lambda c, L=L: c.p.close / c.roll(c.p.close.astype(np.float64), L, "max")))
    for L in (10, 20, 50, 100, 200):
        out.append(BaseSignal(f"ma_ratio_{L}", "momentum", f"price over its {L}-session moving average",
                              lambda c, L=L: c.p.close / c.roll(c.p.close.astype(np.float64), L, "mean")))
    for s, L in ((5, 20), (10, 50), (20, 100), (50, 200)):
        out.append(BaseSignal(f"ma_cross_{s}_{L}", "momentum", f"{s}- over {L}-session moving average",
                              lambda c, s=s, L=L: c.roll(c.p.close.astype(np.float64), s, "mean")
                              / c.roll(c.p.close.astype(np.float64), L, "mean")))
    for L in (21, 63, 126, 252):
        out.append(BaseSignal(f"updays_{L}", "momentum", f"share of up sessions in {L} (trend consistency)",
                              lambda c, L=L: c.roll(np.where(np.isnan(c.r), np.nan, (c.r > 0) * 1.0), L, "mean")))
    for L in (63, 126):
        out.append(BaseSignal(f"mom_accel_{L}", "momentum", f"{L}-session return minus the {L} before it",
                              lambda c, L=L: c.roll(c.r, L, "sum") - _lag(c.roll(c.r, L, "sum"), L)))
    return out


def _reversal() -> list[BaseSignal]:
    out = []
    for L in (1, 2, 3, 5, 10):
        out.append(BaseSignal(f"rev_{L}", "reversal", f"return over the last {L} session(s)",
                              lambda c, L=L: c.roll(c.r, L, "sum") if L > 1 else c.r))
    def gap(c):
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.log(c.p.open / _lag(c.p.close, 1)).astype(np.float64)
    def intra(c):
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.log(c.p.close / c.p.open).astype(np.float64)
    for L in (1, 5, 10, 21):
        out.append(BaseSignal(f"gap_{L}", "reversal", f"mean overnight return over {L}",
                              lambda c, L=L: c.roll(gap(c), L, "mean") if L > 1 else gap(c)))
        out.append(BaseSignal(f"intraday_{L}", "reversal", f"mean open-to-close return over {L}",
                              lambda c, L=L: c.roll(intra(c), L, "mean") if L > 1 else intra(c)))
    for L in (5, 21, 63):
        out.append(BaseSignal(f"maxret_{L}", "reversal", f"largest daily return in {L} (lottery demand)",
                              lambda c, L=L: c.roll(c.r, L, "max")))
        out.append(BaseSignal(f"minret_{L}", "reversal", f"worst daily return in {L} (fire sale)",
                              lambda c, L=L: c.roll(c.r, L, "min")))
        out.append(BaseSignal(f"off_low_{L}", "reversal", f"price over its {L}-session low",
                              lambda c, L=L: c.p.close / c.roll(c.p.close.astype(np.float64), L, "min")))
        out.append(BaseSignal(f"range_pos_{L}", "reversal", f"position inside the {L}-session high-low range",
                              lambda c, L=L: (c.p.close - c.roll(c.p.low.astype(np.float64), L, "min"))
                              / (c.roll(c.p.high.astype(np.float64), L, "max")
                                 - c.roll(c.p.low.astype(np.float64), L, "min"))))
    return out


def _volatility() -> list[BaseSignal]:
    out = []
    for L in (10, 21, 63, 126, 252):
        out.append(BaseSignal(f"vol_{L}", "volatility", f"std of daily returns over {L}",
                              lambda c, L=L: c.roll(c.r, L, "std")))
    for L in (21, 63, 126):
        out.append(BaseSignal(f"downvol_{L}", "volatility", f"std of negative returns over {L}",
                              lambda c, L=L: c.roll(np.where(c.r < 0, c.r, np.where(np.isnan(c.r), np.nan, 0.0)),
                                                    L, "std")))
    def hl2(c):
        with np.errstate(divide="ignore", invalid="ignore"):
            return (np.log(c.p.high / c.p.low) ** 2).astype(np.float64)
    for L in (10, 21, 63):
        out.append(BaseSignal(f"parkinson_{L}", "volatility", f"high-low (Parkinson) volatility over {L}",
                              lambda c, L=L: np.sqrt(c.roll(hl2(c), L, "mean") / (4 * np.log(2)))))
    for L in (63, 126):
        out.append(BaseSignal(f"ivol_{L}", "volatility", f"std of market-relative returns over {L}",
                              lambda c, L=L: c.roll(c.r - c.m[:, None], L, "std")))
    out.append(BaseSignal("volvol_63", "volatility", "variability of 21-session volatility over 63",
                          lambda c: c.roll(c.roll(c.r, 21, "std"), 63, "std")))
    for L in (63, 126, 252):
        out.append(BaseSignal(f"skew_{L}", "volatility", f"skewness of daily returns over {L}",
                              lambda c, L=L: c.roll(c.r, L, "skew")))
        def beta(c, L=L):
            m = np.broadcast_to(c.m[:, None], c.r.shape)
            mr = c.roll(c.r * m, L, "mean") - c.roll(c.r, L, "mean") * c.roll(np.ascontiguousarray(m), L, "mean")
            return mr / c.roll(np.ascontiguousarray(m), L, "var")
        out.append(BaseSignal(f"beta_{L}", "volatility", f"beta to the equal-weight universe over {L}", beta))
    for L in (63, 252):
        out.append(BaseSignal(f"kurt_{L}", "volatility", f"excess kurtosis over {L} (tail risk)",
                              lambda c, L=L: c.roll(c.r, L, "kurt")))
    for L in (5, 21):
        out.append(BaseSignal(f"hl_range_{L}", "volatility", f"mean (high-low)/close over {L}",
                              lambda c, L=L: c.roll(((c.p.high - c.p.low) / c.p.close).astype(np.float64), L, "mean")))
    out.append(BaseSignal("vol_ratio_21_126", "volatility", "21- over 126-session volatility (regime change)",
                          lambda c: c.roll(c.r, 21, "std") / c.roll(c.r, 126, "std")))
    return out


def _volume() -> list[BaseSignal]:
    out = []
    lt = lambda c: np.log(np.where(c.turnover > 0, c.turnover, np.nan))  # noqa: E731
    lv = lambda c: np.log(np.where(c.p.volume > 0, c.p.volume, np.nan).astype(np.float64))  # noqa: E731
    for L in (5, 21, 63):
        out.append(BaseSignal(f"lturn_{L}", "volume", f"log mean rupee turnover over {L}",
                              lambda c, L=L: np.log(c.roll(c.turnover, L, "mean"))))
    for s, L in ((1, 21), (5, 21), (5, 63), (21, 126), (21, 252)):
        out.append(BaseSignal(f"vsurge_{s}_{L}", "volume", f"{s}- over {L}-session mean volume",
                              lambda c, s=s, L=L: (c.roll(c.p.volume.astype(np.float64), s, "mean") if s > 1
                                                   else c.p.volume.astype(np.float64))
                              / c.roll(c.p.volume.astype(np.float64), L, "mean")))
    for L in (21, 63):
        out.append(BaseSignal(f"vstd_{L}", "volume", f"std of log volume over {L}",
                              lambda c, L=L: c.roll(lv(c), L, "std")))
        def pvc(c, L=L):
            dv = lv(c) - _lag(lv(c), 1)
            a, b = pd.DataFrame(c.r), pd.DataFrame(dv)
            return a.rolling(L, min_periods=int(0.8 * L)).corr(b).to_numpy()
        out.append(BaseSignal(f"pvcorr_{L}", "volume", f"correlation of return and volume change over {L}", pvc))
        out.append(BaseSignal(f"upvol_{L}", "volume", f"share of volume on up sessions over {L}",
                              lambda c, L=L: c.roll(np.where(c.r > 0, c.p.volume, 0.0).astype(np.float64), L, "sum")
                              / c.roll(c.p.volume.astype(np.float64), L, "sum")))
        out.append(BaseSignal(f"abvol_{L}", "volume", f"sessions in {L} with volume over 2x its 63-session mean",
                              lambda c, L=L: c.roll((c.p.volume > 2 * _lag(c.roll(c.p.volume.astype(np.float64), 63, "mean"), 1))
                                                    .astype(np.float64), L, "sum")))
    out.append(BaseSignal("turn_trend", "volume", "21- minus 126-session log turnover",
                          lambda c: np.log(c.roll(c.turnover, 21, "mean")) - np.log(c.roll(c.turnover, 126, "mean"))))
    out.append(BaseSignal("lturn_level", "volume", "log turnover today (attention spike)", lt))
    return out


def _liquidity() -> list[BaseSignal]:
    out = []
    amihud = lambda c: np.abs(c.r) / np.where(c.turnover > 0, c.turnover, np.nan)  # noqa: E731
    for L in (5, 21, 63, 126, 252):
        out.append(BaseSignal(f"amihud_{L}", "liquidity", f"Amihud |return| per rupee traded over {L}",
                              lambda c, L=L: c.roll(amihud(c), L, "mean")))
    for L in (21, 63, 126):
        out.append(BaseSignal(f"zeroret_{L}", "liquidity", f"share of zero-return sessions over {L}",
                              lambda c, L=L: c.roll(np.where(np.isnan(c.r), np.nan, (np.abs(c.r) < 1e-9) * 1.0),
                                                    L, "mean")))
    for L in (21, 63):
        def roll_spread(c, L=L):
            lag = _lag(c.r, 1)
            cov = c.roll(c.r * lag, L, "mean") - c.roll(c.r, L, "mean") * c.roll(lag, L, "mean")
            return 2 * np.sqrt(np.clip(-cov, 0, None))
        out.append(BaseSignal(f"roll_{L}", "liquidity", f"Roll implied spread over {L}", roll_spread))
        out.append(BaseSignal(f"turn_cv_{L}", "liquidity", f"coefficient of variation of turnover over {L}",
                              lambda c, L=L: c.roll(c.turnover, L, "std") / c.roll(c.turnover, L, "mean")))
    out.append(BaseSignal("log_price", "liquidity", "log price level (low-priced names are costlier to trade)",
                          lambda c: np.log(c.p.close.astype(np.float64))))
    out.append(BaseSignal("illiq_trend", "liquidity", "21- over 126-session Amihud (worsening liquidity)",
                          lambda c: c.roll(amihud(c), 21, "mean") / c.roll(amihud(c), 126, "mean")))
    return out


def _seasonal() -> list[BaseSignal]:
    """Heston-Sadka: a stock's return in the same window of past years.
    The window one year back that the NEXT 21 sessions will mirror is
    sessions t+1-252k .. t+21-252k — entirely in the past for k >= 1."""
    out = []
    def same_window(c, years, h=21):
        s21 = c.roll(c.r, h, "sum")              # sum over (t-h, t]
        parts = [_lag(s21, 252 * k - h) for k in years]
        if len(parts) == 1:
            return parts[0]
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)     # years before the data: all-NaN
            return np.nanmean(np.stack(parts), axis=0)
    for k in (1, 2, 3, 5):
        out.append(BaseSignal(f"hs_last{k}y", "seasonal", f"mean return in the coming 21-session window over the last {k} year(s)",
                              lambda c, k=k: same_window(c, range(1, k + 1))))
    out.append(BaseSignal("hs_years2to5", "seasonal", "the same, years 2-5 only (skips last year's momentum)",
                          lambda c: same_window(c, range(2, 6))))
    for k in (1, 2):
        out.append(BaseSignal(f"hs63_last{k}y", "seasonal", f"the coming 63-session window, last {k} year(s)",
                              lambda c, k=k: same_window(c, range(1, k + 1), h=63)))
    out.append(BaseSignal("annual_rev", "seasonal", "return a year ago over 21 sessions (annual reversal)",
                          lambda c: _lag(c.roll(c.r, 21, "sum"), 252)))
    def tom(c, months):
        d = c.p.dates
        mo = np.array([x.year * 12 + x.month for x in d])
        edge = np.zeros(len(d), dtype=bool)
        for i in range(len(d)):
            # last three sessions of a month or first three of the next
            nxt = mo[i + 1:i + 4]
            prv = mo[max(0, i - 3):i]
            edge[i] = (len(nxt) and (nxt != mo[i]).any()) or (len(prv) and (prv != mo[i]).any())
        x = np.where(edge[:, None], c.r, np.nan)
        return pd.DataFrame(x).rolling(int(months * 21), min_periods=int(months * 4)).mean().to_numpy()
    for k in (12, 24, 36):
        out.append(BaseSignal(f"tom_{k}m", "seasonal", f"mean turn-of-month return over the last {k} months",
                              lambda c, k=k: tom(c, k)))
    return out


def _institutional() -> list[BaseSignal]:
    out = []
    def per_turn(c, a, L):
        return c.roll(a.astype(np.float64), L, "sum") / c.roll(c.turnover, L, "sum")
    for L in (5, 21, 63, 126):
        out.append(BaseSignal(f"dnet_{L}", "institutional", f"net disclosed deal buying per rupee traded over {L}",
                              lambda c, L=L: per_turn(c, c.p.deal_buy - c.p.deal_sell, L)))
    for L in (21, 63):
        out.append(BaseSignal(f"dbuy_{L}", "institutional", f"disclosed deal buying per rupee traded over {L}",
                              lambda c, L=L: per_turn(c, c.p.deal_buy, L)))
        out.append(BaseSignal(f"dsell_{L}", "institutional", f"disclosed deal selling per rupee traded over {L}",
                              lambda c, L=L: per_turn(c, c.p.deal_sell, L)))
        out.append(BaseSignal(f"ddays_{L}", "institutional", f"sessions with a disclosed deal in {L}",
                              lambda c, L=L: c.roll(((c.p.deal_buy + c.p.deal_sell) > 0).astype(np.float64), L, "sum")))
    for hl in (10, 42):
        out.append(BaseSignal(f"dnet_ewm{hl}", "institutional", f"net deal buying, half-life {hl} sessions, per mean turnover",
                              lambda c, hl=hl: pd.DataFrame((c.p.deal_buy - c.p.deal_sell).astype(np.float64))
                              .ewm(halflife=hl).mean().to_numpy() / c.roll(c.turnover, 63, "mean")))
    return out


def base_signals() -> list[BaseSignal]:
    sigs = _momentum() + _reversal() + _volatility() + _volume() + _liquidity() + _seasonal() + _institutional()
    ids = [s.id for s in sigs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate base-signal id")
    for s in sigs:
        _ = s.mechanism        # raises if a family has no written mechanism
    return sigs


def combination_count(n_base: int, depth: int) -> int:
    """Depth-1..depth candidates: C(n, d) choices of d signals x 2^(d-1)
    relative orientations each."""
    return sum(comb(n_base, d) * 2 ** (d - 1) for d in range(1, depth + 1))


def combinations_of(ids: list[str], depth: int) -> Iterator[tuple[tuple[str, int], ...]]:
    """Every candidate as ((id, sign), ...). The first component's sign is +1;
    the procedure chooses the overall direction."""
    for d in range(1, depth + 1):
        for group in combinations(ids, d):
            for bits in range(2 ** (d - 1)):
                signs = [1] + [(-1 if (bits >> i) & 1 else 1) for i in range(d - 1)]
                yield tuple(zip(group, signs, strict=True))


def percentile_ranks(x: np.ndarray, universe: np.ndarray) -> np.ndarray:
    """Cross-sectional percentile rank in (0, 1] inside the universe; NaN outside."""
    m = np.where(universe & ~np.isnan(x), x, np.nan)
    return pd.DataFrame(m).rank(axis=1, pct=True).to_numpy()


def combine(ranks: dict[str, np.ndarray], cand: tuple[tuple[str, int], ...]) -> np.ndarray:
    """A candidate's value: the mean of its components' signed percentile ranks."""
    stack = np.stack([ranks[i] * s for i, s in cand])
    return stack.mean(axis=0) if len(cand) > 1 else stack[0]
