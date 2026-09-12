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

from src.common.paths import governance_db  # noqa: E402
from src.governance import provenance as prov  # noqa: E402

MEMO = Path(__file__).resolve().parents[1] / "docs" / "reports" / "SEASONALITY_POWER.md"
LOGICAL_NAME = "engine_2_seasonality_power_verdict"
PRODUCED_BY = "scripts/register_engine2_verdict.py"


def _refuse_an_empty_ledger() -> str | None:
    """Registering into a ledger with no history is not registering.

    MEASURED 2026-09-12, and this guard exists because of it. Run on a machine
    with no warehouse, provenance._con() called migrate_sqlite() and CREATED a
    governance database, then wrote this verdict into it as the only row. The
    script printed a hash and exited 0. Nothing was wrong with the code and the
    result was worthless: no prior artefacts, no trial counters, an empty
    merkle_log, and therefore no append-only chain for the row to belong to.

    A fresh ledger is indistinguishable from the real one at the moment of
    insert, so the check has to be on CONTENT. If the project's own earlier
    verdicts are absent, this is not the production ledger.
    """
    import sqlite3

    db = governance_db(None)
    if not Path(db).exists():
        return f"{db} does not exist; this is not the production ledger"
    con = sqlite3.connect(str(db))
    try:
        try:
            arte = con.execute("SELECT COUNT(*) FROM artefact").fetchone()[0]
            merkle = con.execute("SELECT COUNT(*) FROM merkle_log").fetchone()[0]
        except sqlite3.OperationalError as e:
            return f"{db} has no governance schema ({e})"
    finally:
        con.close()
    if arte == 0 or merkle == 0:
        return (f"{db} holds {arte} artefact(s) and {merkle} merkle row(s) — an "
                f"empty ledger. The real one carries prop_hft_classifier_coverage "
                f"and engine_1_deals_entity_verdict. Refusing to register a "
                f"verdict into a database that has no history to append to.")
    return None


def main() -> int:
    if not MEMO.exists():
        print(f"FATAL: {MEMO} does not exist", file=sys.stderr)
        return 1
    if (why := _refuse_an_empty_ledger()) is not None:
        print(f"REFUSED: {why}", file=sys.stderr)
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
