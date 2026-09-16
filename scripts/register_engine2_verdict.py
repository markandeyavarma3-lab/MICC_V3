"""Record the Engine 2 (seasonality) feasibility verdict as a governance artefact.

THIS REGISTERS A VERDICT, NOT AN EXPERIMENT. No experiment is pre-registered here
because none is going to be run: the memo's finding is that no seasonality
specification has the power to be worth running. The artefact is the memo itself,
content-addressed, the same way `prop_hft_classifier_coverage` and
`engine_1_deals_entity_verdict` were recorded.

IT TOUCHES NO WAREHOUSE. `docs/reports/SEASONALITY_POWER.md` is pure arithmetic
over figures already measured and committed in configs/. Nothing here reads
price_spine_adj, and nothing writes seasonality_cell.

FINAL ALPHA-CANDIDATE VERDICT. With Engine 1 (deals) recorded DEAD as
`engine_1_deals_entity_verdict` and Engine 2 (seasonality) DEAD here, the
project has no remaining alpha candidate. `params.final_alpha_candidate_verdict`
marks that, so the claim is queryable rather than only narrated in a memo.
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
            "final_alpha_candidate_verdict": True,
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
    print(f"  type           : RESULT")
    print(f"  verdict        : DEAD (binding constraint: SAMPLE SIZE)")
    print(f"  final alpha-candidate verdict for the project: YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
