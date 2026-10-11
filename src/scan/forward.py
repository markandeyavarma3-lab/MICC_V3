"""forward.py — exp_006: does the factor-neutral residual of a wide search
persist on sessions nobody had seen when it was frozen?

The design (docs/plan/EXP006_FORWARD_RESIDUAL_DRAFT.md, decision 0086 (b)):

  1. SELECT, once, at registration: on the CONFIRM grid exp_005 ran
     (2005-01-03 .. 2026-10-01), every candidate's partial rank IC net of
     exp_005's attribution factors (hi_252, downvol_126), averaged over every
     block; the 100 with the largest |mean|, each in its training sign. The 100
     keys and signs are hashed into the registered spec. Their means are never
     stored or printed: the in-sample mean of a set selected on the same blocks
     is selection, not information (0035).
  2. SCORE, only forward: signal dates from FIRST_ENTRY on — the 22nd session
     after the grid's last (21 sessions of forward return + the one-session
     gap), so no scored return overlaps anything the selection saw — in
     consecutive 21-session blocks, each block's value the mean over the 100 of
     its block partial IC, exactly as exp_005 scored a candidate.
  3. READ, once, when READ_AFTER_BLOCKS complete blocks exist. Until then only
     `health()` runs, and it reports counts, never an IC.

    RESEARCH_ENV=prod .venv/bin/python -m src.scan.forward --health
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.scan import atlas as A  # noqa: E402
from src.scan import confirm  # noqa: E402
from src.scan import signals as S  # noqa: E402

EXPERIMENT_ID = "exp_006_forward_residual"
ENGINE_ID = "ENGINE_S_SCAN"
FAMILY = "TRACK_S_PROCEDURE"
TRAIN_END = date(2026, 10, 1)            # the CONFIRM grid's last session
TOP_N = 100
FIRST_ENTRY_OFFSET = 22                  # sessions after TRAIN_END: 21 of forward return + 1 gap
# The bar (2026-10-11): one-sided, because the selection freezes each sign;
# Šidák over the four procedure tests TRACK_S_PROCEDURE now holds (exp_005's
# three N and this), the family rule. alpha = 1 - 0.95^(1/4) = 0.01274.
T_BAR = 2.234
# Blocks for 80% power at that bar: ((2.234 + 0.842) x 0.0727 / 0.0283)^2 x 1.54
# (scripts/exp006_power.py's top-100 SD and inflation, 0089's corrected effect).
READ_AFTER_BLOCKS = 96
MIN_BLOCKS_WITH_NAMES = 80               # kill 1: fewer complete blocks with >= 100 names -> UNDERPOWERED
MAX_LOST_CANDIDATES = 0.20               # kill 2: share of the 100 that can no longer be computed
MIN_EFFECT = 0.015                       # half of exp_005's recorded partial test IC
NULL_REPS, NULL_SEED = 1000, 20261011
# Calendar days of history loaded before FIRST_ENTRY. The longest base signals
# reach five years back (hs_last5y, hs_years2to5: 5 x 252 + 21 sessions) and
# tom_36m averages 36 months; with less, a signal is either undefined (and J_t,
# which needs every signal, empties) or computed on fewer years than exp_005's
# full-history panel gave it — a different statistic. Seven years covers both.
LOOKBACK_DAYS = 2600


def first_entry(sessions: list[date]) -> date | None:
    """The first scored signal date: the FIRST_ENTRY_OFFSET-th observed session
    after TRAIN_END, or None while it has not happened."""
    after = [d for d in sessions if d > TRAIN_END]
    return after[FIRST_ENTRY_OFFSET - 1] if len(after) >= FIRST_ENTRY_OFFSET else None


def parse_key(key: str) -> tuple[tuple[str, int], ...]:
    """'+hi_252|-downvol_126' -> (('hi_252', 1), ('downvol_126', -1)), atlas.run's format."""
    return tuple((p[1:], 1 if p[0] == "+" else -1) for p in key.split("|"))


def _key(c: tuple[tuple[str, int], ...]) -> str:
    return "|".join(f"{'+' if sg > 0 else '-'}{i}" for i, sg in c)


def top_by_abs(mean: np.ndarray, n: int) -> np.ndarray:
    """Indices of the n largest |mean|, largest first; NaN never selected.
    Ties break on the lower index, so the selection is deterministic."""
    m = np.abs(np.asarray(mean, dtype=np.float64))
    m[~np.isfinite(m)] = -1.0                    # after abs: a NaN must rank last, not as |-1|
    return np.lexsort((np.arange(len(m)), -m))[:n]


