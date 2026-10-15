"""Record the family charges four registered experiments never wrote.

FOUND 2026-10-15 (project audit). `family_charge` holds the exploration
charges (confounds, delisting) and exp_004's three tests — and nothing for the
primary tests of exp_001, exp_002, exp_003 or exp_005. Their run paths never
called families.commit_charge, so every family counter undercounts:
TRACK_D_DEALS reads 215 without exp_001's 2 and exp_002's 24 tests,
TRACK_O_POSITIONING 0 without exp_003's 8, and TRACK_S_PROCEDURE 0 although
exp_005 used its three configurations. exp_006 would have been registered with
"trials_before 0" in a family exp_005 had already used.

What this changes: future bars only. All four experiments are REJECTED and no
verdict moves. Each charge says it was recorded late, and why. The ledger is
append-only (triggers refuse updates and deletes), so this is written once.

    RESEARCH_ENV=prod .venv/bin/python scripts/backfill_family_charges.py              # show only
    RESEARCH_ENV=prod .venv/bin/python scripts/backfill_family_charges.py --rehearse   # on a copy
    RESEARCH_ENV=prod .venv/bin/python scripts/backfill_family_charges.py --commit     # the real ledger
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.paths import governance_db  # noqa: E402
from src.research import families  # noqa: E402

LATE = "Recorded late on 2026-10-15 (project audit): the run path never committed this charge. "
#: (family, experiment, trials = the registered test_count, what was tested)
CHARGES = [
    ("TRACK_D_DEALS", "exp_001_bulk_deal_avoidance_filter", 2,
     "exp_001 primary: the avoidance filter on two holdouts (registry test_count 2)"),
    ("TRACK_D_DEALS", "exp_002_entity_persistence", 24,
     "exp_002 primary: 24 entity-level persistence tests (registry test_count 24)"),
    ("TRACK_O_POSITIONING", "exp_003_participant_oi_category", 8,
     "exp_003 primary: 4 categories x 2 signal columns x 1 horizon (registry test_count 8)"),
    ("TRACK_S_PROCEDURE", "exp_005_scan_procedure", 3,
     "exp_005 primary: the procedure at 3 values of N; width does not charge, family size 3"),
]


def already(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT experiment_id FROM family_charge WHERE experiment_id IS NOT NULL")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rehearse", action="store_true", help="write to a throwaway copy of the governance db")
    ap.add_argument("--commit", action="store_true", help="write the REAL ledger (append-only, once)")
    a = ap.parse_args()
    real = governance_db(None)
    target = real
    tmp = None
    if a.rehearse:
        tmp = Path(tempfile.mkdtemp(prefix="charges_rehearsal_"))
        target = tmp / real.name
        shutil.copy2(real, target)
        print(f"  REHEARSAL on a copy: {target}")
    con = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        done = already(con)
    finally:
        con.close()
    todo = [c for c in CHARGES if c[1] not in done]
    for fam, exp, n, what in CHARGES:
        print(f"  {fam:<20} {exp:<36} {n:>3}  {'already recorded' if exp in done else 'MISSING'}")
    if not todo:
        print("  nothing to record.")
        return 0
    if not (a.rehearse or a.commit):
        print("  SHOW ONLY: nothing written. --rehearse on a copy, --commit for the real ledger.")
        return 0
    orig = families._con
    families._con = lambda env=None: sqlite3.connect(str(target))      # the copy, or the real db
    try:
        for fam, exp, n, what in todo:
            before = families.persisted_counter(fam)
            ch = families.commit_charge(fam, trials_added=n, description=LATE + what, experiment_id=exp)
            print(f"  wrote {fam:<20} {exp:<36} before {before:>4} -> after {ch.trials_after:>4} "
                  f"(added {ch.trials_added}); bar |t| >= {ch.bar.required_t:.2f}")
    finally:
        families._con = orig
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    print("  REHEARSED — real ledger untouched" if a.rehearse else "  COMMITTED to the real ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
