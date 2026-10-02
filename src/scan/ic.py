"""ic.py — the daily cross-sectional rank IC, Track S's one estimator.
Plan 4 §5, configs/scan.yml `cross_sectional`, decision 0021.

THE UNIT OF EVIDENCE IS THE DATE. On each session the signal ranks the names
and the forward return ranks them again; the Spearman correlation of the two
rankings is ONE observation, however many names it spans. Pooling names buys
precision within a date and no extra dates (scan.yml: 568 IC observations,
MDE 0.014 on mean IC).

Rank IC is invariant to subtracting the same number from every name on a date,
so PRICE and MARKET_RELATIVE returns give the same IC; the pooled average of
market-relative returns, which is identically zero (0021), never appears.

ALIGNMENT, THE PART THAT IS EASY TO GET WRONG. A signal at session t may use
data through the close of t. Its forward return is the sum of daily log
returns over sessions t+1+gap .. t+gap+h — `gap` sessions are skipped first
(scan.yml `mandatory_gap_sessions: 1`), because a close at the bid followed by
a close at the ask manufactures reversal: ~30% of short-horizon reversal died
with a one-session gap when it was measured. A window with any missing return
is NaN, never a partial sum.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd


def forward_returns(log_ret: np.ndarray, h: int, gap: int = 1) -> np.ndarray:
    """(T x N) daily log returns -> (T x N) forward sums over t+1+gap .. t+gap+h.
    NaN where any return in the window is missing or the window passes the end."""
    T, N = log_ret.shape
    filled = np.nan_to_num(log_ret, nan=0.0)
    ok = (~np.isnan(log_ret)).astype(np.int32)
    cs = np.vstack([np.zeros((1, N)), np.cumsum(filled, axis=0)])
    cn = np.vstack([np.zeros((1, N), dtype=np.int64), np.cumsum(ok, axis=0)])
    out = np.full((T, N), np.nan)
    lo = np.arange(T) + 1 + gap          # first return in the window
    hi = lo + h                          # one past the last
    valid = hi <= T
    t = np.where(valid)[0]
    s = cs[hi[t]] - cs[lo[t]]
    n = cn[hi[t]] - cn[lo[t]]
    s[n < h] = np.nan
    out[t] = s
    return out


def rank_ic(signal: np.ndarray, fwd: np.ndarray, min_names: int = 100) -> np.ndarray:
    """Per-date Spearman correlation between `signal` and `fwd` (both T x N),
    over the names where BOTH are present. NaN on a date with fewer than
    `min_names` such names, or with no variation in either ranking."""
    both = ~np.isnan(signal) & ~np.isnan(fwd)
    x = pd.DataFrame(np.where(both, signal, np.nan)).rank(axis=1).to_numpy()
    y = pd.DataFrame(np.where(both, fwd, np.nan)).rank(axis=1).to_numpy()
    n = both.sum(axis=1)
    # A date with no valid pair (the tail, where forward windows run out) has
    # an empty mean; it is NaN by the n < min_names rule below either way.
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        xc = x - np.nanmean(np.where(both, x, np.nan), axis=1, keepdims=True)
        yc = y - np.nanmean(np.where(both, y, np.nan), axis=1, keepdims=True)
    xc = np.where(both, xc, 0.0)
    yc = np.where(both, yc, 0.0)
    num = (xc * yc).sum(axis=1)
    den = np.sqrt((xc ** 2).sum(axis=1) * (yc ** 2).sum(axis=1))
    with np.errstate(invalid="ignore", divide="ignore"):
        ic = num / den
    ic[(n < min_names) | (den == 0)] = np.nan
    return ic


def summary(ic: np.ndarray) -> dict[str, float]:
    """Mean IC, its naive SE and t over the dates that have one. Serial
    correlation from overlapping forward windows is NOT corrected here — the
    procedure test works on fold-level means, and any per-signal t reported
    from this must say so."""
    v = ic[~np.isnan(ic)]
    if len(v) < 2:
        return {"n": float(len(v)), "mean": float("nan"), "se": float("nan"), "t": float("nan")}
    se = float(v.std(ddof=1) / np.sqrt(len(v)))
    return {"n": float(len(v)), "mean": float(v.mean()), "se": se,
            "t": float(v.mean() / se) if se > 0 else float("nan")}
