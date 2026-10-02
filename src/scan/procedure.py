"""procedure.py — does searching work at all? Track S's headline.
Plan 4 §4, Plan 3 step 6S.3, configs/scan.yml `procedure_test`.

THE QUESTION IS ABOUT THE SEARCH, NOT ANY PATTERN. For every fold: rank all
candidates by their TRAINING mean IC, take the top N (N in scan.yml's top_n),
and look at the same candidates in the untouched TEST window.

  hit rate      fraction of folds whose selected set had a positive mean test
                IC. 0.5 is "searching does not work here".
  degradation   mean train IC minus mean test IC of the selected set — how much
                of what looked good in training was the selection itself.
  rank decay    Spearman, across ALL candidates, of train IC against test IC,
                averaged over folds. Zero means training ranks say nothing.
  PBO           probability of backtest overfitting (Bailey, Borwein, Lopez de
                Prado, Zhu): over the CPCV splits, the share where the
                in-sample best lands in the bottom half out of sample.

DIRECTION IS SELECTED TOO. A candidate with a strongly NEGATIVE training IC is
as selectable as a positive one — the search would trade it the other way — so
selection is on |train IC| and the test IC is read in the training sign.

THE NULL IS MEASURED, NOT ASSUMED (the S2 counterpart of step 6S.2). Hit rate
0.5 is the null only if folds are independent and candidates carry no
persistent edge; neither holds exactly. `null_hit_rates` flips the sign of
every candidate's IC in monthly blocks, one sign shared by all candidates, and
reruns the selection; the observed hit rate is compared with THAT
distribution. Overlapping folds are why a binomial on the nominal fold count
would overstate the evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from src.scan.folds import FoldSet


def _means(ic: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """Per-candidate mean IC over sessions `idx` (ic is T x K, NaN = no IC)."""
    with np.errstate(invalid="ignore"):
        return np.nanmean(ic[idx], axis=0)


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ok = ~np.isnan(a) & ~np.isnan(b)
    if ok.sum() < 3:
        return float("nan")
    ra = np.argsort(np.argsort(a[ok])).astype(float)
    rb = np.argsort(np.argsort(b[ok])).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


@dataclass
class ProcedureResult:
    top_n: int
    folds: int
    effective_folds: float
    hit_rate: float
    mean_train_ic: float
    mean_test_ic: float
    degradation: float
    rank_decay: float
    per_fold_test_ic: list[float] = field(default_factory=list)
    null_hit_rates: np.ndarray | None = None

    @property
    def p_vs_null(self) -> float:
        """Share of null hit rates at or above the observed one (one-sided:
        the claim is that searching works BETTER than chance)."""
        if self.null_hit_rates is None or not len(self.null_hit_rates):
            return float("nan")
        return float((np.sum(self.null_hit_rates >= self.hit_rate) + 1) / (len(self.null_hit_rates) + 1))


def select_and_test(ic: np.ndarray, fs: FoldSet, top_n: int) -> ProcedureResult:
    train_sel, test_sel, decays = [], [], []
    for f in fs.folds:
        tr, te = _means(ic, f.train), _means(ic, f.test)
        usable = ~np.isnan(tr) & ~np.isnan(te)
        if usable.sum() < top_n:
            continue
        cand = np.where(usable)[0]
        order = cand[np.argsort(-np.abs(tr[cand]))][:top_n]
        sign = np.sign(tr[order])
        train_sel.append(float(np.mean(np.abs(tr[order]))))
        test_sel.append(float(np.mean(sign * te[order])))
        decays.append(_spearman(tr[cand] * 1.0, te[cand] * 1.0))
    if not test_sel:
        raise ValueError(f"no fold had {top_n} usable candidates")
    tests = np.array(test_sel)
    return ProcedureResult(
        top_n=top_n, folds=len(tests), effective_folds=fs.effective,
        hit_rate=float(np.mean(tests > 0)),
        mean_train_ic=float(np.mean(train_sel)), mean_test_ic=float(np.mean(tests)),
        degradation=float(np.mean(train_sel) - np.mean(tests)),
        rank_decay=float(np.nanmean(decays)) if decays else float("nan"),
        per_fold_test_ic=[float(x) for x in tests])


def pbo(ic: np.ndarray, cpcv: FoldSet) -> float:
    """CSCV probability of backtest overfitting: for each split, the
    in-sample best candidate's out-of-sample relative rank w (in (0,1));
    PBO = share of splits with logit(w) <= 0, i.e. the best in-sample sits at
    or below the out-of-sample median. Direction is selected as above."""
    lam = []
    for f in cpcv.folds:
        tr, te = _means(ic, f.train), _means(ic, f.test)
        usable = np.where(~np.isnan(tr) & ~np.isnan(te))[0]
        if len(usable) < 2:
            continue
        best = usable[np.argmax(np.abs(tr[usable]))]
        oos = te[usable] * np.sign(tr[best])
        w = (np.sum(oos < oos[list(usable).index(best)]) + 0.5) / len(usable)
        lam.append(np.log(w / (1 - w)))
    return float(np.mean(np.array(lam) <= 0)) if lam else float("nan")


#: Sessions per sign block in the null — one trading month. Short enough that a
#: training window spans many independent signs, long enough to keep the
#: within-month dependence of overlapping forward windows.
NULL_BLOCK_SESSIONS = 21


def null_hit_rates(ic: np.ndarray, fs: FoldSet, top_n: int, reps: int = 200,
                   seed: int = 20261002, block: int = NULL_BLOCK_SESSIONS) -> np.ndarray:
    """The measured null for the hit rate: BLOCK SIGN FLIPS.

    Every candidate's IC on every session of a `block`-session block is
    multiplied by one random +-1, shared by all candidates. A lasting edge
    becomes independent between any training and test window (they sit in
    different blocks), while the magnitude of each candidate's IC, its
    within-block dependence and the correlation between candidates are kept.

    FIRST VERSION, AND WHY IT WAS WRONG (2026-10-02). It removed each
    candidate's full-sample mean, then rotated. The full-sample mean contains
    the training mean, so the centred TEST window leans against whatever
    training selected: on pure noise the null hit rate sat near 0.1 and noise
    read as 'searching works', p = 0.016. A test caught it; the sign flip has
    no such coupling."""
    rng = np.random.default_rng(seed)
    T = ic.shape[0]
    blocks = np.arange(T) // block
    out = np.empty(reps)
    for r in range(reps):
        signs = rng.choice([-1.0, 1.0], size=blocks[-1] + 1)[blocks]
        out[r] = select_and_test(ic * signs[:, None], fs, top_n).hit_rate
    return out


def run(ic: np.ndarray, sequential: FoldSet, cpcv: FoldSet, top_n: list[int],
        reps: int = 200) -> tuple[list[ProcedureResult], float]:
    """The procedure test for every N, each with its measured null, plus PBO."""
    results = []
    for n in top_n:
        r = select_and_test(ic, sequential, n)
        r.null_hit_rates = null_hit_rates(ic, sequential, n, reps)
        results.append(r)
    return results, pbo(ic, cpcv)
