"""fastic.py — every candidate's daily IC from per-date moments, exactly.
Plan 4 §10; decision 0084.

WHY. The direct route — combine the candidate's ranks, re-rank, correlate with
the re-ranked forward return — re-ranks two (sessions x names) arrays per
candidate. Measured 2026-10-02 on the explore panel, 1/1000 of the depth-3
grid did not finish in an hour: the full grid projected to well over a month
against scan.yml's 21-day budget.

THE IDENTITY THAT REMOVES THE COST. On date t take one cross-section J_t
(below). Let Z_i be base signal i's percentile ranks on J_t, centred, and Y
the forward return's, centred. A candidate is x = sum_a s_a R_a / d, so

    cov(x, y)  = (1/d) sum_a s_a C_iy[a]
    var(x)     = (1/d^2) sum_a sum_b s_a s_b C_ii[a, b]
    IC_t(x)    = sum_a s_a C_iy[a] / sqrt( sum_ab s_a s_b C_ii[a, b] * C_yy )

with C_ii = Z Z^T, C_iy = Z Y, C_yy = Y.Y computed ONCE per date. Each
candidate then costs O(d^2) per date instead of two sorts of the panel.

WHAT THE STATISTIC IS, STATED BEFORE ANY CANDIDATE IS SCORED ON REAL DATA.
  J_t   the names in the point-in-time universe on t with a forward return AND
        every base signal defined. One cross-section for all candidates on a
        date, so no candidate is scored on an easier set of names. Fewer than
        min_names names: no IC that date.
  depth 1   Spearman correlation of the signal and the forward return on J_t
            (average ranks for ties) — the rank IC of ic.rank_ic, on J_t.
  depth 2-3 Pearson correlation of the mean of the components' signed
            percentile ranks with the forward return's percentile rank on J_t
            — the standard rank-composite IC. It is NOT the Spearman of the
            composite (which would re-rank it); the difference is the cost
            this module exists to avoid, and it is the same for every
            candidate of a depth.
Both are tested against a direct computation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import rankdata


@dataclass
class Moments:
    cii: np.ndarray        # (T, K, K) float32
    ciy: np.ndarray        # (T, K) float32
    cyy: np.ndarray        # (T,) float64, NaN on a date without an IC
    n: np.ndarray          # (T,) names in J_t


def _universe_slots(universe: np.ndarray) -> np.ndarray:
    """(T, U) column index of each universe name per date, -1 padded."""
    T = universe.shape[0]
    U = int(universe.sum(axis=1).max()) if T else 0
    out = np.full((T, max(U, 1)), -1, dtype=np.int64)
    for t in range(T):
        cols = np.flatnonzero(universe[t])
        out[t, :len(cols)] = cols
    return out


def compress(a: np.ndarray, slots: np.ndarray) -> np.ndarray:
    """A (T x N) array reduced to its universe slots, (T x U), NaN in padding."""
    T = a.shape[0]
    rows = np.repeat(np.arange(T)[:, None], slots.shape[1], axis=1)
    out = a[rows, np.where(slots >= 0, slots, 0)].astype(np.float32)
    out[slots < 0] = np.nan
    return out


def moments(base: np.ndarray, fwd: np.ndarray, min_names: int = 100) -> Moments:
    """`base` (K, T, U) and `fwd` (T, U), both already reduced to universe
    slots. Builds J_t, the centred percentile ranks and their cross-products."""
    K, T, _ = base.shape
    cii = np.full((T, K, K), np.nan, dtype=np.float32)
    ciy = np.full((T, K), np.nan, dtype=np.float32)
    cyy = np.full(T, np.nan)
    n = np.zeros(T, dtype=np.int64)
    for t in range(T):
        x = base[:, t, :]
        y = fwd[t]
        ok = np.isfinite(y) & np.isfinite(x).all(axis=0)
        m = int(ok.sum())
        n[t] = m
        if m < min_names:
            continue
        z = rankdata(x[:, ok], axis=1) / m
        z -= z.mean(axis=1, keepdims=True)
        yr = rankdata(y[ok]) / m
        yr -= yr.mean()
        cii[t] = (z @ z.T).astype(np.float32)
        ciy[t] = (z @ yr).astype(np.float32)
        cyy[t] = float(yr @ yr)
    return Moments(cii, ciy, cyy, n)


def batch_ic(mo: Moments, idx: np.ndarray, signs: np.ndarray) -> np.ndarray:
    """(T, B) daily IC for B candidates of one depth: idx and signs (B, d)."""
    B, d = idx.shape
    num = np.zeros((mo.cyy.shape[0], B))
    var = np.zeros((mo.cyy.shape[0], B))
    for a in range(d):
        num += signs[:, a] * mo.ciy[:, idx[:, a]]
        for b in range(d):
            var += (signs[:, a] * signs[:, b]) * mo.cii[:, idx[:, a], idx[:, b]]
    with np.errstate(invalid="ignore", divide="ignore"):
        ic = num / np.sqrt(var * mo.cyy[:, None])
    ic[~np.isfinite(ic)] = np.nan
    return ic


def block_sums(ic: np.ndarray, block: int) -> tuple[np.ndarray, np.ndarray]:
    """(T, B) daily IC -> (nblocks, B) sums and counts over `block`-session blocks."""
    T = ic.shape[0]
    starts = np.arange(0, T, block)
    ok = np.isfinite(ic)
    sums = np.add.reduceat(np.where(ok, ic, 0.0), starts, axis=0).astype(np.float32)
    counts = np.add.reduceat(ok.astype(np.int32), starts, axis=0).astype(np.int16)
    return sums, counts
