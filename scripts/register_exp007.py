"""Pre-register exp_007 — does a stock keep drifting after a governance resignation?

The draft is docs/plan/EXP007_REGISTRATION_DRAFT.md; the research and power,
docs/plan/EXP007_RESIGNATIONS_AND_INDUSTRY_PLAN.md and docs/reports/EXP007_POWER.md.
Owner choices (2026-10-16): CEO/MD and CFO pooled with auditors and independent
directors ("yeah include them also"); one test on the whole sample, no
explore; t <= -1.645 one-sided with a -0.50% effect floor.

The event list — every (filing date, ISIN, role) the frozen rule yields with a
filing date on or before the data date — is hashed into the spec, so the read
can show it used the same events.

REGISTERING IS TYPED, NEVER DEFAULTED:

    RESEARCH_ENV=prod .venv/bin/python scripts/register_exp007.py              # check only
    RESEARCH_ENV=prod .venv/bin/python scripts/register_exp007.py --rehearse   # a throwaway copy
    RESEARCH_ENV=prod .venv/bin/python scripts/register_exp007.py --register   # the real registry
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.hashing import spec_hash  # noqa: E402
from src.common.paths import governance_db  # noqa: E402
from src.governance import registration as reg  # noqa: E402
from src.research import families, measure, resignations  # noqa: E402
from src.research import resignation_study as S  # noqa: E402

DATA_DATE = measure.REPRODUCIBILITY_HORIZON           # filings and returns end here
POWER = {"script": "src/research/resignation_study.py power", "date": "2026-10-16",
         "full_63s_char_matched": {"events": 4894, "cohorts": 150, "cohort_sd": 0.0574, "mde": 0.0131,
                                   "bound": 0.015, "ratio": 0.88},
         "confirm_only_63s": {"cohorts": 90, "ratio": 1.00}, "note": "dispersion only; no mean read"}


def frozen_events() -> list[resignations.Event]:
    rows, sessions = S._load()
    return [e for e in S.governance_events(rows, sessions) if e.date <= DATA_DATE]


def build_spec(evs: list[resignations.Event]) -> dict:
    ev_json = json.dumps([[e.date, e.isin, e.role] for e in evs], separators=(",", ":"))
    by_role = {r: sum(1 for e in evs if e.role == r) for r in sorted(resignations.GOVERNANCE)}
    return {
        "hypothesis":
            "After a listed company discloses the resignation of its statutory auditor, an independent director, "
            "its CEO/MD/whole-time director or its CFO, its stock underperforms its CHAR_MATCHED peers over the "
            "63 sessions that follow the first open after the filing.",
        "prior_belief":
            "Moderate, stated before any mean in this project. The announcement reaction is documented (about "
            "-1.3% over four days for independent directors in India, Chakrabarti, Subramanian & Tung; a further "
            "-2% over 30 days after CFO exits in one unverified report). Drift after the first open is not "
            "established; a null is likely and informative (the market adjusts on day one).",
        "data_version":
            f"NSE corporate announcements as archived (2014-01-01 onward), price_spine_adj, char_panel, as of the "
            f"registration commit; filings and returns to {DATA_DATE}.",
        "universe_definition":
            "every company with a governance resignation filing whose ISIN is in security_master and which has a "
            "forward return (suspension-spanning windows excluded, measure._returns_sql)",
        "participant_definition": "not applicable: the event is the company's own filing",
        "signal_definition":
            "a filing whose text reports the resignation of a statutory auditor, an independent director, a "
            "CEO/MD/whole-time/executive director, or a CFO, by src/research/resignations.py at the registration "
            "commit (role read near each mention of resigning; subsidiaries' auditors and unreadable roles "
            "excluded); one per company per 21 sessions",
        "event_count": len(evs),
        "events_by_role": json.dumps(by_role, sort_keys=True),
        "event_set_sha256": hashlib.sha256(ev_json.encode()).hexdigest(),
        "interpretation_mode": "EVENT",
        "holding_period": "63 sessions (primary); 21 reported, never tested",
        "entry_policy": "the open of the first session after the filing date",
        "exit_policy": "the close 63 sessions later; a window spanning a suspension is no observation",
        "cost_policy": "a short book on the events at the pessimistic costs.yml level, REPORTED, never tested",
        "benchmark_policy":
            "CHAR_MATCHED primary (outcomes.py's ladder: size x momentum x volatility, self-excluded, >= 10 "
            "names); CHAR_MATCHED_IND (sector x size tercile, then sector, then the CHAR_MATCHED ladder) and the "
            "same-session market mean reported",
        "training_period": "none: nothing is fitted",
        "validation_period": "none",
        "final_test_period":
            f"every event 2014-01-01 .. {DATA_DATE}, read ONCE; no explore half (draft §4: nothing in the design "
            "is shaped by returns, and no mean has been read for any period)",
        "search_space_definition": "none: one event definition, one horizon, one benchmark",
        "test_count": 1,
        "multiple_testing_policy":
            f"one test, the first in {S.FAMILY} (a new family, carried 0); bar t <= {S.T_BAR}",
        "permutation_policy": "none; the serial-corrected cohort t is the test",
        "pass_bar":
            f"DRIFT_CONFIRMED if the mean monthly-cohort abnormal return has t <= {S.T_BAR} (one-sided, Bartlett "
            f"inflation with the lag covering the 3-month overlap, 0033) AND the mean <= {S.EFFECT_FLOOR:.2%}. "
            "SIGNIFICANT_BUT_SMALL if only the t passes, reported and not passed. Otherwise NO_DRIFT.",
        "kill_criteria": f"fewer than {S.MIN_COHORTS} monthly cohorts with an event at the read -> UNDERPOWERED, unread",
        "confounds":
            "size, momentum, volatility CONTROLLED (CHAR_MATCHED); industry REPORTED (CHAR_MATCHED_IND covers ~31% "
            "of events at the sector rungs); the announcement reaction EXCLUDED by next-open entry; clustered "
            "resignations CONTROLLED (one per company per 21 sessions); the SEBI auditor circular (Oct 2019) "
            "REPORTED as a pre/post split",
        "exploratory_prior_run": json.dumps(POWER, sort_keys=True),
        "trial_family": S.FAMILY,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rehearse", action="store_true")
    ap.add_argument("--register", action="store_true")
    a = ap.parse_args()
    dirty = reg.dirty_code()
    if dirty and a.register:
        print("  REFUSED: uncommitted code or config — code_commit_hash would name other code:")
        print("\n".join(f"    {d}" for d in dirty))
        return 1
    evs = frozen_events()
    spec = build_spec(evs)
    print(f"  events            : {spec['event_count']:,} {spec['events_by_role']}")
    print(f"  event_set_sha256  : {spec['event_set_sha256']}")
    if not (a.register or a.rehearse):
        print("  CHECK ONLY: nothing written. --rehearse on a copy, --register for the real registry.")
        return 0
    real = governance_db(None)
    target = real
    if a.rehearse:
        target = Path(tempfile.mkdtemp(prefix="exp007_rehearsal_")) / real.name
        shutil.copy2(real, target)
        print(f"  REHEARSAL on a copy: {target}")
    con = sqlite3.connect(str(target))
    try:
        sh = reg.register(con, S.EXPERIMENT_ID, S.ENGINE_ID, spec,
                          {"family": S.FAMILY, "horizon_sessions": S.PRIMARY_SESSIONS, "t_bar": S.T_BAR,
                           "effect_floor": S.EFFECT_FLOOR, "min_cohorts": S.MIN_COHORTS, "data_date": DATA_DATE},
                          reg.head(), families.persisted_counter(S.FAMILY),
                          "Markandeya Varma (owner) / Claude Opus 5.5")
    except RuntimeError as e:
        print(f"  REFUSED: {e}")
        return 1
    finally:
        con.close()
        if a.rehearse:
            shutil.rmtree(target.parent, ignore_errors=True)
    assert sh == spec_hash(spec)
    print(f"  experiment_id     : {S.EXPERIMENT_ID}\n  spec_hash         : {sh}\n  family            : {S.FAMILY}")
    print(f"  stored fields     : {len(spec)} — the stored row reproduces the hash")
    print("  status            : " + ("REHEARSED — nothing registered" if a.rehearse else "REGISTERED — no mean read"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
