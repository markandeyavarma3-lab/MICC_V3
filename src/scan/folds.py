"""folds.py — walk-forward folds for Track S, and how many of them count.
Plan 4 §3.3, Plan 3 step 6S.1, configs/scan.yml `folds`.

TWO DESIGNS, BECAUSE THEY ANSWER DIFFERENT QUESTIONS.

  sequential   anchored expanding windows: training always starts at
               `train_start`, the test window advances `step_years` at a time.
               "Would this have worked if deployed in real time" — the owner's
               question, and the one that matters for deployment.
  cpcv         combinatorial purged cross-validation: the sessions are cut
               into `n_groups` contiguous blocks and every choice of
               `k_test_groups` blocks is a test set, the rest training. Many
               more paths, which is what a stable PBO estimate needs.

A FOLD COUNT IS NOT AN EVIDENCE COUNT. Consecutive anchored folds share almost
all their training data and overlapping test windows share test data, so 16
folds with 2-year tests stepped by 1 year are about 8 independent tests; CPCV's
120 paths over 16 groups test each session in 15 of them and carry 16
groups' worth of evidence. `effective` is reported beside `nominal` on every
fold set, and the scan refuses a single-fold design (Plan 4 §10a.3).

LEAKAGE CONTROL. A label at session t uses returns through t + horizon, so a
training label near a test block can see test-block prices:
  embargo  sessions dropped from training AFTER each test block (and, in the
           sequential design, between train end and test start)
  purge    sessions dropped from training BEFORE each test block
Both are in SESSIONS — the trading calendar — never calendar days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import combinations

import numpy as np


@dataclass(frozen=True)
class Fold:
    name: str
    train: np.ndarray      # session indices
    test: np.ndarray       # session indices

    @property
    def span(self) -> tuple[int, int, int, int]:
        return (int(self.train.min()), int(self.train.max()),
                int(self.test.min()), int(self.test.max()))


@dataclass(frozen=True)
class FoldSet:
    design: str
    folds: list[Fold]
    nominal: int
    effective: float
    note: str


def _idx(sessions: list[date], d: date) -> int:
    """First session on or after `d`."""
    return int(np.searchsorted(np.array(sessions, dtype="datetime64[D]"), np.datetime64(d)))


def sequential(sessions: list[date], train_start: date, first_test_start: date,
               test_years: int, step_years: int, embargo_sessions: int,
               end: date | None = None) -> FoldSet:
    """Anchored expanding walk-forward, test windows of `test_years` stepping
    `step_years`, inside [train_start, end]. A test window that would run past
    `end` (or the data) is truncated only if at least half of it fits, else
    dropped — a 3-month 'two-year' test is not one."""
    end = end or sessions[-1]
    stop = _idx(sessions, end) if end < sessions[-1] else len(sessions) - 1
    if end < sessions[-1] and sessions[stop] > end:
        stop -= 1
    t0 = _idx(sessions, train_start)
    folds = []
    start = first_test_start
    while True:
        a = _idx(sessions, start)
        if a > stop:
            break
        b_date = date(start.year + test_years, start.month, start.day)
        b = min(_idx(sessions, b_date) - 1, stop)
        # "At least half" in CALENDAR time: measured in available sessions, a
        # window past the data's end would always look complete.
        if (sessions[b] - sessions[a]).days < (b_date - start).days / 2:
            break
        train_end = a - embargo_sessions - 1
        if train_end <= t0:
            raise ValueError(f"fold at {start}: the embargo leaves no training data")
        folds.append(Fold(f"seq_{start:%Y}", np.arange(t0, train_end + 1), np.arange(a, b + 1)))
        start = date(start.year + step_years, start.month, start.day)
    if len(folds) < 2:
        raise ValueError(f"{len(folds)} sequential fold(s): a single fold is an in-sample fit, refused")
    # Independent tests = test sessions covered / one test window's length.
    covered = len(np.unique(np.concatenate([f.test for f in folds])))
    eff = covered / float(np.mean([len(f.test) for f in folds]))
    shared = (f"consecutive folds share {test_years - step_years}/{test_years} of their test window"
              if step_years < test_years else "test windows are disjoint")
    return FoldSet("sequential", folds, len(folds), round(eff, 2),
                   f"{len(folds)} folds, ~{eff:.1f} independent: {shared}; training is anchored, "
                   "so consecutive folds share nearly all of it")


def cpcv(n_sessions: int, n_groups: int, k_test_groups: int,
         purge_sessions: int, embargo_sessions: int, start: int = 0) -> FoldSet:
    """Every choice of `k_test_groups` of `n_groups` contiguous blocks over
    sessions [start, start + n_sessions) as the test set; training is the rest
    minus `purge_sessions` before and `embargo_sessions` after each test block."""
    if k_test_groups >= n_groups:
        raise ValueError("k_test_groups must be smaller than n_groups")
    edges = np.linspace(start, start + n_sessions, n_groups + 1).round().astype(int)
    groups = [np.arange(edges[i], edges[i + 1]) for i in range(n_groups)]
    all_idx = np.arange(start, start + n_sessions)
    folds = []
    for combo in combinations(range(n_groups), k_test_groups):
        test = np.concatenate([groups[g] for g in combo])
        drop = np.zeros(start + n_sessions, dtype=bool)
        for g in combo:
            lo, hi = groups[g][0], groups[g][-1]
            drop[max(start, lo - purge_sessions): hi + embargo_sessions + 1] = True
        train = all_idx[~drop[start:]]
        folds.append(Fold("cpcv_" + "_".join(str(g) for g in combo), train, test))
    return FoldSet("cpcv", folds, len(folds), float(n_groups),
                   f"{len(folds)} paths over {n_groups} groups: each group is tested in "
                   f"{len(folds) * k_test_groups // n_groups} paths, so the evidence is {n_groups} groups' worth")


def from_config(sessions: list[date], end: date | None = None) -> dict[str, FoldSet]:
    """Both designs from configs/scan.yml, optionally cut at `end` (the explore
    boundary, for development runs that must not touch confirmation data)."""
    import yaml

    from src.common.paths import CONFIGS
    f = yaml.safe_load((CONFIGS / "scan.yml").read_text())["folds"]
    s, c = f["sequential"], f["cpcv"]
    seq = sequential(sessions, date.fromisoformat(s["train_start"]),
                     date.fromisoformat(s["first_test_start"]), int(s["test_years"]),
                     int(s["step_years"]), int(s["embargo_sessions"]), end)
    a = _idx(sessions, date.fromisoformat(s["train_start"]))
    b = (_idx(sessions, end) if end and end < sessions[-1] else len(sessions))
    cp = cpcv(b - a, int(c["n_groups"]), int(c["k_test_groups"]),
              int(c["purge_sessions"]), int(c["embargo_sessions"]), start=a)
    return {"sequential": seq, "cpcv": cp}


def confirm(sessions: list[date]) -> FoldSet:
    """The registered CONFIRM design (scan.yml folds.confirm): disjoint yearly
    test windows from 2016, anchored training — every fold independent."""
    import yaml

    from src.common.paths import CONFIGS
    c = yaml.safe_load((CONFIGS / "scan.yml").read_text())["folds"]["confirm"]
    return sequential(sessions, date.fromisoformat(c["train_start"]),
                      date.fromisoformat(c["first_test_start"]), int(c["test_years"]),
                      int(c["step_years"]), int(c["embargo_sessions"]))