def select(env: str | None = None) -> tuple[list[dict], dict]:
    """The frozen selection, [{rank, key, sign}] for the TOP_N, and the grid
    manifest it was computed on.

    The partial IC is computed in memory from the panel (Atlas.partial_all reads
    no shards), on the CONFIRM window and scoring exp_005 used. Its OWN
    directory holds the manifest — prices, universe and deal arrays hashed — so
    the selection names the exact data it came from, and a re-run on different
    data is refused rather than silently giving another 100. (The 2026-10-03
    and 0088 CONFIRM directories predate the price hash and cannot be checked.)"""
    import yaml

    from src.common.paths import CONFIGS, warehouse_dir
    from src.scan import panel
    cfg = yaml.safe_load((CONFIGS / "scan.yml").read_text())
    h, depth = int(cfg["signals"]["primary_horizon_sessions"]), int(cfg["signals"]["max_depth"])
    at = A.Atlas(panel.load(env, end=TRAIN_END), warehouse_dir(env) / "scan" / f"exp006_selection_h{h}_d{depth}",
                 horizon=h, depth=depth)
    at._check_manifest("")
    manifest = at.manifest("")
    bic = at.partial_all(list(confirm.ATTRIBUTION_FACTORS))
    mean = bic.mean_over(np.arange(bic.shape[0]))
    sel = top_by_abs(mean, TOP_N)
    want = {int(i): r for r, i in enumerate(sel)}
    out: list[dict | None] = [None] * len(sel)
    for i, c in enumerate(S.combinations_of(at.ids, depth)):
        if i in want:
            out[want[i]] = {"rank": want[i] + 1, "key": _key(c), "sign": int(np.sign(mean[i]))}
    if any(o is None for o in out):
        raise RuntimeError("a selected index fell outside the canonical enumeration")
    return out, manifest  # type: ignore[return-value]


@dataclass
class Forward:
    first: date | None
    dates: list[date]
    block_ic: np.ndarray            # (blocks,) mean over the selection of each block's partial IC
    names_min: np.ndarray           # (blocks,) fewest universe names on any date of the block
    computable: np.ndarray          # (TOP_N,) candidate had a finite IC in the last complete block


def score(selection: list[dict], env: str | None = None, end: date | None = None) -> Forward:
    """The forward block series. Signal dates before FIRST_ENTRY are never scored;
    a block counts only when every one of its 21 forward windows has closed."""
    import yaml

    from src.common.paths import CONFIGS, warehouse_dir
    from src.scan import fastic, panel

    cfg = yaml.safe_load((CONFIGS / "scan.yml").read_text())
    h, depth = int(cfg["signals"]["primary_horizon_sessions"]), int(cfg["signals"]["max_depth"])
    probe = panel.load(env, start=TRAIN_END + timedelta(days=1), end=end)
    first = first_entry(list(probe.dates))
    empty = Forward(first, [], np.array([]), np.array([]), np.zeros(len(selection), dtype=bool))
    if first is None:
        return empty
    p = panel.load(env, start=first - timedelta(days=LOOKBACK_DAYS), end=end)
    at = A.Atlas(p, warehouse_dir(env) / "scan" / "forward_unused", horizon=h, depth=depth)
    mo = at.prepare()
    cands = [parse_key(s["key"]) for s in selection]
    signs_sel = np.array([s["sign"] for s in selection], dtype=np.float64)
    F = np.array([at.pos[f] for f in confirm.ATTRIBUTION_FACTORS])
    daily = np.full((len(at.p.dates), len(cands)), np.nan)
    for d in sorted({len(c) for c in cands}):
        cols = [j for j, c in enumerate(cands) if len(c) == d]
        idx = np.array([[at.pos[i] for i, _ in cands[j]] for j in cols], dtype=np.int64)
        sg = np.array([[s for _, s in cands[j]] for j in cols], dtype=np.float64)
        daily[:, cols] = fastic.batch_partial_ic(mo, idx, sg, F)
    daily *= signs_sel[None, :]                 # each candidate read in its training sign
    t0 = list(at.p.dates).index(first)
    T = len(at.p.dates)
    # A forward window closes at t + gap + h; a block counts only when its last date's has.
    last_closed = T - 1 - (at.gap + h)
    n_blocks = max(0, (last_closed - t0 + 1) // A.BLOCK)
    if n_blocks == 0:
        return Forward(first, list(at.p.dates[t0:]), np.array([]), np.array([]), empty.computable)
    seg = daily[t0:t0 + n_blocks * A.BLOCK]
    sums, counts = fastic.block_sums(seg, A.BLOCK)
    per_cand = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)      # (blocks, TOP_N)
    with np.errstate(invalid="ignore"):
        block_ic = np.nanmean(per_cand, axis=1)
    names = at.p.universe[t0:t0 + n_blocks * A.BLOCK].sum(axis=1).reshape(n_blocks, A.BLOCK).min(axis=1)
    return Forward(first, list(at.p.dates[t0:t0 + n_blocks * A.BLOCK]), block_ic, names,
                   np.isfinite(per_cand[-1]))


