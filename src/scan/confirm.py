"""confirm.py — exp_005: does searching work on 2016+? The registered run.
Plan 4 §4 and §9; decision 0085; draft docs/plan/EXP005_SCAN_PROCEDURE_REGISTRATION_DRAFT.md.

Everything here is fixed before the run, and `run()` refuses to start
unless exp_005 is REGISTERED (the same guard as exp_004's panel).

  primary      the procedure hit rate of the top-N training selection (N in
               scan.yml top_n), over the CONFIRM folds (disjoint yearly test
               windows 2016+), against the block-sign-flip null; one-sided,
               Benjamini-Hochberg across the three N at FDR_ALPHA.
  attribution  the same procedure on the PARTIAL IC net of the two factors
               exploration found the search selecting (ATTRIBUTION_FACTORS).
  costs        every fold's selected set as long-short books (portfolio.py),
               pessimistic costs; the mean net spread per fold.

VERDICT, in this order:
  NO_SEARCH_SKILL               no N passes the primary
  REDISCOVERS_KNOWN_FACTORS     the primary passes, the partial procedure does not
  SIGNIFICANT_BUT_UNPROFITABLE  both pass, the mean net spread is <= 0
  SEARCH_FINDS_NEW_EDGE         all three pass
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import numpy as np

from src.common.paths import governance_db
from src.scan import atlas as A
from src.scan import portfolio, procedure
from src.scan.folds import FoldSet

EXPERIMENT_ID = "exp_005_scan_procedure"
FAMILY = "TRACK_S_PROCEDURE"
ENGINE_ID = "ENGINE_S_SCAN"
ATTRIBUTION_FACTORS = ("hi_252", "downvol_126")
FDR_ALPHA = 0.05
NULL_REPS = 1000
QUANTILE = 0.2


def registered_hash(env: str | None = None) -> str:
    con = sqlite3.connect(str(governance_db(env)))
    try:
        row = con.execute("SELECT spec_hash, status FROM experiment_registry WHERE experiment_id = ?",
                          (EXPERIMENT_ID,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        con.close()
    if not row or row[1] != "REGISTERED":
        raise RuntimeError(f"{EXPERIMENT_ID} is not REGISTERED (found {row}); the CONFIRM run reads "
                           "2016+ and MUST NOT run before scripts/register_exp005.py froze the spec")
    return row[0]


def bh(ps: list[float]) -> list[float]:
    """Benjamini-Hochberg q-values."""
    m = len(ps)
    order = np.argsort(ps)
    q = np.empty(m)
    run = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        run = min(run, ps[i] * m / rank)
        q[i] = min(run, 1.0)
    return q.tolist()


@dataclass
class Outcome:
    verdict: str
    primary: list[procedure.ProcedureResult]
    primary_q: list[float]
    partial: list[procedure.ProcedureResult]
    partial_q: list[float]
    pbo: float
    net_per_fold: dict[int, list[float]] = field(default_factory=dict)
    gross_per_fold: dict[int, list[float]] = field(default_factory=dict)
    turnover: dict[int, float] = field(default_factory=dict)


def books_for(at: A.Atlas, bic: A.BlockIC, fs_blocks: FoldSet, fs_sessions: FoldSet,
              keys: list[str], n: int) -> tuple[list[float], list[float], float]:
    """Per fold: the top-n training selection as books over the test window;
    returns (mean gross per fold, mean net per fold, mean turnover)."""
    gross, net, turn = [], [], []
    for fb, fsn in zip(fs_blocks.folds, fs_sessions.folds, strict=True):
        tr = bic.mean_over(fb.train)
        cand = np.where(np.isfinite(tr))[0]
        sel = cand[np.argsort(-np.abs(tr[cand]))][:n]
        g, nt, tv = [], [], []
        for j in sel:
            sign = float(np.sign(tr[j]))
            comps = [(c[1:], 1.0 if c[0] == "+" else -1.0) for c in keys[j].split("|")]
            b = portfolio.book(at.stack, at._mo.ok, at.fwd_c, at.slots, at.adv_c, at.vol_c, at.p.dates,
                               [at.pos[i] for i, _ in comps], [s * sign for _, s in comps],
                               fsn.test, rebalance=at.h, quantile=QUANTILE)
            if len(b.gross):
                g.append(float(b.gross.mean()))
                nt.append(float(b.net.mean()))
                tv.append(float(b.turnover[1:].mean()) if len(b.turnover) > 1 else 1.0)
        gross.append(float(np.mean(g)) if g else float("nan"))
        net.append(float(np.mean(nt)) if nt else float("nan"))
        turn.append(float(np.mean(tv)) if tv else float("nan"))
    return gross, net, float(np.nanmean(turn))


def evaluate(at: A.Atlas, bic: A.BlockIC, keys: list[str], fs_sessions: FoldSet,
             top_n: list[int], reps: int = NULL_REPS) -> Outcome:
    """The whole registered analysis on a prepared atlas. Pure given its
    inputs — the rehearsal runs it on EXPLORE folds, the registered run on
    CONFIRM folds, and nothing else differs."""
    fb = A.block_folds(fs_sessions)
    prim, pbo = procedure.run(bic, fb, fb, top_n, reps)
    pq = bh([r.p_vs_null for r in prim])
    pbic = at.partial_all(list(ATTRIBUTION_FACTORS))
    part, _ = procedure.run(pbic, fb, fb, top_n, reps)
    aq = bh([r.p_vs_null for r in part])
    gross, net, turn = {}, {}, {}
    for n in top_n:
        g, nt, tv = books_for(at, bic, fb, fs_sessions, keys, n)
        gross[n], net[n], turn[n] = g, nt, tv
    return Outcome(decide(top_n, pq, aq, net), prim, pq, part, aq, pbo, net, gross, turn)


def decide(top_n: list[int], primary_q: list[float], partial_q: list[float],
           net: dict[int, list[float]]) -> str:
    """The verdict ladder in the module docstring. An N counts only if it
    passes BOTH the primary and the attribution, and is profitable net."""
    passed = {n for n, q in zip(top_n, primary_q, strict=True) if q < FDR_ALPHA}
    both = passed & {n for n, q in zip(top_n, partial_q, strict=True) if q < FDR_ALPHA}
    if not passed:
        return "NO_SEARCH_SKILL"
    if not both:
        return "REDISCOVERS_KNOWN_FACTORS"
    if all(np.nanmean(net[n]) <= 0 for n in both):
        return "SIGNIFICANT_BUT_UNPROFITABLE"
    return "SEARCH_FINDS_NEW_EDGE"


def render(o: Outcome, title: str, note: str, fs: FoldSet) -> str:
    L = [f"# {title}", "", note, "",
         f"**Verdict: {o.verdict}**", "",
         f"Folds: {fs.note}. PBO over the folds: {o.pbo:.2f}.", "",
         "## Primary — the search procedure, plain IC", "",
         "| top N | hit rate | null mean | p | q (BH) | train IC | test IC | degradation | rank decay |",
         "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r, q in zip(o.primary, o.primary_q, strict=True):
        L.append(f"| {r.top_n} | **{r.hit_rate:.2f}** | {r.null_hit_rates.mean():.2f} | {r.p_vs_null:.3f} | "
                 f"{q:.3f} | {r.mean_train_ic:+.4f} | {r.mean_test_ic:+.4f} | {r.degradation:+.4f} | "
                 f"{r.rank_decay:+.3f} |")
    L += ["", f"## Attribution — partial IC net of {', '.join(ATTRIBUTION_FACTORS)}", "",
          "| top N | hit rate | null mean | p | q (BH) | train IC | test IC |", "|---:|---:|---:|---:|---:|---:|---:|"]
    for r, q in zip(o.partial, o.partial_q, strict=True):
        L.append(f"| {r.top_n} | **{r.hit_rate:.2f}** | {r.null_hit_rates.mean():.2f} | {r.p_vs_null:.3f} | "
                 f"{q:.3f} | {r.mean_train_ic:+.4f} | {r.mean_test_ic:+.4f} |")
    L += ["", "## Costs — selected sets as long-short books, pessimistic level", "",
          "| top N | mean gross / rebalance | mean net / rebalance | folds net > 0 | mean turnover |",
          "|---:|---:|---:|---:|---:|"]
    for n in o.net_per_fold:
        g, nt = np.array(o.gross_per_fold[n]), np.array(o.net_per_fold[n])
        L.append(f"| {n} | {np.nanmean(g):+.2%} | {np.nanmean(nt):+.2%} | "
                 f"{int(np.sum(nt > 0))}/{int(np.sum(np.isfinite(nt)))} | {o.turnover[n]:.0%} |")
    return "\n".join(L) + "\n"
