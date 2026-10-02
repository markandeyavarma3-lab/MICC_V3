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

import warnings
from dataclasses import dataclass, field

import numpy as np

from src.scan.folds import FoldSet


def _means(ic, idx: np.ndarray) -> np.ndarray:
    """Per-candidate mean IC over `idx`: sessions of a (T x K) daily array, or
    blocks of an atlas.BlockIC (which weights each block by its sessions)."""
    if hasattr(ic, "mean_over"):
        return ic.mean_over(idx)
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
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


def select_and_test(ic: np.ndarray, fs: FoldSet, top_n: int, decay: bool = True) -> ProcedureResult:
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
        if decay:      # skipped by the null, which never reads it (an O(K log K) sort a fold)
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
    if hasattr(ic, "mean_over"):
        block = 1            # an atlas.BlockIC is already one row per block
    blocks = np.arange(T) // block
    out = np.empty(reps)
    for r in range(reps):
        signs = rng.choice([-1.0, 1.0], size=blocks[-1] + 1)[blocks]
        flipped = ic * signs if hasattr(ic, "mean_over") else ic * signs[:, None]
        out[r] = select_and_test(flipped, fs, top_n, decay=False).hit_rate
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


def record(results: list[ProcedureResult], pbo_value: float, manifest: dict, regime: str,
           candidates: int, commit: str, experiment_id: str | None = None,
           env: str | None = None, keys: list[str] | None = None,
           fold_names: list[str] | None = None) -> str:
    """Write one procedure run: the headline to governance `procedure_result`
    (write-once), the grid and the per-fold detail to the warehouse. Returns
    the run_id (sha256 of the manifest, first 16). A CONFIRM run must name its
    registered experiment; an EXPLORE run must not."""
    import hashlib
    import json
    import sqlite3
    from datetime import UTC, datetime

    import duckdb

    from src.common.migrate import migrate_duckdb, migrate_sqlite
    from src.common.paths import governance_db, research_db

    if regime not in ("EXPLORE", "CONFIRM"):
        raise ValueError(regime)
    if (regime == "CONFIRM") != (experiment_id is not None):
        raise ValueError("a CONFIRM run names its registered experiment; an EXPLORE run names none")
    run_id = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:16]
    now = datetime.now(UTC).isoformat()

    wh = research_db(env)
    migrate_duckdb(wh)
    con = duckdb.connect(str(wh))
    try:
        if not con.execute("SELECT 1 FROM scan_run WHERE run_id = ?", [run_id]).fetchone():
            con.execute("INSERT INTO scan_run VALUES (?, ?, ?, ?)",
                        [run_id, json.dumps(manifest, sort_keys=True), regime, now])
            if keys:
                # One bulk insert: 1.9M rows through executemany is row by row.
                import pandas as pd
                cells = pd.DataFrame({"run_id": run_id, "cell_idx": np.arange(len(keys), dtype=np.int64),
                                      "cell_key": keys,
                                      "depth": [k.count("|") + 1 for k in keys]})
                con.register("cells_df", cells)
                con.execute("INSERT INTO scan_cell SELECT run_id, cell_idx, cell_key, depth FROM cells_df")
        for r in results:
            names = fold_names or [f"fold_{i}" for i in range(len(r.per_fold_test_ic))]
            con.executemany(
                "INSERT OR REPLACE INTO scan_fold_result VALUES (?, ?, ?, ?, ?, ?)",
                [(run_id, "sequential", r.top_n, n, None, t)
                 for n, t in zip(names, r.per_fold_test_ic, strict=True)])
    finally:
        con.close()

    gv = governance_db(env)
    migrate_sqlite(gv)
    g = sqlite3.connect(str(gv))
    try:
        g.executemany(
            "INSERT INTO procedure_result (run_id, regime, experiment_id, top_n, folds, effective_folds,"
            " hit_rate, null_mean, p_vs_null, mean_train_ic, mean_test_ic, degradation, rank_decay, pbo,"
            " candidates, code_commit, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(run_id, regime, experiment_id, r.top_n, r.folds, r.effective_folds, r.hit_rate,
              float(np.mean(r.null_hit_rates)) if r.null_hit_rates is not None else None,
              r.p_vs_null, r.mean_train_ic, r.mean_test_ic, r.degradation, r.rank_decay,
              pbo_value, candidates, commit, now) for r in results])
        g.commit()
    finally:
        g.close()
    return run_id
