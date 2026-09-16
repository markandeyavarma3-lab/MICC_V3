"""Pre-register exp_003 — participant-wise OI as a category series. Decision 0067.

REGISTERED BEFORE A SINGLE MEAN IS COMPUTED. `src/research/oi_power.py`
computes dispersion and n only, and it refuses to run without the hash this
writes. The spec below is the table in 0067, verbatim in substance; 0067 is
the human record, this is the machine record, and `spec_hash` binds them.

A PLAIN INSERT, NOT INSERT OR REPLACE. A second registration of the same id
must fail loudly: rewriting a registered spec is the one thing a registry
exists to make impossible. exp_002's script used INSERT OR REPLACE; this one
does not.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.hashing import spec_hash  # noqa: E402
from src.common.paths import governance_db  # noqa: E402
from src.research import families  # noqa: E402

EXPERIMENT_ID = "exp_003_participant_oi_category"
FAMILY = "TRACK_O_POSITIONING"
PRIMARY_HORIZON_SESSIONS = 21
CATEGORIES = ("FII", "DII", "Pro", "Client")
SIGNALS = ("index_fut_net", "stock_fut_net")
HORIZONS_SESSIONS = (1, 2, 3, 5, 10, 21, 63, 126, 252)

SPEC = {
    "hypothesis":
        "The sign of a category's daily net open-interest change on index futures "
        "(primary) or stock futures (secondary) predicts the NIFTY 50's forward "
        "return: sessions in the top tercile of dOI differ from sessions in the "
        "bottom tercile at the primary horizon, per category, after multiplicity. "
        "THIS IS DERIVATIVES POSITIONING, NOT CASH FLOW.",
    "prior_belief":
        "Weak. Positioning data is widely watched; a large persistent index-level "
        "edge visible in a public daily file would be arbitraged. The honest "
        "expectation is an effect below the plausible bound, in which case the "
        "landing is UNDERPOWERED, not a hint.",
    "data_version":
        "participant_oi 2014-01-01..2026-09-15 (15,359 v1_export + 280 "
        "nse_participant_oi, decision 0065); NIFTY 50 close from "
        "seed:global_indices_daily 2007-09-17..2026-07-07; overlap 3,067 sessions",
    "universe_definition":
        "One session x one category. Categories FII, DII, Pro, Client; TOTAL "
        "excluded (the market's sum row, net identically zero). Signal columns "
        "index_fut_net (primary) and stock_fut_net (secondary); options columns "
        "not tested (no stock-option shorts in migration 0004).",
    "participant_definition":
        "A CATEGORY, not a person or fund. 0056 measured that entity-level "
        "attribution is unresearchable; the category series is the unit.",
    "interpretation_mode": "CATEGORY",
    "holding_period":
        "primary 21 sessions; horizons 1,2,3,5,10,21,63,126,252 reported. "
        "research.yml's 12-month primary is a deal-event rule (0034/0038); a "
        "daily positioning series turns over in days, and a 252-session label on "
        "daily observations overlaps 251/252 of every cohort. Declared here, "
        "before measurement, as the one departure from research.yml.",
    "entry_policy": "signal at session t close (file published after close); position at t+1 OPEN",
    "exit_policy": "close of session t+1+h; no same-day close (research.yml timing)",
    "cost_policy":
        "portfolio gate: long-short NIFTY futures sized to costs.yml participation "
        "cap, full statutory + sqrt-impact stack at the pessimistic level",
    "benchmark_policy":
        "NIFTY 50 PRICE index (seed:global_indices_daily, symbol NIFTY50). The "
        "signal is index-level so CHAR_MATCHED has no meaning; the official NIFTY "
        "500 TRI is archived bytes only (INDEX_TRI/, decision pending) and not in "
        "the warehouse. The dividend leg (~1.2pp/yr) is common to both terciles "
        "and cancels in the difference. Swapping to the TRI re-registers.",
    "training_period": "2014-01-01 .. 2019-12-31  (FORMATION: tercile cut-points set here only)",
    "validation_period": "none; the walk-forward split IS the validation",
    "final_test_period": "2020-01-01 .. 2026-07-07  (EVALUATION: touched once)",
    "search_space_definition":
        "ONE specification, no free parameters. Terciles of dOI on the formation "
        "period, held fixed. Estimator = monthly-cohort mean forward NIFTY return "
        "on top-tercile sessions minus bottom-tercile sessions, Bartlett serial "
        "correction with lag covering the label overlap (0033). Expiry sessions "
        "reported separately and excluded from the primary.",
    "test_count": len(CATEGORIES) * len(SIGNALS),
    "multiple_testing_policy":
        f"Benjamini-Hochberg FDR at 5% across {len(CATEGORIES) * len(SIGNALS)} tests "
        f"(4 categories x 2 signal columns x 1 primary horizon), declared here. "
        f"Robustness horizons reported, never tested.",
    "permutation_policy":
        "moving-block bootstrap, block = 21 sessions, 10,000 draws, seed 20260916, "
        "resampling whole months",
    "pass_bar":
        "Event gate: tercile difference at 21 sessions clears the serial-corrected "
        "MDE AND the plausible bound (0.5%/month x horizon months, 0028) at BH-FDR "
        "5%; AND portfolio gate (0003): the long-short position beats the benchmark "
        "net of costs on the evaluation period. Both, not either.",
    "kill_criteria":
        "(1) MDE at 21 sessions > plausible bound for a category -> UNDERPOWERED, "
        "not fitted. (2) Effect survives only above the participation/liquidity "
        "cap. (3) Effect present only at horizons <= 5 sessions and absent at 21 "
        "-> temporary impact, not information.",
    "confounds":
        "momentum APPLICABLE (positioning follows price; momentum-neutral check on "
        "lagged 21s NIFTY return reported); expiry APPLICABLE (dOI spikes "
        "mechanically at monthly expiry; those sessions reported separately and "
        "excluded from the primary); market-relative NOT_APPLICABLE (the outcome IS "
        "the market); size/liquidity tiers NOT_APPLICABLE (one instrument); "
        "delisting NOT_APPLICABLE (an index does not delist); industry "
        "NOT_APPLICABLE.",
    "trial_family": FAMILY,
    "exploratory_prior_run": json.dumps({
        "note": "no forward return was computed before this registration; "
                "src/research/oi_power.py runs AFTER and computes dispersion only",
        "counts_seen": {"overlap_sessions": 3067, "categories": 4, "signals": 2},
    }),
}

EXPERIMENT = {"experiment_id": EXPERIMENT_ID, "engine_id": "ENGINE_O_POSITIONING",
              "status": "REGISTERED", "decision_reason": None}


def main() -> int:
    import sqlite3

    sh = spec_hash(SPEC)
    trials_before = families.persisted_counter(FAMILY)
    row = {**EXPERIMENT, **SPEC, "spec_hash": sh, "created_at": datetime.now(UTC).isoformat(),
           "created_by": "Markandeya Varma (owner) / Claude Opus 5",
           "configuration_json": json.dumps({
               "primary_horizon_sessions": PRIMARY_HORIZON_SESSIONS,
               "horizons_sessions": list(HORIZONS_SESSIONS),
               "categories": list(CATEGORIES), "signals": list(SIGNALS),
               "fdr_alpha": 0.05, "formation_end": "2019-12-31",
               "family": FAMILY, "decision": "0067"}),
           "code_commit_hash": subprocess.run(["git", "rev-parse", "HEAD"],
                                              capture_output=True, text=True).stdout.strip(),
           "trials_before": trials_before}
    con = sqlite3.connect(str(governance_db(None)))
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(experiment_registry)")]
        use = {k: v for k, v in row.items() if k in cols}
        existing = con.execute(
            "SELECT spec_hash FROM experiment_registry WHERE experiment_id = ?", (EXPERIMENT_ID,)
        ).fetchone()
        if existing:
            print(f"  REFUSED: {EXPERIMENT_ID} is already registered with spec_hash "
                  f"{existing[0]}; a registered spec is not rewritten. Register a new id.")
            return 1
        con.execute(
            f"INSERT INTO experiment_registry ({','.join(use)}) VALUES ({','.join('?' * len(use))})",
            list(use.values()))
        con.commit()
    finally:
        con.close()
    print(f"  experiment_id  : {EXPERIMENT_ID}")
    print(f"  spec_hash      : {sh}")
    print(f"  family         : {FAMILY}  trials_before={trials_before}")
    print(f"  test_count     : {SPEC['test_count']}  (declared, not derived)")
    print(f"  status         : REGISTERED — no result computed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