def registered_selection(configuration_json: str) -> list[dict]:
    """The frozen 100, as the registry stores them (a hashed spec field)."""
    from src.governance.registration import EXTRA_KEY
    return json.loads(json.loads(configuration_json)[EXTRA_KEY]["selection"])


def health(fw: Forward) -> dict:
    """What the yearly check may see: counts and data health. Never an IC."""
    return {"first_entry": fw.first.isoformat() if fw.first else None,
            "complete_blocks": int(len(fw.block_ic)),
            "blocks_with_100_names": int((fw.names_min >= 100).sum()) if len(fw.names_min) else 0,
            "fewest_names_in_a_block": int(fw.names_min.min()) if len(fw.names_min) else None,
            "candidates_computable": int(fw.computable.sum()),
            "read_due_at_blocks": READ_AFTER_BLOCKS}


def decide(block_ic: np.ndarray, names_min: np.ndarray, computable: np.ndarray, t_bar: float) -> dict:
    """The one read. Pure: the frozen arithmetic, testable on synthetic series."""
    x = np.asarray(block_ic, dtype=np.float64)
    x = x[np.isfinite(x)]
    if int((np.asarray(names_min) >= 100).sum()) < MIN_BLOCKS_WITH_NAMES:
        return {"verdict": "UNDERPOWERED", "reason": "fewer than 50 complete blocks with >= 100 names"}
    if 1 - computable.mean() > MAX_LOST_CANDIDATES:
        return {"verdict": "UNREADABLE", "reason": "more than 20% of the selection cannot be computed forward"}
    n, mean, sd = len(x), float(x.mean()), float(x.std(ddof=1))
    r = float(np.corrcoef(x[:-1], x[1:])[0, 1]) if n > 2 else 0.0
    infl = max(1.0, (1 + r) / (1 - r))
    t = mean / (sd / np.sqrt(n) * np.sqrt(infl))
    rng = np.random.default_rng(NULL_SEED)
    null = np.array([(x * rng.choice([-1.0, 1.0], n)).mean() for _ in range(NULL_REPS)])
    p_flip = float((null >= mean).mean())
    passed = bool(t >= t_bar and mean >= MIN_EFFECT)
    return {"verdict": "PERSISTS" if passed else ("SIGNIFICANT_BUT_SMALL" if t >= t_bar else "DOES_NOT_PERSIST"),
            "blocks": n, "mean_block_ic": mean, "t": float(t), "lag1_r": r, "inflation": infl,
            "p_sign_flip": p_flip, "t_bar": t_bar, "min_effect": MIN_EFFECT}


def main() -> int:
    import argparse

    from src.common.paths import governance_db
    ap = argparse.ArgumentParser()
    ap.add_argument("--health", action="store_true", help="counts and data health only; never an IC")
    a = ap.parse_args()
    if not a.health:
        print("  Only --health exists before the read. The read is one, after "
              f"{READ_AFTER_BLOCKS} complete forward blocks, and is not run from here.")
        return 1
    import sqlite3
    con = sqlite3.connect(f"file:{governance_db(None)}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT configuration_json FROM experiment_registry WHERE experiment_id = ?",
                          (EXPERIMENT_ID,)).fetchone()
    finally:
        con.close()
    if not row:
        print(f"  {EXPERIMENT_ID} is not registered; nothing to check.")
        return 1
    selection = registered_selection(row[0])
    print(json.dumps(health(score(selection)), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
