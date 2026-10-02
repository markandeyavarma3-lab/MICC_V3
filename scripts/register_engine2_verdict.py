"""Record the Engine 2 (seasonality) feasibility verdict as a governance artefact.

THIS REGISTERS A VERDICT, NOT AN EXPERIMENT. No experiment is pre-registered here
because none is going to be run: the memo's finding is that no seasonality
specification has the power to be worth running. The artefact is the memo itself,
content-addressed, the same way `prop_hft_classifier_coverage` and
`engine_1_deals_entity_verdict` were recorded.

IT TOUCHES NO WAREHOUSE. `docs/reports/SEASONALITY_POWER.md` is pure arithmetic
over figures already measured and committed in configs/. Nothing here reads
price_spine_adj, and nothing writes seasonality_cell.

NOT THE FINAL ALPHA-CANDIDATE VERDICT — CORRECTED 2026-10-02, BEFORE THE FIRST
REAL REGISTRATION. This script was written 2026-09-12 to mark the project as
having no remaining alpha candidate, which was true that day. By the time it
first ran against the real ledger it was not: exp_004 (institutional holding
change) was rehearsed and waiting on coverage, and promoter sells had measured
1.13x short. The ledger is append-only, so a stale claim written into it could
never be withdrawn — only contradicted. `final_alpha_candidate_verdict` is
False and `remaining_candidates` names what is still open.

SCOPE. The memo is about calendar cells (Track S1, Phase 7). It does not cover
the signal-combination track (TRACK_S_SIGNALS) or the procedure test
(TRACK_S_PROCEDURE), whose arithmetic is different: a signal fires many times
a year, so walk-forward works natively (PLAN_4 §12).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.governance import provenance as prov  # noqa: E402
from src.governance.ledger import LedgerRefused, require_populated_ledger  # noqa: E402

MEMO = Path(__file__).resolve().parents[1] / "docs" / "reports" / "SEASONALITY_POWER.md"
LOGICAL_NAME = "engine_2_seasonality_power_verdict"
PRODUCED_BY = "scripts/register_engine2_verdict.py"


def main() -> int:
    if not MEMO.exists():
        print(f"FATAL: {MEMO} does not exist", file=sys.stderr)
        return 1
    try:
        require_populated_ledger(None)
    except LedgerRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        print("The memo stands; only its registration is outstanding.", file=sys.stderr)
        return 2
    commit = subprocess.run(["git", "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    digest = prov.register_file(
        MEMO,
        artefact_type="RESULT",
        logical_name=LOGICAL_NAME,
        produced_by=PRODUCED_BY,
        params={
            "verdict": "DEAD",
            "binding_constraint": "SAMPLE_SIZE",
            "engine_id": "ENGINE_2_SEASONALITY",
            "final_alpha_candidate_verdict": False,
            "remaining_candidates": [
                "exp_004_holdings_change — rehearsed, registration pending coverage (0076)",
                "insider promoter sells, 12m — 1.13x short (docs/reports/INSIDER_POWER.md); re-measure yearly",
            ],
            "scope": "Track S1 calendar cells and Phase 7 seasonality; NOT TRACK_S_SIGNALS or TRACK_S_PROCEDURE",
            # The numbers the verdict turns on, so the artefact is queryable
            # without re-reading the prose. All from src/research/seasonality_power.py.
            "mde_bps_monthly_pooled_bonferroni_31_9M": 538,
            "mde_bps_monthly_pooled_no_correction": 219,
            "largest_spec_clearing_bar_mde_bps": 123,
            "largest_spec_clearing_bar": "<=20 pre-registered hypotheses, >=6-month window",
            "years_required_for_100bps_at_m1": 96,
            "years_available": 21,
            "prior_external_search_cells": 31_893_556,
            "rho_cross_sectional": 0.2350,
            "n_eff_of_4200_names": 4.25,
            "warehouse_queried": False,
            "seasonality_cell_written": False,
            "reproduced_by": "tests/test_seasonality_power.py",
            "code_commit": commit,
        },
    )
    print(f"  artefact       : {LOGICAL_NAME}")
    print(f"  hash           : {digest}")
    print("  type           : RESULT")
    print("  verdict        : DEAD (binding constraint: SAMPLE SIZE)")
    print("  final alpha-candidate verdict for the project: NO — exp_004 and promoter sells remain")
    print("  scope          : calendar seasonality (Track S1 / Phase 7) only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
