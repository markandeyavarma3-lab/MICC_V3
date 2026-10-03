"""Pre-register exp_005 — does a wide signal search work on 2016+? (Track S).

The draft is docs/plan/EXP005_SCAN_PROCEDURE_REGISTRATION_DRAFT.md; this is
it made machine-readable, through src/governance/registration.py (every spec
field stored, the stored row must reproduce the hash). Exploration (2005-2015)
has run — docs/reports/SCAN_EXPLORE_H21.md and SCAN_REHEARSAL_EXPLORE_H21.md —
and this freezes the CONFIRM test of 2016+ before any 2016 IC exists.

    RESEARCH_ENV=prod .venv/bin/python scripts/register_exp005.py --rehearse
    RESEARCH_ENV=prod .venv/bin/python scripts/register_exp005.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from src.common.hashing import spec_hash  # noqa: E402
from src.common.paths import CONFIGS, governance_db  # noqa: E402
from src.governance import registration as reg  # noqa: E402
from src.research import families  # noqa: E402
from src.scan import confirm  # noqa: E402
from src.scan import signals as S  # noqa: E402

EXPLORATION = {
    "SCAN_EXPLORE_H21": {"folds": 5, "effective": 3.0, "hit_rate": {1: 1.0, 10: 1.0, 100: 1.0},
                         "p_vs_null": {1: 0.080, 10: 0.100, 100: 0.095}, "test_ic": 0.086,
                         "degradation": 0.0, "rank_decay": 0.80, "pbo": 0.14,
                         "drivers": "hi_252 +0.077, downvol_126 -0.072, ram_252 +0.071; deal signals weakest"},
    "SCAN_REHEARSAL_EXPLORE_H21": {"folds": 6, "effective": 6.0, "design": "disjoint yearly 2010-2015, 1000 reps",
                                   "primary_hit_rate": 1.0, "primary_q": 0.018, "test_ic": 0.095,
                                   "partial_hit_rate": 0.83, "partial_q": 0.110, "partial_test_ic": 0.024,
                                   "net_per_rebalance": 0.0155, "turnover": 0.29,
                                   "verdict": "REDISCOVERS_KNOWN_FACTORS"},
}


def build_spec() -> dict:
    scan = yaml.safe_load((CONFIGS / "scan.yml").read_text())
    n_base = len(S.base_signals())
    depth = int(scan["signals"]["max_depth"])
    width = S.combination_count(n_base, depth)
    top_n = scan["procedure_test"]["top_n"]
    h = int(scan["signals"]["primary_horizon_sessions"])
    c = scan["folds"]["confirm"]
    return {
        "hypothesis":
            f"Selecting the top N of {width:,} signal combinations by their training rank IC picks "
            "combinations whose IC stays positive out of sample: over disjoint yearly test windows "
            "2016 onward, the selected set's test IC is positive in more folds than the block sign-flip "
            f"null allows, for N in {top_n} (Benjamini-Hochberg across the three).",
        "prior_belief":
            "Mixed, and stated before any 2016 IC exists. Exploration (2005-2015, docs/reports/"
            "SCAN_EXPLORE_H21.md): hit rate 5/5 for every N, test IC +0.086, degradation ~0, rank decay "
            "0.80, PBO 0.14, but p 0.08-0.10 on ~3 independent folds; the search selected momentum "
            "(hi_252, risk-adjusted momentum) and low volatility, published 1993-2006. Expectation: the "
            "plain procedure passes, weaker than 2010-2015 as factor investing spread in India after "
            "~2017; the partial (factor-neutral) procedure does not; REDISCOVERS_KNOWN_FACTORS is the "
            "likeliest verdict.",
        "data_version":
            "price_spine_adj, institutional_deals_clean (bulk/block deals, PROP_HFT and same-day round "
            "trips excluded) and seed pit_universe as of the registration commit. NO shareholding (exp_004's "
            "signal) and no insider data. Identity by security (0061).",
        "universe_definition":
            "On each session, J_t (decision 0084): names in the point-in-time top 500 by ADV (monthly "
            "rebalance, seed pit_universe) with a forward return and every base signal defined; fewer than "
            f"{scan['cross_sectional']['min_names_per_date']} names = no IC that date.",
        "signal_definition":
            f"{n_base} base signals in seven families, each with a written mechanism (src/scan/signals.py), "
            f"combined to depth {depth} as the mean of signed percentile ranks on J_t; {width:,} candidates, "
            "counted at run time.",
        "interpretation_mode": "PROCEDURE",
        "holding_period": f"forward {h} sessions after a one-session gap (sessions t+2 .. t+{h + 1}); 5 reported, never tested",
        "entry_policy": "the close of t is the signal; the forward window starts after one skipped session (bid-ask bounce, scan.yml)",
        "exit_policy": f"close of t+1+{h}; a window with any missing return is no observation",
        "cost_policy":
            f"each fold's selected set rebuilt as long-short books (top/bottom {confirm.QUANTILE:.0%} of J_t, "
            f"rebalanced every {h} sessions, Rs 100 crore), pessimistic costs.yml level (statutory round trip + "
            "square-root impact on median ADV20 and 63-session volatility of the names traded)",
        "benchmark_policy": "none: the rank IC is cross-sectional and market-neutral by construction (0021)",
        "training_period": f"anchored expanding from {c['train_start']} to {c['embargo_sessions']} sessions before each test window",
        "validation_period": "none",
        "final_test_period":
            f"disjoint {c['test_years']}-year windows from {c['first_test_start']} to the data end (a final window "
            "counts if at least half of it exists); each fold touched once",
        "search_space_definition":
            f"{width:,} candidates = sum over d<= {depth} of C({n_base}, d) x 2^(d-1); selection by |mean train "
            "IC|, test IC read in the training sign; scoring exactly as decision 0084",
        "test_count": len(top_n),
        "multiple_testing_policy":
            f"Benjamini-Hochberg across the {len(top_n)} values of N at {confirm.FDR_ALPHA:.0%}. The family is "
            "TRACK_S_PROCEDURE (fixed size 3, width does not charge it: one procedure is under test). "
            "No individual pattern is claimed; a pattern claim would pay TRACK_S_SIGNALS' full width.",
        "permutation_policy":
            f"block sign flips, 21-session blocks shared by all candidates, {confirm.NULL_REPS} reps, seed "
            "20261002 (procedure.null_hit_rates); one-sided p = share of null hit rates >= observed",
        "pass_bar":
            f"An N passes if its primary q < {confirm.FDR_ALPHA}. Verdict ladder (confirm.decide): "
            "NO_SEARCH_SKILL (no N passes) / REDISCOVERS_KNOWN_FACTORS (no N passes the partial-IC "
            f"procedure net of {', '.join(confirm.ATTRIBUTION_FACTORS)} as well) / "
            "SIGNIFICANT_BUT_UNPROFITABLE (an N passes both and every such N has mean net spread <= 0) / "
            "SEARCH_FINDS_NEW_EDGE.",
        "kill_criteria":
            "(1) primary within the null -> NO_SEARCH_SKILL. (2) the selected IC vanishes net of momentum "
            "and low volatility -> REDISCOVERS_KNOWN_FACTORS. (3) mean net spread <= 0 at the pessimistic "
            "level -> SIGNIFICANT_BUT_UNPROFITABLE.",
        "confounds":
            "momentum and low volatility APPLICABLE (attribution, kill 2); bid-ask bounce APPLICABLE (one-"
            "session gap); survivorship CONTROLLED (point-in-time universe); prior search of this space "
            "APPLICABLE (exploration ran on 2005-2015 and is reported; the 2016+ data is untouched); "
            "industry NOT CONTROLLED (sector_history is Phase 3).",
        "exploratory_prior_run": json.dumps(EXPLORATION),
        "trial_family": confirm.FAMILY,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rehearse", action="store_true")
    args = ap.parse_args()
    dirty = reg.dirty_code()
    if dirty and not args.rehearse:
        print("  REFUSED: uncommitted code or config — code_commit_hash would name other code:")
        print("\n".join(f"    {d}" for d in dirty))
        return 1
    spec = build_spec()
    real = governance_db(None)
    target = real
    if args.rehearse:
        target = Path(tempfile.mkdtemp(prefix="exp005_rehearsal_")) / real.name
        shutil.copy2(real, target)
        print(f"  REHEARSAL on a copy: {target}")
    con = sqlite3.connect(str(target))
    try:
        sh = reg.register(con, confirm.EXPERIMENT_ID, confirm.ENGINE_ID, spec,
                          {"family": confirm.FAMILY, "decision": "0085",
                           "attribution_factors": list(confirm.ATTRIBUTION_FACTORS),
                           "null_reps": confirm.NULL_REPS, "quantile": confirm.QUANTILE},
                          reg.head(), families.persisted_counter(confirm.FAMILY),
                          "Markandeya Varma (owner) / Claude Opus 5.5")
    except RuntimeError as e:
        print(f"  REFUSED: {e}")
        return 1
    finally:
        con.close()
        if args.rehearse:
            shutil.rmtree(target.parent, ignore_errors=True)
    assert sh == spec_hash(spec)
    print(f"  experiment_id  : {confirm.EXPERIMENT_ID}\n  spec_hash      : {sh}\n  family         : {confirm.FAMILY}")
    print(f"  stored fields  : {len(spec)} — the stored row reproduces the hash")
    print("  status         : " + ("REHEARSED — nothing registered" if args.rehearse else "REGISTERED — no 2016 IC computed"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
