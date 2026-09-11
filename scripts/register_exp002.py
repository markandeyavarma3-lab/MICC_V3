"""Pre-register exp_002 — the entity verdict study. Workstream 3 item 3.

REGISTERED BEFORE A SINGLE OUTCOME IS COMPUTED. Nothing in this file reads a
forward return, and the study code refuses to run without the hash this writes.
The 24 entities and their role classification are already fixed by
src/research/entity_names.py and src/research/roles.py, both of which classify on
names alone and never touch outcomes.
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

EXPERIMENT_ID = "exp_002_entity_persistence"
NOW = datetime.now(UTC).isoformat()
COMMIT = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                        text=True).stdout.strip()

SPEC = {
    "hypothesis":
        "Among named LONG_ONLY institutions disclosing directional bulk/block "
        "deals, a tier formed on 2006-2015 excess returns persists out-of-sample "
        "on 2016-2026, net of the full cost stack.",
    "prior_belief":
        "Weak and closer to negative than positive. 0056 found no participant "
        "supported at FWER 5% under the §6.3 specification, and 0055 found the "
        "deals track's binding constraint is arithmetic rather than method. What "
        "is genuinely new here is the POPULATION: normalisation surfaced 24 "
        "long-only institutions (HDFC, SBI, ICICI Pru, Norges Bank) that "
        "fragmentation had held below the eligibility floor, and role "
        "classification removes the conduits that would have manufactured an "
        "edge. This is the first specification in which the tested names are "
        "plausibly decision-makers, so it deserves one honest run.",
    "data_version": "v1_export 2026-07-10 + spine to 2026-09-10 + collected to 2026-09-10",
    "universe_definition":
        "Directional deals: NOT same_day_round_trip_flag, NOT unresolved_symbol_flag, "
        "NOT uncovered_symbol_flag. 60,775 deals / 19,248 normalised entities.",
    "participant_definition":
        "Counterparty normalised by src/research/entity_names.normalize (case, "
        "punctuation, decorative corporate suffixes; country and numeral tokens "
        "PRESERVED). Eligible: >=30 deals AND >=12 distinct months -> 133 "
        "entities. Tested: role == LONG_ONLY per src/research/roles.classify -> "
        "24 entities, 1,539 deals. ARBITRAGE, ODI_ISSUER, INDEX_VEHICLE and "
        "BANK_EXECUTION are excluded with reasons declared in roles.py BEFORE "
        "any return was computed; UNKNOWN (78 entities) is reported, not tested.",
    "interpretation_mode": "INDIVIDUAL",
    "holding_period": "primary 63 sessions (3 months); all 9 horizons reported",
    "entry_policy": "next-session OPEN after the disclosure is observable",
    "exit_policy":
        "close of the horizon session; SUSPENDED and DELISTED priced per Plan 2 "
        "§3.4 with recovery factor 0.0 headline; CENSORED events get no row",
    "cost_policy":
        "full stack: statutory round-trip from configs/costs.yml (date-effective) "
        "PLUS sqrt impact Y=1.0 at config participation — the pessimistic level, "
        "chosen in advance so the cost assumption cannot be relaxed after seeing "
        "the result",
    "benchmark_policy":
        "CHAR_MATCHED primary (size x momentum x volatility; industry "
        "UNAVAILABLE, sector_history is IMPOSSIBLE per 0057). EW_TOP500 reported "
        "alongside because CHAR_MATCHED covers 74% of outcomes.",
    "training_period": "2006-01-02 .. 2015-12-31  (FORMATION — tiers formed here only)",
    "validation_period": "none; the walk-forward split IS the validation",
    "final_test_period": "2016-01-01 .. 2026-09-10  (EVALUATION — touched once)",
    "search_space_definition":
        "ONE specification, no free parameters. Tier score = mean excess return "
        "vs CHAR_MATCHED at 63 sessions over formation-period deals. Entities "
        "ranked by that score; TOP tier = top third, BOTTOM tier = bottom third. "
        "No threshold is tuned and no alternative scoring is tried.",
    "test_count": 24,
    "multiple_testing_policy":
        "Benjamini-Hochberg FDR at 5% across all 24 entity-level tests. The "
        "family is the entity screen, declared here at 24 BEFORE running, not "
        "read off the output.",
    "permutation_policy":
        "moving-block bootstrap, block = 63 sessions (the holding period), "
        "10,000 draws, seed 20260911, resampling whole months to preserve "
        "cross-sectional and serial dependence",
    "pass_bar":
        "The TOP tier must (a) contain at least one entity passing BH-FDR 5% "
        "in-sample on 2006-2015, AND (b) beat its benchmark net-of-costs on "
        "2016-2026 out-of-sample. Both, not either.",
    "kill_criteria":
        "If no tier passes FDR in-sample AND beats the benchmark net-of-costs "
        "out-of-sample, deals-based Engine 1 is DEAD and the verdict is recorded "
        "as a governance artefact.",
    "exploratory_prior_run": json.dumps({
        "note": "the 24-entity population and its role classification were "
                "derived from names and deal counts only; no forward return was "
                "computed before this registration",
        "counts_seen": {"directional_deals": 60775, "entities_normalised": 19248,
                        "candidates_30d_12m": 133, "long_only": 24},
    }),
}

EXPERIMENT = {"experiment_id": EXPERIMENT_ID, "engine_id": "ENGINE_1_DEALS",
              "status": "REGISTERED", "decision_reason": None}


def main() -> int:
    import sqlite3

    sh = spec_hash(SPEC)
    trials_before = families.persisted_counter("TRACK_D_DEALS")
    row = {**EXPERIMENT, **SPEC, "spec_hash": sh, "created_at": NOW,
           "created_by": "Markandeya Varma (owner) / Claude Opus 5",
           "configuration_json": json.dumps({"primary_horizon_sessions": 63,
                                             "tiers": 3, "fdr_alpha": 0.05,
                                             "formation_end": "2015-12-31"}),
           "code_commit_hash": COMMIT, "trials_before": trials_before}
    con = sqlite3.connect(str(governance_db(None)))
    cols = [r[1] for r in con.execute("PRAGMA table_info(experiment_registry)")]
    use = {k: v for k, v in row.items() if k in cols}
    con.execute(
        f"INSERT OR REPLACE INTO experiment_registry ({','.join(use)}) "
        f"VALUES ({','.join('?' * len(use))})", list(use.values()))
    con.commit()
    print(f"  experiment_id  : {EXPERIMENT_ID}")
    print(f"  spec_hash      : {sh}")
    print(f"  trials_before  : {trials_before}")
    print(f"  test_count     : {SPEC['test_count']}  (declared, not derived)")
    print(f"  status         : REGISTERED — no result computed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
