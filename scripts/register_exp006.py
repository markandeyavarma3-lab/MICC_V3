"""Pre-register exp_006 — does the factor-neutral residual of a wide search
persist on sessions nobody had seen? (Track S, forward.)

The draft is docs/plan/EXP006_FORWARD_RESIDUAL_DRAFT.md (decision 0086 (b));
this is it made machine-readable through src/governance/registration.py. The
selection — 100 keys and signs from the CONFIRM grid to 2026-10-01 — is
computed here and hashed into the spec; nothing forward of 2026-10-01 is read.

REGISTERING IS TYPED, NEVER DEFAULTED (the exp_004 lesson, 2026-10-08):

    RESEARCH_ENV=prod .venv/bin/python scripts/register_exp006.py              # check only
    RESEARCH_ENV=prod .venv/bin/python scripts/register_exp006.py --rehearse   # a throwaway copy
    RESEARCH_ENV=prod .venv/bin/python scripts/register_exp006.py --register   # the real registry

It must run before the first entry session (the 22nd session after
2026-10-01, about 2026-11-03).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.hashing import spec_hash  # noqa: E402
from src.common.paths import governance_db  # noqa: E402
from src.governance import registration as reg  # noqa: E402
from src.research import families  # noqa: E402
from src.scan import confirm  # noqa: E402
from src.scan import forward as F  # noqa: E402

EXPLORATION = {
    "exp_005_partial_attribution": {"years_positive": "10 of 11 CONFIRM years", "q": 0.009,
                                    "test_ic": {"1": 0.0267, "10": 0.0290, "100": 0.0296},
                                    "decision": "0085; could not count, the ladder put the primary first"},
    "exp_005_remeasured_0089": {"top100_years_positive": "10 of 11", "q": 0.012, "test_ic_100": 0.0283},
    "power_exp006": {"script": "scripts/exp006_power.py", "top100": {"sd_block_ic": 0.0727, "lag1_r": 0.21,
                     "inflation": 1.54, "blocks_needed": 57, "blocks_needed_at_0.0283": 62}},
}


def build_spec(selection: list[dict], grid: dict) -> dict:
    sel_json = json.dumps(selection, sort_keys=True, separators=(",", ":"))
    return {
        "hypothesis":
            "The factor-neutral residual of a wide search persists: the 100 signal combinations with the "
            "largest mean partial rank IC (net of hi_252 and downvol_126) over the whole CONFIRM grid to "
            f"{F.TRAIN_END}, each read in its training sign, have a mean block partial IC above zero on "
            "forward sessions that did not exist when they were selected.",
        "prior_belief":
            "Weak, stated before any forward session exists. exp_005's factor-neutral selections were positive "
            "in 10 of 11 CONFIRM years (q 0.009; 0.012 re-measured on corrected prices, 0089), but effects found "
            "by search decay, and exp_005's plain IC halved after 2016. UNDERPOWERED at the read, or a pass at "
            "the margin, are both likely.",
        "data_version":
            "price_spine_adj, institutional_deals_clean (PROP_HFT and same-day round trips excluded), the "
            "point-in-time top 500 (seed pit_universe to 2026-10-01, then src/warehouse/pit_universe.py's "
            "month-end rebalances by the seed's own rule) as of the registration commit and as they extend.",
        "universe_definition":
            "J_t, decision 0084: names in the point-in-time top 500 with a forward return and every base signal "
            "defined; fewer than 100 names = no IC that date.",
        "signal_definition":
            f"The {F.TOP_N} combinations in `selection`, frozen: each the mean of signed percentile ranks of its "
            "base signals (src/scan/signals.py at the registration commit), read in its training sign.",
        "selection":
            sel_json,
        "selection_sha256":
            hashlib.sha256(sel_json.encode()).hexdigest(),
        "interpretation_mode": "PROCEDURE",
        "holding_period": "forward 21 sessions after a one-session gap (t+2 .. t+22), as exp_005",
        "entry_policy":
            f"signal dates from the first entry session: the {F.FIRST_ENTRY_OFFSET}th observed session after "
            f"{F.TRAIN_END} (21 sessions of forward return plus the gap), so no scored return overlaps the "
            "selection's data; consecutive 21-session blocks from there",
        "exit_policy": "close of t+22; a block counts only when all 21 of its forward windows have closed",
        "cost_policy":
            "the top/bottom 20% long-short book on the 100, pessimistic costs.yml level, monthly; REPORTED, "
            "never tested",
        "benchmark_policy": "none: the rank IC is cross-sectional and market-neutral by construction (0021)",
        "training_period":
            f"2005-01-03 .. {F.TRAIN_END}, the CONFIRM window and scoring exp_005 ran, on the corrected spine "
            f"(0088). Grid manifest: {json.dumps({k: grid[k] for k in ('first', 'last', 'sessions', 'securities', 'ids_hash', 'prices_hash', 'candidates', 'base_ids_hash')}, sort_keys=True)}",
        "validation_period": "none",
        "final_test_period":
            f"forward only, from the first entry session; ONE read when {F.READ_AFTER_BLOCKS} complete blocks "
            "exist (about 2034). No interim look decides anything; a yearly health check reports block "
            "count and data health and never an IC (src/scan/forward.py --health)",
        "search_space_definition":
            "none at test time: the selection is frozen in this spec. It came from the same grid and scoring "
            "as exp_005 (1,929,213 candidates, decision 0084)",
        "test_count": 1,
        "multiple_testing_policy":
            f"one test in {F.FAMILY}, its fourth (exp_005's three N are concluded). One-sided Sidak over the "
            f"four: alpha 1 - 0.95^(1/4) = 0.0127, t >= {F.T_BAR}. One-sided because every selected sign is "
            "frozen; Sidak because the family's rule is that each test raises the bar",
        "permutation_policy":
            f"block sign flips of the forward block series, {F.NULL_REPS} reps, seed {F.NULL_SEED}; reported "
            "beside the t, not the decision",
        "pass_bar":
            f"PERSISTS if t >= {F.T_BAR} (one-sided, mean block IC over its AR(1)-inflated SE) AND mean block IC "
            f">= {F.MIN_EFFECT} (half of exp_005's recorded test IC). t above the bar with a smaller mean is "
            "SIGNIFICANT_BUT_SMALL, reported and not passed. Otherwise DOES_NOT_PERSIST.",
        "kill_criteria":
            f"(1) fewer than {F.MIN_BLOCKS_WITH_NAMES} complete forward blocks with >= 100 names at the read -> "
            f"UNDERPOWERED, unread. (2) more than {F.MAX_LOST_CANDIDATES:.0%} of the 100 not computable in the "
            "last complete block (a base signal's source retired) -> UNREADABLE.",
        "confounds":
            "momentum and low volatility CONTROLLED (the statistic is net of both); bid-ask bounce APPLICABLE "
            "(one-session gap); survivorship CONTROLLED (point-in-time universe, extended monthly); look-ahead "
            "CONTROLLED (forward sessions only); industry NOT CONTROLLED (sector_history is Phase 3).",
        "exploratory_prior_run": json.dumps(EXPLORATION),
        "trial_family": F.FAMILY,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rehearse", action="store_true",
                    help="register into a throwaway COPY of the governance db, verify, delete it")
    ap.add_argument("--register", action="store_true",
                    help="write the REAL registry. Without it (and without --rehearse) nothing is written")
    ap.add_argument("--show", type=Path, default=None, help="also write the frozen selection to this file")
    args = ap.parse_args()
    if date.today() >= date(2026, 11, 3) and args.register:
        print("  CHECK: past ~2026-11-03 the first entry session may already exist; confirm it has not before "
              "registering (src/scan/forward.first_entry).")
    dirty = reg.dirty_code()
    if dirty and args.register:
        print("  REFUSED: uncommitted code or config — code_commit_hash would name other code:")
        print("\n".join(f"    {d}" for d in dirty))
        return 1
    print("  selecting the frozen 100 on the CONFIRM grid (minutes)...")
    selection, grid = F.select()
    spec = build_spec(selection, grid)
    print(f"  grid prices_hash : {grid['prices_hash']} ({grid['sessions']} sessions, {grid['candidates']:,} candidates)")
    print(f"  selection_sha256 : {spec['selection_sha256']}")
    print("  depths           : " + ", ".join(f"{d}: {sum(1 for s in selection if s['key'].count('|') + 1 == d)}"
                                               for d in (1, 2, 3)))
    if args.show:
        args.show.write_text(json.dumps(selection, indent=1))
        print(f"  selection written to {args.show}")
    if not (args.register or args.rehearse):
        print("  CHECK ONLY: nothing written. --rehearse to rehearse on a copy, --register to register.")
        return 0
    real = governance_db(None)
    target = real
    if args.rehearse:
        target = Path(tempfile.mkdtemp(prefix="exp006_rehearsal_")) / real.name
        shutil.copy2(real, target)
        print(f"  REHEARSAL on a copy: {target}")
        if dirty:
            print(f"  ({len(dirty)} uncommitted code/config path(s) — the real run would refuse here)")
    con = sqlite3.connect(str(target))
    try:
        sh = reg.register(con, F.EXPERIMENT_ID, F.ENGINE_ID, spec,
                          {"family": F.FAMILY, "decision": "0090", "top_n": F.TOP_N,
                           "attribution_factors": list(confirm.ATTRIBUTION_FACTORS),
                           "read_after_blocks": F.READ_AFTER_BLOCKS, "t_bar": F.T_BAR},
                          reg.head(), families.persisted_counter(F.FAMILY),
                          "Markandeya Varma (owner) / Claude Opus 5.5")
    except RuntimeError as e:
        print(f"  REFUSED: {e}")
        return 1
    finally:
        con.close()
        if args.rehearse:
            shutil.rmtree(target.parent, ignore_errors=True)
    assert sh == spec_hash(spec)
    print(f"  experiment_id    : {F.EXPERIMENT_ID}\n  spec_hash        : {sh}\n  family           : {F.FAMILY}")
    print(f"  stored fields    : {len(spec)} — the stored row reproduces the hash")
    print("  status           : " + ("REHEARSED — nothing registered" if args.rehearse
                                     else "REGISTERED — no forward session scored"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
